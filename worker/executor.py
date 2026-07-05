"""Job execution engine.

Runs a claimed job through ``claimed -> running -> completed|failed`` (retry vs
dead-letter routing on failure is added in commit 11). Each attempt:

* increments ``jobs.attempts`` and creates exactly one ``job_executions`` row,
* runs the registered handler under a timeout,
* persists handler-emitted logs to ``job_logs`` tied to the execution,
* records status, error text, and ``duration_ms``.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Job, JobExecution, JobLog
from app.models.enums import ExecutionStatus, JobStatus
from app.services import job_state
from worker.handlers import JobContext, get_handler

logger = logging.getLogger("worker.executor")

_UTC = dt.timezone.utc
_DEFAULT_TIMEOUT_S = 300.0


def _utcnow() -> dt.datetime:
    return dt.datetime.now(tz=_UTC)


def _timeout_for(payload: dict) -> float:
    if isinstance(payload, dict) and payload.get("timeout_s") is not None:
        try:
            return float(payload["timeout_s"])
        except (TypeError, ValueError):
            return _DEFAULT_TIMEOUT_S
    return _DEFAULT_TIMEOUT_S


async def execute_job(
    session_factory: async_sessionmaker[AsyncSession],
    worker_id: int,
    job_id: int,
) -> ExecutionStatus | None:
    """Execute one claimed job. Returns the execution's terminal status (or None
    if the job was not in a claimable state)."""
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if job is None or job.status is not JobStatus.claimed:
            return None

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
        await session.commit()  # publish running + the execution row

        ctx = JobContext(
            job_id=job.id,
            execution_id=execution.id,
            payload=job.payload if isinstance(job.payload, dict) else {},
            job_type=job.type,
        )
        handler = get_handler(job.type)
        timeout_s = _timeout_for(ctx.payload)

        started = _utcnow()
        exec_status: ExecutionStatus
        error_text: str | None = None
        try:
            await asyncio.wait_for(handler(ctx), timeout=timeout_s)
            exec_status = ExecutionStatus.completed
        except asyncio.TimeoutError:
            exec_status = ExecutionStatus.timeout
            error_text = f"handler timed out after {timeout_s}s"
        except Exception as exc:  # noqa: BLE001
            exec_status = ExecutionStatus.failed
            error_text = str(exc) or exc.__class__.__name__
        finished = _utcnow()

        # Persist handler-emitted logs, tied to this execution.
        for level, message in ctx.logs:
            session.add(
                JobLog(
                    job_id=job.id,
                    execution_id=execution.id,
                    level=level,
                    message=message,
                )
            )

        execution.status = exec_status
        execution.finished_at = finished
        execution.duration_ms = int((finished - started).total_seconds() * 1000)

        if exec_status is ExecutionStatus.completed:
            await job_state.transition(
                session,
                job,
                JobStatus.completed,
                execution_id=execution.id,
                message="execution_completed",
            )
        else:
            execution.error = error_text
            job.last_error = error_text
            await job_state.transition(
                session,
                job,
                JobStatus.failed,
                execution_id=execution.id,
                level="error",
                message=f"execution_failed: {error_text}",
            )

        await session.commit()
        return exec_status
