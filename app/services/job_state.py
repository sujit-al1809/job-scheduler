"""The single job state-transition function.

Every status change to a job MUST go through :func:`transition`. It validates the
transition against the state machine, stamps the right timestamps, and appends a
``job_logs`` row. Nothing else in the codebase may ``UPDATE jobs SET status = ...``.

State machine (from CLAUDE.md)::

    scheduled ──> queued ──> claimed ──> running ──> completed
                    ↑           │            │
                    │           ├──> queued  ├──> failed ──> queued (retry)
                    │           └──> ...      └──> queued (requeue on worker death)
                    │                                 failed ──> dead
    any pre-running (scheduled|queued|claimed) ──> cancelled
    dead ──> queued (DLQ retry, fresh)
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Job, JobLog
from app.models.enums import JobStatus

_UTC = dt.timezone.utc


class InvalidTransitionError(AppError):
    status_code = 409
    code = "INVALID_TRANSITION"


# Allowed target states for each source state. Empty set == terminal.
LEGAL_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.scheduled: {JobStatus.queued, JobStatus.cancelled},
    JobStatus.queued: {JobStatus.claimed, JobStatus.cancelled},
    JobStatus.claimed: {JobStatus.running, JobStatus.queued, JobStatus.cancelled},
    # running -> queued covers requeue-on-worker-death and graceful-shutdown release.
    JobStatus.running: {JobStatus.completed, JobStatus.failed, JobStatus.queued},
    JobStatus.failed: {JobStatus.queued, JobStatus.dead},
    JobStatus.dead: {JobStatus.queued},
    JobStatus.completed: set(),
    JobStatus.cancelled: set(),
}


async def transition(
    session: AsyncSession,
    job: Job,
    to: JobStatus,
    *,
    worker_id: int | None = None,
    run_at: dt.datetime | None = None,
    message: str | None = None,
    level: str = "info",
    execution_id: int | None = None,
) -> Job:
    """Move ``job`` to state ``to``, stamping timestamps and logging the change.

    Raises :class:`InvalidTransitionError` if the transition is not permitted.
    """
    frm = job.status
    if to not in LEGAL_TRANSITIONS.get(frm, set()):
        raise InvalidTransitionError(
            f"Cannot transition job from {frm.value} to {to.value}.",
            details={"from": frm.value, "to": to.value},
        )

    now = dt.datetime.now(tz=_UTC)
    job.status = to

    if to is JobStatus.claimed:
        job.claimed_at = now
        job.worker_id = worker_id
    elif to is JobStatus.running:
        job.started_at = now
    elif to is JobStatus.queued:
        # Promotion / retry / release: detach any worker, allow a new run_at.
        job.claimed_at = None
        job.worker_id = None
        if run_at is not None:
            job.run_at = run_at
    elif to in (JobStatus.completed, JobStatus.failed, JobStatus.dead, JobStatus.cancelled):
        job.finished_at = now

    session.add(
        JobLog(
            job_id=job.id,
            execution_id=execution_id,
            level=level,
            message=message or f"{frm.value} -> {to.value}",
        )
    )
    await session.flush()
    return job
