"""Queue business logic: CRUD, pause/resume, retry-policy wiring, and stats.

Every operation is reached through the owning project, which is itself org-scoped,
so cross-org access surfaces as 404.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.models import Job, JobExecution, Project, Queue, RetryPolicy
from app.models.enums import ExecutionStatus, JobStatus
from app.schemas.queue import QueueCreate, QueueUpdate, RetryPolicyIn
from app.services.project import get_project_or_404


async def get_queue_for_org(
    session: AsyncSession, org_id: int, queue_id: int
) -> Queue:
    """Fetch a queue by its global id, enforcing that it belongs to the caller's org.

    Jobs reference queues by top-level id (``/queues/{id}/jobs``), so this resolves
    the queue through its project's org without a project id in the path.
    """
    queue = await session.scalar(
        select(Queue)
        .join(Project, Project.id == Queue.project_id)
        .where(Queue.id == queue_id, Project.org_id == org_id)
    )
    if queue is None:
        raise NotFoundError("Queue not found.", code="QUEUE_NOT_FOUND")
    return queue


async def _resolve_retry_policy_id(
    session: AsyncSession,
    project_id: int,
    retry_policy_id: int | None,
    inline: RetryPolicyIn | None,
) -> int | None:
    if retry_policy_id is not None and inline is not None:
        raise BadRequestError(
            "Provide either retry_policy_id or retry_policy, not both.",
            code="RETRY_POLICY_AMBIGUOUS",
        )
    if inline is not None:
        policy = RetryPolicy(
            project_id=project_id,
            name=inline.name,
            strategy=inline.strategy,
            base_delay_s=inline.base_delay_s,
            max_delay_s=inline.max_delay_s,
            max_attempts=inline.max_attempts,
            jitter=inline.jitter,
        )
        session.add(policy)
        await session.flush()
        return policy.id
    if retry_policy_id is not None:
        exists = await session.scalar(
            select(RetryPolicy.id).where(
                RetryPolicy.id == retry_policy_id,
                RetryPolicy.project_id == project_id,
            )
        )
        if exists is None:
            raise NotFoundError(
                "Retry policy not found.", code="RETRY_POLICY_NOT_FOUND"
            )
        return retry_policy_id
    return None


async def get_queue_or_404(
    session: AsyncSession, org_id: int, project_id: int, queue_id: int
) -> Queue:
    await get_project_or_404(session, org_id, project_id)  # enforce org ownership
    queue = await session.scalar(
        select(Queue).where(Queue.id == queue_id, Queue.project_id == project_id)
    )
    if queue is None:
        raise NotFoundError("Queue not found.", code="QUEUE_NOT_FOUND")
    return queue


async def create_queue(
    session: AsyncSession, org_id: int, project_id: int, body: QueueCreate
) -> Queue:
    await get_project_or_404(session, org_id, project_id)
    dupe = await session.scalar(
        select(Queue.id).where(
            Queue.project_id == project_id, Queue.name == body.name
        )
    )
    if dupe is not None:
        raise ConflictError(
            "A queue with this name already exists.", code="QUEUE_NAME_TAKEN"
        )
    policy_id = await _resolve_retry_policy_id(
        session, project_id, body.retry_policy_id, body.retry_policy
    )
    queue = Queue(
        project_id=project_id,
        name=body.name,
        priority=body.priority,
        concurrency_limit=body.concurrency_limit,
        retry_policy_id=policy_id,
    )
    session.add(queue)
    await session.flush()
    await session.refresh(queue)
    return queue


async def list_queues(
    session: AsyncSession, org_id: int, project_id: int, limit: int, offset: int
) -> tuple[list[Queue], int]:
    await get_project_or_404(session, org_id, project_id)
    total = await session.scalar(
        select(func.count()).select_from(Queue).where(Queue.project_id == project_id)
    )
    rows = (
        await session.scalars(
            select(Queue)
            .where(Queue.project_id == project_id)
            .order_by(Queue.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)


async def update_queue(
    session: AsyncSession,
    org_id: int,
    project_id: int,
    queue_id: int,
    body: QueueUpdate,
) -> Queue:
    queue = await get_queue_or_404(session, org_id, project_id, queue_id)
    if body.name is not None and body.name != queue.name:
        dupe = await session.scalar(
            select(Queue.id).where(
                Queue.project_id == project_id,
                Queue.name == body.name,
                Queue.id != queue_id,
            )
        )
        if dupe is not None:
            raise ConflictError(
                "A queue with this name already exists.", code="QUEUE_NAME_TAKEN"
            )
        queue.name = body.name
    if body.priority is not None:
        queue.priority = body.priority
    if body.concurrency_limit is not None:
        queue.concurrency_limit = body.concurrency_limit
    if body.retry_policy_id is not None or body.retry_policy is not None:
        queue.retry_policy_id = await _resolve_retry_policy_id(
            session, project_id, body.retry_policy_id, body.retry_policy
        )
    await session.flush()
    await session.refresh(queue)
    return queue


async def delete_queue(
    session: AsyncSession, org_id: int, project_id: int, queue_id: int
) -> None:
    queue = await get_queue_or_404(session, org_id, project_id, queue_id)
    await session.delete(queue)
    await session.flush()


async def set_paused(
    session: AsyncSession,
    org_id: int,
    project_id: int,
    queue_id: int,
    paused: bool,
) -> Queue:
    queue = await get_queue_or_404(session, org_id, project_id, queue_id)
    queue.is_paused = paused
    await session.flush()
    await session.refresh(queue)
    return queue


async def queue_stats(
    session: AsyncSession, org_id: int, project_id: int, queue_id: int
) -> dict:
    queue = await get_queue_or_404(session, org_id, project_id, queue_id)

    status_rows = await session.execute(
        select(Job.status, func.count())
        .where(Job.queue_id == queue.id)
        .group_by(Job.status)
    )
    by_status = {status.value: 0 for status in JobStatus}
    total = 0
    for status, count in status_rows.all():
        by_status[status.value] = count
        total += count

    oldest_queued_run_at = await session.scalar(
        select(func.min(Job.run_at)).where(
            Job.queue_id == queue.id, Job.status == JobStatus.queued
        )
    )
    oldest_queued_age_s: float | None = None
    if oldest_queued_run_at is not None:
        now = dt.datetime.now(tz=dt.timezone.utc)
        oldest_queued_age_s = max(0.0, (now - oldest_queued_run_at).total_seconds())

    avg_duration_ms = await session.scalar(
        select(func.avg(JobExecution.duration_ms))
        .select_from(JobExecution)
        .join(Job, Job.id == JobExecution.job_id)
        .where(
            Job.queue_id == queue.id,
            JobExecution.status == ExecutionStatus.completed,
        )
    )

    in_flight = (
        by_status[JobStatus.claimed.value] + by_status[JobStatus.running.value]
    )
    return {
        "queue_id": queue.id,
        "total": total,
        "by_status": by_status,
        "oldest_queued_age_s": oldest_queued_age_s,
        "avg_duration_ms": float(avg_duration_ms) if avg_duration_ms is not None else None,
        "in_flight": in_flight,
    }
