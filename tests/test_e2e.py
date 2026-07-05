"""The showcase suite: heavy concurrency + failure handling, end to end.

These are the tests that most directly demonstrate the reliability guarantees:
no duplicate execution under load, retries that respect the policy, and correct
handling of paused queues, delayed jobs, and parallel idempotent submits.
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
    RetryPolicy,
)
from app.models.enums import JobStatus, RetryStrategy
from app.schemas.job import JobCreate
from app.services import worker as worker_service
from app.services.job import create_job
from worker.claim import claim_jobs
from worker.executor import execute_job

pytestmark = pytest.mark.asyncio

UTC = dt.timezone.utc
_NON_TERMINAL = [
    JobStatus.queued,
    JobStatus.scheduled,
    JobStatus.claimed,
    JobStatus.running,
]


async def _seed_org_project_queue(
    session: AsyncSession, *, concurrency_limit: int = 1000, base_delay_s: float = 0.0
) -> tuple[int, int, int]:
    org = Organization(name="o")
    session.add(org)
    await session.flush()
    project = Project(org_id=org.id, name="p", api_key="k-" + str(org.id))
    session.add(project)
    await session.flush()
    # base_delay 0 so retries are immediately due — keeps the test fast.
    policy = RetryPolicy(
        project_id=project.id,
        strategy=RetryStrategy.fixed,
        base_delay_s=base_delay_s,
        max_delay_s=base_delay_s,
        max_attempts=3,
        jitter=False,
    )
    session.add(policy)
    await session.flush()
    queue = Queue(
        project_id=project.id,
        name="q",
        concurrency_limit=concurrency_limit,
        retry_policy_id=policy.id,
    )
    session.add(queue)
    await session.flush()
    await session.commit()
    return org.id, project.id, queue.id


async def _drain_with_workers(
    session_factory: async_sessionmaker[AsyncSession],
    worker_ids: list[int],
    *,
    batch_size: int = 25,
) -> None:
    """Run N worker loops until every job reaches a terminal state."""

    async def _worker(worker_id: int) -> None:
        while True:
            async with session_factory() as session:
                claimed = await claim_jobs(
                    session, worker_id, batch_size=batch_size
                )
                await session.commit()
            if claimed:
                for job_id in claimed:
                    await execute_job(session_factory, worker_id, job_id)
                continue
            # Nothing claimable right now — stop only if all jobs are terminal.
            async with session_factory() as session:
                remaining = await session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(Job.status.in_(_NON_TERMINAL))
                )
            if remaining == 0:
                break
            await asyncio.sleep(0.02)

    await asyncio.gather(*(_worker(wid) for wid in worker_ids))


async def test_showcase_500_jobs_3_workers(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    n_jobs = 500
    _, project_id, queue_id = await _seed_org_project_queue(db_session)

    now = dt.datetime.now(tz=UTC) - dt.timedelta(seconds=1)
    for i in range(n_jobs):
        # 10% random_fail (fail_rate 0.5) so retries + some dead-lettering are real.
        if i % 10 == 0:
            job_type, payload = "demo.random_fail", {"fail_rate": 0.5}
        else:
            job_type, payload = "demo.sleep", {"sleep_s": 0}
        db_session.add(
            Job(
                queue_id=queue_id,
                project_id=project_id,
                type=job_type,
                payload=payload,
                status=JobStatus.queued,
                run_at=now,
                max_attempts=3,
            )
        )
    await db_session.commit()

    worker_ids = []
    for i in range(3):
        w = await worker_service.register_worker(db_session, f"w{i}", concurrency=8)
        worker_ids.append(w.id)

    await _drain_with_workers(session_factory, worker_ids)

    # 1) Every job reached a terminal state (completed or dead) — none stuck.
    non_terminal = await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.status.in_(_NON_TERMINAL))
    )
    assert non_terminal == 0
    terminal = await db_session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.status.in_([JobStatus.completed, JobStatus.dead]))
    )
    assert terminal == n_jobs

    # 2) Zero duplicate execution: each job has exactly `attempts` executions, and
    #    the (job_id, attempt) pairs are globally unique (DB-enforced, re-checked).
    total_attempts = await db_session.scalar(select(func.sum(Job.attempts)))
    total_execs = await db_session.scalar(
        select(func.count()).select_from(JobExecution)
    )
    assert total_execs == total_attempts
    distinct_pairs = await db_session.scalar(
        select(func.count()).select_from(
            select(JobExecution.job_id, JobExecution.attempt)
            .distinct()
            .subquery()
        )
    )
    assert distinct_pairs == total_execs

    # 3) Retry counts respect the policy: dead jobs used exactly max_attempts;
    #    every job's attempts never exceed its max.
    dead_jobs = (
        await db_session.scalars(
            select(Job).where(Job.status == JobStatus.dead)
        )
    ).all()
    for job in dead_jobs:
        assert job.attempts == job.max_attempts == 3
    over = await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.attempts > Job.max_attempts)
    )
    assert over == 0


async def test_paused_queue_starvation(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, project_id, queue_id = await _seed_org_project_queue(db_session)
    # Pause the queue, then add jobs.
    queue = await db_session.get(Queue, queue_id)
    queue.is_paused = True
    now = dt.datetime.now(tz=UTC) - dt.timedelta(seconds=1)
    for _ in range(10):
        db_session.add(
            Job(
                queue_id=queue_id, project_id=project_id, type="demo.sleep",
                payload={"sleep_s": 0}, status=JobStatus.queued, run_at=now,
                max_attempts=3,
            )
        )
    await db_session.commit()
    [worker_id] = [
        (await worker_service.register_worker(db_session, "w", concurrency=4)).id
    ]

    async with session_factory() as s:
        claimed = await claim_jobs(s, worker_id, batch_size=25)
        await s.commit()
    assert claimed == []
    # All jobs remain queued (starved) while paused.
    queued = await db_session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.status == JobStatus.queued)
    )
    assert queued == 10


async def test_delayed_job_not_claimable_early(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, project_id, queue_id = await _seed_org_project_queue(db_session)
    future = dt.datetime.now(tz=UTC) + dt.timedelta(hours=1)
    job = Job(
        queue_id=queue_id, project_id=project_id, type="demo.sleep",
        payload={}, status=JobStatus.queued, run_at=future, max_attempts=3,
    )
    db_session.add(job)
    await db_session.commit()
    [worker_id] = [
        (await worker_service.register_worker(db_session, "w", concurrency=4)).id
    ]

    async with session_factory() as s:
        claimed = await claim_jobs(s, worker_id, batch_size=25)
        await s.commit()
    assert claimed == []  # run_at is in the future


async def test_idempotency_under_parallel_submits(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id, _, queue_id = await _seed_org_project_queue(db_session)

    async def submit() -> tuple[int, bool]:
        async with session_factory() as session:
            job, created = await create_job(
                session,
                org_id,
                queue_id,
                JobCreate(type="demo.sleep", idempotency_key="same-key"),
            )
            await session.commit()
            return job.id, created

    results = await asyncio.gather(*(submit() for _ in range(10)))

    # All submissions resolve to the same job; exactly one row exists for the key.
    distinct_ids = {jid for jid, _ in results}
    assert len(distinct_ids) == 1
    rows = await db_session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.idempotency_key == "same-key")
    )
    assert rows == 1
