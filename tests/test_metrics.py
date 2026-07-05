"""Metrics math on seeded executions + bulk retry-failed."""
from __future__ import annotations

import datetime as dt

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Job, JobExecution, Organization, Project, Queue
from app.models.enums import ExecutionStatus, JobStatus
from app.services import worker as worker_service
from worker.claim import claim_jobs
from worker.executor import execute_job

pytestmark = pytest.mark.asyncio

UTC = dt.timezone.utc
REGISTER = "/api/v1/auth/register"
PROJECTS = "/api/v1/projects"


async def _register(client: AsyncClient, email: str) -> dict[str, str]:
    reg = await client.post(REGISTER, json={"email": email, "password": "supersecret"})
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


async def test_metrics_math_on_seeded_executions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h = await _register(client, "metrics@example.com")
    proj = await client.post(PROJECTS, json={"name": "p"}, headers=h)
    pid = proj.json()["id"]
    q = await client.post(f"{PROJECTS}/{pid}/queues", json={"name": "q"}, headers=h)
    qid = q.json()["id"]

    now = dt.datetime.now(tz=UTC)
    # Seed 4 executions directly: 3 completed (durations 100, 200, 300 ms) + 1 failed.
    durations = [100, 200, 300]
    for i, d in enumerate(durations):
        job = Job(
            queue_id=qid, project_id=pid, type="t", status=JobStatus.completed,
            run_at=now, max_attempts=5,
        )
        db_session.add(job)
        await db_session.flush()
        db_session.add(
            JobExecution(
                job_id=job.id, attempt=1, status=ExecutionStatus.completed,
                started_at=now, finished_at=now, duration_ms=d,
            )
        )
    fail_job = Job(
        queue_id=qid, project_id=pid, type="t", status=JobStatus.dead,
        run_at=now, max_attempts=1,
    )
    db_session.add(fail_job)
    await db_session.flush()
    db_session.add(
        JobExecution(
            job_id=fail_job.id, attempt=1, status=ExecutionStatus.failed,
            started_at=now, finished_at=now, duration_ms=50, error="x",
        )
    )
    await db_session.commit()

    resp = await client.get(f"{PROJECTS}/{pid}/metrics", headers=h)
    assert resp.status_code == 200, resp.text
    m = resp.json()
    assert m["total_completed"] == 3
    assert m["total_failed"] == 1
    assert m["success_rate"] == pytest.approx(3 / 4)
    # p50 of {100,200,300} = 200; p95 ~ close to 300.
    assert m["p50_duration_ms"] == pytest.approx(200.0)
    assert 280 <= m["p95_duration_ms"] <= 300
    # Throughput buckets sum to the resolved executions.
    total_bucketed = sum(b["completed"] + b["failed"] for b in m["throughput_per_minute"])
    assert total_bucketed == 4
    # Queue depth snapshot present for the queue.
    depth = next(d for d in m["queue_depths"] if d["queue_id"] == qid)
    assert depth["depth"] == 0  # no queued jobs


async def test_metrics_empty_project(client: AsyncClient) -> None:
    h = await _register(client, "empty@example.com")
    proj = await client.post(PROJECTS, json={"name": "p"}, headers=h)
    pid = proj.json()["id"]
    resp = await client.get(f"{PROJECTS}/{pid}/metrics", headers=h)
    assert resp.status_code == 200
    m = resp.json()
    assert m["total_completed"] == 0
    assert m["success_rate"] is None
    assert m["p50_duration_ms"] is None
    assert m["throughput_per_minute"] == []


async def test_metrics_are_org_scoped(client: AsyncClient) -> None:
    h_a = await _register(client, "ma@example.com")
    proj = await client.post(PROJECTS, json={"name": "p"}, headers=h_a)
    pid = proj.json()["id"]
    h_b = await _register(client, "mb@example.com")
    assert (await client.get(f"{PROJECTS}/{pid}/metrics", headers=h_b)).status_code == 404


async def test_bulk_retry_failed(
    client: AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    h = await _register(client, "bulk@example.com")
    proj = await client.post(PROJECTS, json={"name": "p"}, headers=h)
    pid = proj.json()["id"]
    q = await client.post(f"{PROJECTS}/{pid}/queues", json={"name": "q"}, headers=h)
    qid = q.json()["id"]

    # Two always-fail jobs, max_attempts=1 -> they go dead.
    for _ in range(2):
        await client.post(
            f"/api/v1/queues/{qid}/jobs",
            json={"type": "demo.always_fail", "max_attempts": 1},
            headers=h,
        )
    worker = await worker_service.register_worker(db_session, "w", concurrency=2)
    async with session_factory() as s:
        claimed = await claim_jobs(s, worker.id, batch_size=10)
        await s.commit()
    for jid in claimed:
        await execute_job(session_factory, worker.id, jid)

    # Both are dead and in the DLQ.
    assert (await client.get(f"{PROJECTS}/{pid}/dlq", headers=h)).json()["total"] == 2

    retried = await client.post(f"/api/v1/queues/{qid}/jobs/retry-failed", headers=h)
    assert retried.status_code == 200
    assert retried.json()["requeued"] == 2

    # Back to queued, DLQ cleared.
    queued = await client.get(f"/api/v1/jobs?status=queued&queue_id={qid}", headers=h)
    assert queued.json()["total"] == 2
    assert (await client.get(f"{PROJECTS}/{pid}/dlq", headers=h)).json()["total"] == 0
