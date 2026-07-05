"""Retry backoff math (unit) + exhaustion → DLQ + DLQ retry round-trip."""
from __future__ import annotations

import datetime as dt
import random

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import DeadLetterJob, Job, JobExecution, Organization, Project, Queue
from app.models.enums import JobStatus, RetryStrategy
from app.services import worker as worker_service
from app.services.retry import compute_delay
from worker.claim import claim_jobs
from worker.executor import execute_job

# No module-level asyncio mark: this file mixes pure (sync) backoff-math tests with
# async DB tests. asyncio_mode=auto marks the async ones automatically.

UTC = dt.timezone.utc
REGISTER = "/api/v1/auth/register"
PROJECTS = "/api/v1/projects"


# --------------------------------------------------------------------------- #
# backoff math (pure)
# --------------------------------------------------------------------------- #
def test_backoff_math_table() -> None:
    P = dict(base_delay_s=5.0, max_delay_s=1000.0, jitter=False)

    # fixed: always base
    assert compute_delay(RetryStrategy.fixed, 1, **P) == 5.0
    assert compute_delay(RetryStrategy.fixed, 4, **P) == 5.0

    # linear: base * attempt
    assert compute_delay(RetryStrategy.linear, 1, **P) == 5.0
    assert compute_delay(RetryStrategy.linear, 2, **P) == 10.0
    assert compute_delay(RetryStrategy.linear, 3, **P) == 15.0

    # exponential: base * 2^(attempt-1)
    assert compute_delay(RetryStrategy.exponential, 1, **P) == 5.0
    assert compute_delay(RetryStrategy.exponential, 2, **P) == 10.0
    assert compute_delay(RetryStrategy.exponential, 3, **P) == 20.0
    assert compute_delay(RetryStrategy.exponential, 4, **P) == 40.0


def test_backoff_respects_max_delay_cap() -> None:
    delay = compute_delay(
        RetryStrategy.exponential,
        5,  # 5 * 2^4 = 80
        base_delay_s=5.0,
        max_delay_s=12.0,
        jitter=False,
    )
    assert delay == 12.0


def test_backoff_jitter_stays_in_band() -> None:
    rng = random.Random(42)
    for _ in range(50):
        delay = compute_delay(
            RetryStrategy.fixed,
            1,
            base_delay_s=10.0,
            max_delay_s=1000.0,
            jitter=True,
            rng=rng,
        )
        assert 8.0 <= delay <= 12.0  # 10 * uniform(0.8, 1.2)


# --------------------------------------------------------------------------- #
# exhaustion → DLQ
# --------------------------------------------------------------------------- #
async def _seed_always_fail(session: AsyncSession, max_attempts: int) -> tuple[int, int]:
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
        type="demo.always_fail",
        payload={"message": "nope"},
        status=JobStatus.queued,
        run_at=dt.datetime.now(tz=UTC) - dt.timedelta(seconds=1),
        max_attempts=max_attempts,
    )
    session.add(job)
    await session.commit()
    return project.id, job.id


async def test_exhaustion_lands_in_dlq_with_all_executions(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    max_attempts = 3
    _, job_id = await _seed_always_fail(db_session, max_attempts)
    worker = await worker_service.register_worker(db_session, "w", concurrency=1)

    # Drive attempts: each fail reschedules to run_at≈now (backoff), so we make it
    # immediately claimable again by resetting run_at into the past between attempts.
    for _ in range(max_attempts):
        async with session_factory() as s:
            claimed = await claim_jobs(s, worker.id, batch_size=10)
            await s.commit()
        assert claimed == [job_id]
        await execute_job(session_factory, worker.id, job_id)
        # Pull the next retry's run_at back so it's due now.
        job = await db_session.get(Job, job_id)
        await db_session.refresh(job)
        if job.status == JobStatus.queued:
            job.run_at = dt.datetime.now(tz=UTC) - dt.timedelta(seconds=1)
            await db_session.commit()

    job = await db_session.get(Job, job_id)
    await db_session.refresh(job)
    assert job.status == JobStatus.dead
    assert job.attempts == max_attempts

    exec_count = await db_session.scalar(
        select(func.count()).select_from(JobExecution).where(JobExecution.job_id == job_id)
    )
    assert exec_count == max_attempts

    dlq = await db_session.scalar(
        select(DeadLetterJob).where(DeadLetterJob.job_id == job_id)
    )
    assert dlq is not None
    assert dlq.attempts == max_attempts
    assert dlq.final_error == "nope"
    assert dlq.payload == {"message": "nope"}


async def test_retry_reschedules_before_exhaustion(
    db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, job_id = await _seed_always_fail(db_session, max_attempts=3)
    worker = await worker_service.register_worker(db_session, "w", concurrency=1)

    async with session_factory() as s:
        claimed = await claim_jobs(s, worker.id, batch_size=10)
        await s.commit()
    await execute_job(session_factory, worker.id, job_id)

    job = await db_session.get(Job, job_id)
    await db_session.refresh(job)
    # First of three attempts failed → back to queued with a future run_at.
    assert job.status == JobStatus.queued
    assert job.attempts == 1
    assert job.run_at > dt.datetime.now(tz=UTC)


# --------------------------------------------------------------------------- #
# DLQ API round-trip
# --------------------------------------------------------------------------- #
async def test_dlq_list_retry_and_delete(
    client, db_session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # Register through the API so the DLQ is visible to that org.
    reg = await client.post(
        REGISTER, json={"email": "dlq@example.com", "password": "supersecret"}
    )
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    proj = await client.post(PROJECTS, json={"name": "p"}, headers=h)
    pid = proj.json()["id"]
    q = await client.post(f"{PROJECTS}/{pid}/queues", json={"name": "q"}, headers=h)
    qid = q.json()["id"]
    created = await client.post(
        f"/api/v1/queues/{qid}/jobs",
        json={"type": "demo.always_fail", "max_attempts": 1, "payload": {"message": "x"}},
        headers=h,
    )
    job_id = created.json()["id"]

    # One attempt, exhausted immediately (max_attempts=1) → DLQ.
    worker = await worker_service.register_worker(db_session, "w", concurrency=1)
    async with session_factory() as s:
        await claim_jobs(s, worker.id, batch_size=10)
        await s.commit()
    await execute_job(session_factory, worker.id, job_id)

    listed = await client.get(f"{PROJECTS}/{pid}/dlq", headers=h)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    dlq_id = listed.json()["items"][0]["id"]

    # Retry re-enqueues fresh (attempts reset, status queued) and clears the DLQ.
    retried = await client.post(f"/api/v1/dlq/{dlq_id}/retry", headers=h)
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"
    assert retried.json()["attempts"] == 0
    assert (await client.get(f"{PROJECTS}/{pid}/dlq", headers=h)).json()["total"] == 0

    # Cause another DLQ entry and delete it.
    await execute_job(session_factory, worker.id, job_id)  # no-op (queued, not claimed)
    async with session_factory() as s:
        await claim_jobs(s, worker.id, batch_size=10)
        await s.commit()
    await execute_job(session_factory, worker.id, job_id)
    listed2 = await client.get(f"{PROJECTS}/{pid}/dlq", headers=h)
    dlq_id2 = listed2.json()["items"][0]["id"]
    deleted = await client.delete(f"/api/v1/dlq/{dlq_id2}", headers=h)
    assert deleted.status_code == 204
    assert (await client.get(f"{PROJECTS}/{pid}/dlq", headers=h)).json()["total"] == 0
