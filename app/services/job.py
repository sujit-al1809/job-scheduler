"""Job business logic: submission (immediate/delayed/idempotent), listing, detail,
and cancellation. All status changes route through ``services.job_state``.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError
from app.models import Job, JobLog, Project, Queue, RetryPolicy
from app.models.enums import JobStatus
from app.schemas.job import JobCreate
from app.services import job_state
from app.services.queue import get_queue_for_org

_UTC = dt.timezone.utc

_DEFAULT_MAX_ATTEMPTS = 5


async def _default_max_attempts(session: AsyncSession, queue: Queue) -> int:
    if queue.retry_policy_id is not None:
        policy = await session.get(RetryPolicy, queue.retry_policy_id)
        if policy is not None:
            return policy.max_attempts
    return _DEFAULT_MAX_ATTEMPTS


async def create_job(
    session: AsyncSession, org_id: int, queue_id: int, body: JobCreate
) -> tuple[Job, bool]:
    """Create a job. Returns (job, created). ``created`` is False on idempotent replay."""
    queue = await get_queue_for_org(session, org_id, queue_id)
    project_id = queue.project_id  # capture before any flush/rollback

    # Idempotency: a duplicate (project, key) returns the existing job.
    if body.idempotency_key is not None:
        existing = await session.scalar(
            select(Job).where(
                Job.project_id == project_id,
                Job.idempotency_key == body.idempotency_key,
            )
        )
        if existing is not None:
            return existing, False

    now = dt.datetime.now(tz=_UTC)
    if body.delay_s and body.delay_s > 0:
        status = JobStatus.scheduled
        run_at = now + dt.timedelta(seconds=body.delay_s)
    else:
        status = JobStatus.queued
        run_at = now

    job = Job(
        queue_id=queue.id,
        project_id=project_id,
        type=body.type,
        payload=body.payload,
        status=status,
        priority=body.priority if body.priority is not None else queue.priority,
        run_at=run_at,
        max_attempts=body.max_attempts
        if body.max_attempts is not None
        else await _default_max_attempts(session, queue),
        idempotency_key=body.idempotency_key,
    )
    session.add(job)
    try:
        await session.flush()
    except IntegrityError:
        # Lost an idempotency race: another identical submit won. Return theirs.
        await session.rollback()
        if body.idempotency_key is not None:
            existing = await session.scalar(
                select(Job).where(
                    Job.project_id == project_id,
                    Job.idempotency_key == body.idempotency_key,
                )
            )
            if existing is not None:
                return existing, False
        raise

    session.add(
        JobLog(job_id=job.id, level="info", message=f"job_created ({status.value})")
    )
    await session.flush()
    return job, True


def _org_jobs_query(org_id: int):
    return select(Job).join(Project, Project.id == Job.project_id).where(
        Project.org_id == org_id
    )


async def list_jobs(
    session: AsyncSession,
    org_id: int,
    *,
    limit: int,
    offset: int,
    status: JobStatus | None = None,
    queue_id: int | None = None,
    type: str | None = None,
    created_after: dt.datetime | None = None,
    created_before: dt.datetime | None = None,
) -> tuple[list[Job], int]:
    conditions = []
    if status is not None:
        conditions.append(Job.status == status)
    if queue_id is not None:
        conditions.append(Job.queue_id == queue_id)
    if type is not None:
        conditions.append(Job.type == type)
    if created_after is not None:
        conditions.append(Job.created_at >= created_after)
    if created_before is not None:
        conditions.append(Job.created_at <= created_before)

    base = _org_jobs_query(org_id)
    for cond in conditions:
        base = base.where(cond)

    count_q = (
        select(func.count())
        .select_from(Job)
        .join(Project, Project.id == Job.project_id)
        .where(Project.org_id == org_id)
    )
    for cond in conditions:
        count_q = count_q.where(cond)

    total = await session.scalar(count_q)
    rows = (
        await session.scalars(
            base.order_by(Job.id.desc()).limit(limit).offset(offset)
        )
    ).all()
    return list(rows), int(total or 0)


async def get_job_detail(session: AsyncSession, org_id: int, job_id: int) -> Job:
    job = await session.scalar(
        _org_jobs_query(org_id)
        .where(Job.id == job_id)
        .options(selectinload(Job.executions), selectinload(Job.logs))
    )
    if job is None:
        raise NotFoundError("Job not found.", code="JOB_NOT_FOUND")
    return job


async def get_job_or_404(session: AsyncSession, org_id: int, job_id: int) -> Job:
    job = await session.scalar(_org_jobs_query(org_id).where(Job.id == job_id))
    if job is None:
        raise NotFoundError("Job not found.", code="JOB_NOT_FOUND")
    return job


async def cancel_job(session: AsyncSession, org_id: int, job_id: int) -> Job:
    job = await get_job_or_404(session, org_id, job_id)
    # Legal only from a pre-running state; job_state enforces this (409 otherwise).
    await job_state.transition(
        session, job, JobStatus.cancelled, message="cancelled_by_user"
    )
    return job
