"""Scheduler: cron math, promotion, one-job-per-tick concurrency, batch atomicity."""
from __future__ import annotations

import asyncio
import datetime as dt

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Job, ScheduledJob
from app.models.enums import JobStatus
from app.services.scheduler_engine import (
    materialize_due_cron_jobs,
    next_cron_time,
    promote_due_scheduled_jobs,
)

pytestmark = pytest.mark.asyncio

UTC = dt.timezone.utc
REGISTER = "/api/v1/auth/register"
PROJECTS = "/api/v1/projects"


async def _setup_queue(client: AsyncClient, email: str) -> tuple[dict[str, str], int]:
    reg = await client.post(REGISTER, json={"email": email, "password": "supersecret"})
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    proj = await client.post(PROJECTS, json={"name": "p"}, headers=h)
    pid = proj.json()["id"]
    q = await client.post(f"{PROJECTS}/{pid}/queues", json={"name": "q"}, headers=h)
    return h, q.json()["id"]


# --------------------------------------------------------------------------- #
# cron math (pure unit)
# --------------------------------------------------------------------------- #
async def test_cron_advance_math() -> None:
    base = dt.datetime(2026, 1, 1, 12, 0, 30, tzinfo=UTC)
    assert next_cron_time("* * * * *", base) == dt.datetime(
        2026, 1, 1, 12, 1, 0, tzinfo=UTC
    )
    assert next_cron_time("0 * * * *", base) == dt.datetime(
        2026, 1, 1, 13, 0, 0, tzinfo=UTC
    )
    assert next_cron_time("0 0 * * *", base) == dt.datetime(
        2026, 1, 2, 0, 0, 0, tzinfo=UTC
    )


# --------------------------------------------------------------------------- #
# promotion
# --------------------------------------------------------------------------- #
async def test_promote_due_scheduled_job(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    h, qid = await _setup_queue(client, "sched1@example.com")
    created = await client.post(
        f"/api/v1/queues/{qid}/jobs", json={"type": "t", "delay_s": 3600}, headers=h
    )
    jid = created.json()["id"]
    assert created.json()["status"] == "scheduled"

    # Make it due, then promote.
    job = await db_session.get(Job, jid)
    job.run_at = dt.datetime.now(tz=UTC) - dt.timedelta(seconds=1)
    await db_session.commit()

    promoted = await promote_due_scheduled_jobs(db_session)
    assert promoted == 1

    refreshed = await client.get(f"/api/v1/jobs/{jid}", headers=h)
    assert refreshed.json()["status"] == "queued"


# --------------------------------------------------------------------------- #
# one job per tick, even with two schedulers racing
# --------------------------------------------------------------------------- #
async def test_one_job_per_tick_under_two_concurrent_schedulers(
    client: AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    h, qid = await _setup_queue(client, "sched2@example.com")
    resp = await client.post(
        f"/api/v1/queues/{qid}/schedules",
        json={"type": "cron.job", "cron_expr": "* * * * *"},
        headers=h,
    )
    sid = resp.json()["id"]

    # Force the template due now.
    schedule = await db_session.get(ScheduledJob, sid)
    schedule.next_run_at = dt.datetime.now(tz=UTC) - dt.timedelta(seconds=1)
    await db_session.commit()

    async def _run() -> list[int]:
        async with session_factory() as session:
            return await materialize_due_cron_jobs(session)

    # Two schedulers materialize concurrently; SKIP LOCKED must yield exactly one.
    res_a, res_b = await asyncio.gather(_run(), _run())
    assert len(res_a) + len(res_b) == 1

    total_jobs = await db_session.scalar(
        select(func.count()).select_from(Job).where(Job.queue_id == qid)
    )
    assert total_jobs == 1

    # next_run_at advanced into the future, so a follow-up tick creates nothing.
    async with session_factory() as session:
        again = await materialize_due_cron_jobs(session)
    assert again == []


async def test_materialized_job_is_queued(
    client: AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    h, qid = await _setup_queue(client, "sched3@example.com")
    resp = await client.post(
        f"/api/v1/queues/{qid}/schedules",
        json={"type": "cron.job", "cron_expr": "* * * * *", "payload": {"k": "v"}},
        headers=h,
    )
    sid = resp.json()["id"]
    schedule = await db_session.get(ScheduledJob, sid)
    schedule.next_run_at = dt.datetime.now(tz=UTC) - dt.timedelta(seconds=1)
    await db_session.commit()

    async with session_factory() as session:
        [job_id] = await materialize_due_cron_jobs(session)

    job = await db_session.get(Job, job_id)
    assert job.status == JobStatus.queued
    assert job.type == "cron.job"
    assert job.payload == {"k": "v"}


# --------------------------------------------------------------------------- #
# schedule CRUD
# --------------------------------------------------------------------------- #
async def test_create_schedule_validates_cron(client: AsyncClient) -> None:
    h, qid = await _setup_queue(client, "sched4@example.com")
    bad = await client.post(
        f"/api/v1/queues/{qid}/schedules",
        json={"type": "t", "cron_expr": "not a cron"},
        headers=h,
    )
    assert bad.status_code == 422


async def test_schedule_pause_and_activate(client: AsyncClient) -> None:
    h, qid = await _setup_queue(client, "sched5@example.com")
    created = await client.post(
        f"/api/v1/queues/{qid}/schedules",
        json={"type": "t", "cron_expr": "*/5 * * * *"},
        headers=h,
    )
    sid = created.json()["id"]
    assert created.json()["is_active"] is True

    paused = await client.post(
        f"/api/v1/queues/{qid}/schedules/{sid}/pause", headers=h
    )
    assert paused.json()["is_active"] is False
    activated = await client.post(
        f"/api/v1/queues/{qid}/schedules/{sid}/activate", headers=h
    )
    assert activated.json()["is_active"] is True


# --------------------------------------------------------------------------- #
# batch submit
# --------------------------------------------------------------------------- #
async def test_batch_submit_creates_all(client: AsyncClient) -> None:
    h, qid = await _setup_queue(client, "batch1@example.com")
    body = {"jobs": [{"type": "a"}, {"type": "b"}, {"type": "c"}]}
    resp = await client.post(f"/api/v1/queues/{qid}/jobs/batch", json=body, headers=h)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["total"] == 3 and data["created"] == 3 and data["replayed"] == 0
    assert (await client.get("/api/v1/jobs", headers=h)).json()["total"] == 3


async def test_batch_is_atomic_on_bad_item(client: AsyncClient) -> None:
    h, qid = await _setup_queue(client, "batch2@example.com")
    body = {
        "jobs": [
            {"type": "a"},
            {"type": "b", "idempotency_key": "dup"},
            {"type": "c", "idempotency_key": "dup"},  # duplicate within batch
        ]
    }
    resp = await client.post(f"/api/v1/queues/{qid}/jobs/batch", json=body, headers=h)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "DUPLICATE_IN_BATCH"
    # Nothing persisted — the whole batch rolled back.
    assert (await client.get("/api/v1/jobs", headers=h)).json()["total"] == 0
