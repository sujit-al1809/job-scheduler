"""Failure recovery: the dead-worker reaper and graceful in-flight release.

Both paths requeue a worker's in-flight (``claimed``/``running``) jobs and finalize
any dangling ``running`` execution rows so metrics stay honest.

* Reaper (runs in the scheduler): a worker silent past ``HEARTBEAT_TIMEOUT_S`` is
  marked ``dead`` and its jobs are requeued with an incremented attempt count and a
  ``requeued_after_worker_death`` log line (CLAUDE.md invariant 5).
* Graceful release (runs in the worker on shutdown): the worker's own unfinished
  jobs are released back to ``queued`` without consuming an extra attempt
  (invariant 6).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobExecution, Worker
from app.models.enums import ExecutionStatus, JobStatus, WorkerStatus
from app.services import job_state

_UTC = dt.timezone.utc
_IN_FLIGHT = (JobStatus.claimed, JobStatus.running)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(tz=_UTC)


async def _finalize_orphan_executions(
    session: AsyncSession, job_id: int, reason: str, now: dt.datetime
) -> None:
    """Close any still-``running`` execution rows for a job that lost its worker."""
    orphans = (
        await session.scalars(
            select(JobExecution).where(
                JobExecution.job_id == job_id,
                JobExecution.finished_at.is_(None),
                JobExecution.status == ExecutionStatus.running,
            )
        )
    ).all()
    for execution in orphans:
        execution.status = ExecutionStatus.failed
        execution.error = reason
        execution.finished_at = now
        execution.duration_ms = int(
            (now - execution.started_at).total_seconds() * 1000
        )


async def reap_dead_workers(
    session: AsyncSession, *, timeout_s: float, now: dt.datetime | None = None
) -> dict[str, int]:
    """Mark stale workers dead and requeue their in-flight jobs. Commits."""
    now = now or _utcnow()
    cutoff = now - dt.timedelta(seconds=timeout_s)

    dead = (
        await session.scalars(
            select(Worker)
            .where(
                Worker.status == WorkerStatus.online,
                Worker.last_heartbeat_at < cutoff,
            )
            .with_for_update(skip_locked=True)
        )
    ).all()

    requeued = 0
    for worker in dead:
        worker.status = WorkerStatus.dead
        worker.stopped_at = now
        jobs = (
            await session.scalars(
                select(Job)
                .where(Job.worker_id == worker.id, Job.status.in_(_IN_FLIGHT))
                .with_for_update(skip_locked=True)
            )
        ).all()
        for job in jobs:
            await _finalize_orphan_executions(
                session, job.id, "worker_died", now
            )
            job.attempts += 1  # this attempt was lost to the worker's death
            await job_state.transition(
                session,
                job,
                JobStatus.queued,
                run_at=now,
                level="warning",
                message="requeued_after_worker_death",
            )
            requeued += 1

    await session.commit()
    return {"dead_workers": len(dead), "requeued_jobs": requeued}


async def release_worker_jobs(
    session: AsyncSession, worker_id: int, *, now: dt.datetime | None = None
) -> int:
    """Release a worker's own in-flight jobs back to queued (graceful shutdown)."""
    now = now or _utcnow()
    jobs = (
        await session.scalars(
            select(Job).where(
                Job.worker_id == worker_id, Job.status.in_(_IN_FLIGHT)
            )
        )
    ).all()
    for job in jobs:
        await _finalize_orphan_executions(session, job.id, "worker_stopped", now)
        await job_state.transition(
            session,
            job,
            JobStatus.queued,
            run_at=now,
            message="released_on_shutdown",
        )
    await session.commit()
    return len(jobs)
