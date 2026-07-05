"""Execution engine: lifecycle, job_executions rows, handler logs, timeouts."""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Job, JobExecution, JobLog, Organization, Project, Queue
from app.models.enums import ExecutionStatus, JobStatus
from app.services import worker as worker_service
from worker.claim import claim_jobs
from worker.executor import execute_job

pytestmark = pytest.mark.asyncio

UTC = dt.timezone.utc


async def _seed_one(
    session: AsyncSession, job_type: str, payload: dict, *, max_attempts: int = 5
) -> int:
    org = Organization(name="o")
    session.add(org)
    await session.flush()
    project = Project(org_id=org.id, name="p", api_key="k-" + str(org.id))
    session.add(project)
    await session.flush()
    queue = Queue(project_id=project.id, name="q")
    session.add(queue)
    await session.flush()
    job = Job(
        queue_id=queue.id,
        project_id=project.id,
        type=job_type,
        payload=payload,
        status=JobStatus.queued,
        run_at=dt.datetime.now(tz=UTC) - dt.timedelta(seconds=1),
        max_attempts=max_attempts,
    )
    session.add(job)
    await session.commit()
    return job.id


async def _claim_and_execute(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    job_id: int,
) -> None:
    worker = await worker_service.register_worker(db_session, "w", concurrency=1)
    async with session_factory() as s:
        claimed = await claim_jobs(s, worker.id, batch_size=10)
        await s.commit()
    assert job_id in claimed
    await execute_job(session_factory, worker.id, job_id)


async def test_successful_execution_records_everything(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    job_id = await _seed_one(db_session, "demo.sleep", {"seconds": 0})
    await _claim_and_execute(db_session, session_factory, job_id)

    job = await db_session.get(Job, job_id)
    assert job.status == JobStatus.completed
    assert job.attempts == 1

    execution = await db_session.scalar(
        select(JobExecution).where(JobExecution.job_id == job_id)
    )
    assert execution.status == ExecutionStatus.completed
    assert execution.attempt == 1
    assert execution.duration_ms is not None
    assert execution.finished_at is not None

    # Handler-emitted logs are tied to the execution.
    logs = (
        await db_session.scalars(
            select(JobLog).where(
                JobLog.job_id == job_id, JobLog.execution_id == execution.id
            )
        )
    ).all()
    assert any("sleeping" in log.message for log in logs)


async def test_failing_handler_marks_failed_with_error(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # max_attempts=1 so the single failure is terminal (dead), keeping this test
    # focused on how the *execution* records a failure (retry is covered separately).
    job_id = await _seed_one(
        db_session, "demo.always_fail", {"message": "boom"}, max_attempts=1
    )
    await _claim_and_execute(db_session, session_factory, job_id)

    job = await db_session.get(Job, job_id)
    assert job.status == JobStatus.dead
    assert job.last_error == "boom"

    execution = await db_session.scalar(
        select(JobExecution).where(JobExecution.job_id == job_id)
    )
    assert execution.status == ExecutionStatus.failed
    assert execution.error == "boom"


async def test_timeout_marks_execution_timeout(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # Sleep 5s but allow only 0.1s. max_attempts=1 => terminal after the timeout.
    job_id = await _seed_one(
        db_session, "demo.sleep", {"seconds": 5, "timeout_s": 0.1}, max_attempts=1
    )
    await _claim_and_execute(db_session, session_factory, job_id)

    job = await db_session.get(Job, job_id)
    assert job.status == JobStatus.dead

    execution = await db_session.scalar(
        select(JobExecution).where(JobExecution.job_id == job_id)
    )
    assert execution.status == ExecutionStatus.timeout
    assert "timed out" in (execution.error or "")


async def test_unknown_type_uses_default_noop_handler(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    job_id = await _seed_one(db_session, "totally.unknown", {})
    await _claim_and_execute(db_session, session_factory, job_id)
    job = await db_session.get(Job, job_id)
    assert job.status == JobStatus.completed
