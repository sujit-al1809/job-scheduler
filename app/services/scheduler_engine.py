"""The scheduler's core work, shared by the scheduler process and its tests.

Two responsibilities, both safe to run from multiple scheduler instances at once
thanks to ``FOR UPDATE SKIP LOCKED``:

1. Promote due ``scheduled`` jobs to ``queued``.
2. Materialize one fresh job per due ``scheduled_jobs`` (cron) row, then advance
   its ``next_run_at`` via croniter.

Recurring templates never execute directly — the scheduler always materializes a
concrete ``jobs`` row (CLAUDE.md invariant 7).
"""
from __future__ import annotations

import datetime as dt

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobLog, Queue, RetryPolicy, ScheduledJob
from app.models.enums import JobStatus
from app.services import job_state

_UTC = dt.timezone.utc
_DEFAULT_MAX_ATTEMPTS = 5


def _utcnow() -> dt.datetime:
    return dt.datetime.now(tz=_UTC)


def next_cron_time(cron_expr: str, base: dt.datetime) -> dt.datetime:
    """Return the next fire time strictly after ``base`` for ``cron_expr``."""
    itr = croniter(cron_expr, base)
    return itr.get_next(dt.datetime)


async def _max_attempts_for_queue(session: AsyncSession, queue: Queue) -> int:
    if queue.retry_policy_id is not None:
        policy = await session.get(RetryPolicy, queue.retry_policy_id)
        if policy is not None:
            return policy.max_attempts
    return _DEFAULT_MAX_ATTEMPTS


async def promote_due_scheduled_jobs(
    session: AsyncSession, *, now: dt.datetime | None = None, limit: int = 500
) -> int:
    """Flip due ``scheduled`` jobs to ``queued``. Commits. Returns the count."""
    now = now or _utcnow()
    due = (
        await session.scalars(
            select(Job)
            .where(Job.status == JobStatus.scheduled, Job.run_at <= now)
            .order_by(Job.run_at.asc(), Job.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for job in due:
        await job_state.transition(
            session, job, JobStatus.queued, message="promoted_from_scheduled"
        )
    await session.commit()
    return len(due)


async def materialize_due_cron_jobs(
    session: AsyncSession, *, now: dt.datetime | None = None, limit: int = 500
) -> list[int]:
    """Materialize one job per due cron template and advance next_run_at. Commits.

    Returns the ids of the jobs created this tick.
    """
    now = now or _utcnow()
    due = (
        await session.scalars(
            select(ScheduledJob)
            .where(
                ScheduledJob.is_active.is_(True),
                ScheduledJob.next_run_at <= now,
            )
            .order_by(ScheduledJob.next_run_at.asc(), ScheduledJob.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()

    created_ids: list[int] = []
    for template in due:
        queue = await session.get(Queue, template.queue_id)
        if queue is None:  # queue deleted out from under the template
            template.is_active = False
            continue

        job = Job(
            queue_id=queue.id,
            project_id=queue.project_id,
            type=template.type,
            payload=template.payload,
            status=JobStatus.queued,
            priority=template.priority
            if template.priority is not None
            else queue.priority,
            run_at=now,
            max_attempts=await _max_attempts_for_queue(session, queue),
        )
        session.add(job)
        await session.flush()
        session.add(
            JobLog(
                job_id=job.id,
                level="info",
                message=f"materialized_from_schedule ({template.id})",
            )
        )

        # Advance to the next fire time so this row is not due again this tick.
        template.next_run_at = next_cron_time(template.cron_expr, now)
        created_ids.append(job.id)

    await session.commit()
    return created_ids
