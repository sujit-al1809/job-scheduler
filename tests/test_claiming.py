"""The most important tests in the project: atomic claiming under concurrency.

Invariant: N workers claiming one queue of M jobs execute each job exactly once —
no duplicates, none lost.
"""
from __future__ import annotations

import asyncio
import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    Job,
    JobExecution,
    Organization,
    Project,
    Queue,
    Worker,
)
from app.models.enums import ExecutionStatus, JobStatus
from app.services import worker as worker_service
from worker.claim import claim_jobs
from worker.executor import execute_job

pytestmark = pytest.mark.asyncio

UTC = dt.timezone.utc


async def _seed_queue(
    session: AsyncSession,
    *,
    n_jobs: int,
    concurrency_limit: int = 10_000,
    is_paused: bool = False,
    priorities: list[int] | None = None,
) -> tuple[int, int]:
    """Create org/project/queue and n queued jobs. Returns (project_id, queue_id)."""
    org = Organization(name="o")
    session.add(org)
    await session.flush()
    project = Project(org_id=org.id, name="p", api_key="k-" + str(org.id))
    session.add(project)
    await session.flush()
    queue = Queue(
        project_id=project.id,
        name="q",
        concurrency_limit=concurrency_limit,
        is_paused=is_paused,
    )
    session.add(queue)
    await session.flush()

    now = dt.datetime.now(tz=UTC) - dt.timedelta(seconds=1)
    for i in range(n_jobs):
        session.add(
            Job(
                queue_id=queue.id,
                project_id=project.id,
                type="t",
                status=JobStatus.queued,
                priority=priorities[i] if priorities else 0,
                run_at=now,
                max_attempts=5,
            )
        )
    await session.commit()
    return project.id, queue.id


async def _register_workers(session: AsyncSession, n: int) -> list[int]:
    ids = []
    for i in range(n):
        w = await worker_service.register_worker(session, f"w{i}", concurrency=8)
        ids.append(w.id)
    return ids


# --------------------------------------------------------------------------- #
# THE critical test
# --------------------------------------------------------------------------- #
async def test_no_duplicate_execution_under_concurrency(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    n_jobs = 200
    n_workers = 4
    _, queue_id = await _seed_queue(db_session, n_jobs=n_jobs)
    worker_ids = await _register_workers(db_session, n_workers)

    async def drain(worker_id: int) -> None:
        while True:
            async with session_factory() as session:
                claimed = await claim_jobs(session, worker_id, batch_size=10)
                await session.commit()
            if not claimed:
                break
            for job_id in claimed:
                await execute_job(session_factory, worker_id, job_id)

    await asyncio.gather(*(drain(wid) for wid in worker_ids))

    # Exactly n_jobs executions, one per distinct job, all completed.
    total_exec = await db_session.scalar(
        select(func.count()).select_from(JobExecution)
    )
    distinct_jobs = await db_session.scalar(
        select(func.count(func.distinct(JobExecution.job_id)))
    )
    assert total_exec == n_jobs
    assert distinct_jobs == n_jobs  # zero duplicates

    all_completed_exec = await db_session.scalar(
        select(func.count())
        .select_from(JobExecution)
        .where(JobExecution.status == ExecutionStatus.completed)
    )
    assert all_completed_exec == n_jobs

    remaining = await db_session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.queue_id == queue_id, Job.status != JobStatus.completed)
    )
    assert remaining == 0


async def test_paused_queue_never_claims(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_queue(db_session, n_jobs=5, is_paused=True)
    [worker_id] = await _register_workers(db_session, 1)
    async with session_factory() as session:
        claimed = await claim_jobs(session, worker_id, batch_size=10)
        await session.commit()
    assert claimed == []


async def test_priority_ordering(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Three jobs with priorities 1, 5, 9 — higher priority claimed first.
    await _seed_queue(db_session, n_jobs=3, priorities=[1, 9, 5])
    [worker_id] = await _register_workers(db_session, 1)

    order: list[int] = []
    for _ in range(3):
        async with session_factory() as session:
            claimed = await claim_jobs(session, worker_id, batch_size=1)
            await session.commit()
            if not claimed:
                break
            job = await session.get(Job, claimed[0])
            order.append(job.priority)
        # Complete it so the queue's concurrency slot frees for the next claim.
        await execute_job(session_factory, worker_id, claimed[0])
    assert order == [9, 5, 1]


async def test_claim_respects_project_filter(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id, _ = await _seed_queue(db_session, n_jobs=3)
    [worker_id] = await _register_workers(db_session, 1)

    # Matching project id claims; a different id claims nothing.
    async with session_factory() as session:
        none = await claim_jobs(
            session, worker_id, batch_size=10, project_ids=[project_id + 999]
        )
        await session.commit()
    assert none == []

    async with session_factory() as session:
        some = await claim_jobs(
            session, worker_id, batch_size=10, project_ids=[project_id]
        )
        await session.commit()
    assert len(some) == 3
