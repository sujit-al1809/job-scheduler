"""Recovery: dead-worker reaper requeues orphans; graceful shutdown releases in-flight."""
from __future__ import annotations

import asyncio
import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models import (
    Job,
    JobExecution,
    JobLog,
    Organization,
    Project,
    Queue,
    Worker,
)
from app.models.enums import ExecutionStatus, JobStatus, WorkerStatus
from app.services import worker as worker_service
from app.services.recovery import reap_dead_workers, release_worker_jobs
from worker.runtime import WorkerRuntime

pytestmark = pytest.mark.asyncio

UTC = dt.timezone.utc


async def _seed_project_queue(session: AsyncSession) -> tuple[int, int]:
    org = Organization(name="o")
    session.add(org)
    await session.flush()
    project = Project(org_id=org.id, name="p", api_key="k-" + str(org.id))
    session.add(project)
    await session.flush()
    queue = Queue(project_id=project.id, name="q")
    session.add(queue)
    await session.flush()
    await session.commit()
    return project.id, queue.id


async def _seed_inflight_job(
    session: AsyncSession,
    queue_id: int,
    project_id: int,
    worker_id: int,
    *,
    status: JobStatus,
    attempts: int = 1,
    with_running_execution: bool = True,
) -> int:
    now = dt.datetime.now(tz=UTC)
    job = Job(
        queue_id=queue_id,
        project_id=project_id,
        type="demo.sleep",
        status=status,
        worker_id=worker_id,
        claimed_at=now,
        started_at=now if status == JobStatus.running else None,
        attempts=attempts,
        max_attempts=5,
        run_at=now,
    )
    session.add(job)
    await session.flush()
    if with_running_execution:
        session.add(
            JobExecution(
                job_id=job.id,
                attempt=attempts,
                worker_id=worker_id,
                status=ExecutionStatus.running,
                started_at=now,
            )
        )
    await session.commit()
    return job.id


# --------------------------------------------------------------------------- #
# reaper
# --------------------------------------------------------------------------- #
async def test_reaper_requeues_dead_workers_jobs(db_session: AsyncSession) -> None:
    project_id, queue_id = await _seed_project_queue(db_session)
    worker = await worker_service.register_worker(db_session, "zombie", concurrency=2)

    # Make the worker look silent for a long time.
    worker.last_heartbeat_at = dt.datetime.now(tz=UTC) - dt.timedelta(seconds=120)
    await db_session.commit()

    job_id = await _seed_inflight_job(
        db_session, queue_id, project_id, worker.id, status=JobStatus.running, attempts=1
    )

    result = await reap_dead_workers(db_session, timeout_s=30)
    assert result == {"dead_workers": 1, "requeued_jobs": 1}

    await db_session.refresh(worker)
    assert worker.status == WorkerStatus.dead
    assert worker.stopped_at is not None

    job = await db_session.get(Job, job_id)
    await db_session.refresh(job)
    assert job.status == JobStatus.queued
    assert job.worker_id is None
    assert job.attempts == 2  # incremented — that attempt was lost

    # Orphan execution was closed as failed.
    execution = await db_session.scalar(
        select(JobExecution).where(JobExecution.job_id == job_id)
    )
    assert execution.status == ExecutionStatus.failed
    assert execution.error == "worker_died"
    assert execution.finished_at is not None

    # The recovery log line is present.
    log = await db_session.scalar(
        select(JobLog).where(
            JobLog.job_id == job_id, JobLog.message == "requeued_after_worker_death"
        )
    )
    assert log is not None


async def test_reaper_ignores_fresh_workers(db_session: AsyncSession) -> None:
    project_id, queue_id = await _seed_project_queue(db_session)
    worker = await worker_service.register_worker(db_session, "alive", concurrency=2)
    job_id = await _seed_inflight_job(
        db_session, queue_id, project_id, worker.id, status=JobStatus.running
    )

    result = await reap_dead_workers(db_session, timeout_s=30)
    assert result == {"dead_workers": 0, "requeued_jobs": 0}

    job = await db_session.get(Job, job_id)
    await db_session.refresh(job)
    assert job.status == JobStatus.running  # untouched


# --------------------------------------------------------------------------- #
# graceful release
# --------------------------------------------------------------------------- #
async def test_release_worker_jobs_requeues_without_extra_attempt(
    db_session: AsyncSession,
) -> None:
    project_id, queue_id = await _seed_project_queue(db_session)
    worker = await worker_service.register_worker(db_session, "shutting-down", concurrency=2)
    job_id = await _seed_inflight_job(
        db_session, queue_id, project_id, worker.id, status=JobStatus.running, attempts=1
    )

    released = await release_worker_jobs(db_session, worker.id)
    assert released == 1

    job = await db_session.get(Job, job_id)
    await db_session.refresh(job)
    assert job.status == JobStatus.queued
    assert job.worker_id is None
    assert job.attempts == 1  # NOT incremented on graceful release

    execution = await db_session.scalar(
        select(JobExecution).where(JobExecution.job_id == job_id)
    )
    assert execution.status == ExecutionStatus.failed
    assert execution.error == "worker_stopped"


# --------------------------------------------------------------------------- #
# full graceful shutdown via the runtime
# --------------------------------------------------------------------------- #
async def test_runtime_shutdown_releases_in_flight(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, queue_id = await _seed_project_queue(db_session)
    # A long job that will still be running when we ask the worker to stop.
    job = Job(
        queue_id=queue_id,
        project_id=project_id,
        type="demo.sleep",
        payload={"seconds": 30},
        status=JobStatus.queued,
        run_at=dt.datetime.now(tz=UTC) - dt.timedelta(seconds=1),
        max_attempts=5,
    )
    db_session.add(job)
    await db_session.commit()
    job_id = job.id

    monkeypatch.setattr(settings, "drain_timeout_s", 0.3)
    runtime = WorkerRuntime(
        session_factory=session_factory,
        concurrency=2,
        poll_interval_s=0.05,
        heartbeat_interval_s=0.1,
    )
    run_task = asyncio.create_task(runtime.run())

    # Wait until the worker has actually started running the job.
    async def _job_status() -> JobStatus:
        async with session_factory() as s:
            j = await s.get(Job, job_id)
            return j.status

    for _ in range(100):  # up to ~5s
        if await _job_status() == JobStatus.running:
            break
        await asyncio.sleep(0.05)
    assert await _job_status() == JobStatus.running

    runtime.request_stop()
    await asyncio.wait_for(run_task, timeout=10)

    # In-flight job was cancelled at drain and released back to queued.
    assert await _job_status() == JobStatus.queued

    async with session_factory() as s:
        worker = await s.scalar(select(Worker).order_by(Worker.id.desc()))
        assert worker.status == WorkerStatus.stopped
        orphan_running = await s.scalar(
            select(func.count())
            .select_from(JobExecution)
            .where(JobExecution.status == ExecutionStatus.running)
        )
        assert orphan_running == 0  # the in-flight execution was finalized
