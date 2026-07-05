"""Job execution: run a claimed job through its lifecycle, recording an attempt.

Every attempt creates exactly one ``job_executions`` row (CLAUDE.md invariant 3).
This commit ships a minimal executor (payload-driven sleep); the handler registry
and richer failure/retry handling arrive in commits 10–11.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Job, JobExecution
from app.models.enums import ExecutionStatus, JobStatus
from app.services import job_state

logger = logging.getLogger("worker.executor")

_UTC = dt.timezone.utc


def _utcnow() -> dt.datetime:
    return dt.datetime.now(tz=_UTC)


async def _run_stub(job: Job) -> None:
    """Minimal 'work': sleep for payload.sleep_s (default 0). Replaced in commit 10."""
    sleep_s = 0.0
    if isinstance(job.payload, dict):
        try:
            sleep_s = float(job.payload.get("sleep_s", 0) or 0)
        except (TypeError, ValueError):
            sleep_s = 0.0
    if sleep_s > 0:
        await asyncio.sleep(sleep_s)


async def execute_job(
    session_factory: async_sessionmaker[AsyncSession],
    worker_id: int,
    job_id: int,
) -> None:
    """Execute a single claimed job: claimed -> running -> completed/failed.

    Opens its own transaction. If the job is no longer claimed (e.g. cancelled or
    already picked up), it is a no-op.
    """
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if job is None or job.status is not JobStatus.claimed:
            return

        job.attempts += 1
        execution = JobExecution(
            job_id=job.id,
            attempt=job.attempts,
            worker_id=worker_id,
            status=ExecutionStatus.running,
            started_at=_utcnow(),
        )
        session.add(execution)
        await session.flush()
        await job_state.transition(
            session,
            job,
            JobStatus.running,
            execution_id=execution.id,
            message="execution_started",
        )

        started = _utcnow()
        try:
            await _run_stub(job)
        except Exception as exc:  # noqa: BLE001 — richer handling in commit 11
            execution.status = ExecutionStatus.failed
            execution.error = str(exc)
            execution.finished_at = _utcnow()
            execution.duration_ms = int((execution.finished_at - started).total_seconds() * 1000)
            job.last_error = str(exc)
            await job_state.transition(
                session,
                job,
                JobStatus.failed,
                execution_id=execution.id,
                level="error",
                message=f"execution_failed: {exc}",
            )
            await session.commit()
            return

        finished = _utcnow()
        execution.status = ExecutionStatus.completed
        execution.finished_at = finished
        execution.duration_ms = int((finished - started).total_seconds() * 1000)
        await job_state.transition(
            session,
            job,
            JobStatus.completed,
            execution_id=execution.id,
            message="execution_completed",
        )
        await session.commit()
