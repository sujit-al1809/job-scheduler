"""Retry backoff math and the on-failure decision (retry vs dead-letter).

``compute_delay`` is a pure function (unit-tested against a table). Failure
handling schedules the next attempt (``run_at = now + delay``) or, once attempts
are exhausted, moves the job to ``dead`` and snapshots it into ``dead_letter_jobs``.
Retries are always *scheduled*, never slept (CLAUDE.md invariant 8).
"""
from __future__ import annotations

import datetime as dt
import random

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeadLetterJob, Job, Queue, RetryPolicy
from app.models.enums import JobStatus, RetryStrategy
from app.services import job_state

_UTC = dt.timezone.utc

# Defaults when neither the job nor its queue references a retry policy.
_DEFAULT_STRATEGY = RetryStrategy.exponential
_DEFAULT_BASE_DELAY_S = 5.0
_DEFAULT_MAX_DELAY_S = 3600.0
_DEFAULT_JITTER = True


def compute_delay(
    strategy: RetryStrategy,
    attempt: int,
    *,
    base_delay_s: float,
    max_delay_s: float,
    jitter: bool,
    rng: random.Random | None = None,
) -> float:
    """Delay before the next attempt. ``attempt`` is the attempt that just failed (>=1)."""
    if strategy is RetryStrategy.fixed:
        delay = base_delay_s
    elif strategy is RetryStrategy.linear:
        delay = base_delay_s * attempt
    else:  # exponential
        delay = base_delay_s * (2 ** (attempt - 1))

    delay = min(delay, max_delay_s)
    if jitter:
        factor = (rng or random).uniform(0.8, 1.2)
        delay *= factor
    return delay


async def resolve_retry_params(
    session: AsyncSession, job: Job
) -> tuple[RetryStrategy, float, float, bool]:
    """Effective retry params: job policy > queue policy > defaults."""
    policy_id = job.retry_policy_id
    if policy_id is None:
        queue = await session.get(Queue, job.queue_id)
        policy_id = queue.retry_policy_id if queue is not None else None
    if policy_id is not None:
        policy = await session.get(RetryPolicy, policy_id)
        if policy is not None:
            return (
                policy.strategy,
                policy.base_delay_s,
                policy.max_delay_s,
                policy.jitter,
            )
    return (
        _DEFAULT_STRATEGY,
        _DEFAULT_BASE_DELAY_S,
        _DEFAULT_MAX_DELAY_S,
        _DEFAULT_JITTER,
    )


async def handle_job_failure(
    session: AsyncSession,
    job: Job,
    *,
    execution_id: int,
    error_text: str | None,
) -> JobStatus:
    """Record the failure, then either reschedule a retry or dead-letter the job.

    Returns the job's resulting status (``queued`` for a retry, ``dead`` if exhausted).
    The caller commits.
    """
    job.last_error = error_text
    await job_state.transition(
        session,
        job,
        JobStatus.failed,
        execution_id=execution_id,
        level="error",
        message=f"execution_failed: {error_text}",
    )

    if job.attempts < job.max_attempts:
        strategy, base, max_delay, jitter = await resolve_retry_params(session, job)
        delay = compute_delay(
            strategy,
            job.attempts,
            base_delay_s=base,
            max_delay_s=max_delay,
            jitter=jitter,
        )
        run_at = dt.datetime.now(tz=_UTC) + dt.timedelta(seconds=delay)
        await job_state.transition(
            session,
            job,
            JobStatus.queued,
            run_at=run_at,
            execution_id=execution_id,
            message=(
                f"retry_scheduled: attempt {job.attempts}/{job.max_attempts} "
                f"in {delay:.2f}s"
            ),
        )
        return JobStatus.queued

    # Exhausted: dead-letter with a payload/error snapshot.
    await job_state.transition(
        session,
        job,
        JobStatus.dead,
        execution_id=execution_id,
        level="error",
        message="max_attempts_exhausted",
    )
    session.add(
        DeadLetterJob(
            job_id=job.id,
            project_id=job.project_id,
            queue_id=job.queue_id,
            type=job.type,
            payload=job.payload,
            final_error=error_text,
            attempts=job.attempts,
        )
    )
    return JobStatus.dead
