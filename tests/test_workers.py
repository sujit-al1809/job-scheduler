"""Worker registration, heartbeat recording, and the read API."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import WorkerStatus
from app.services import worker as worker_service

pytestmark = pytest.mark.asyncio

REGISTER = "/api/v1/auth/register"


async def _auth(client: AsyncClient, email: str) -> dict[str, str]:
    reg = await client.post(REGISTER, json={"email": email, "password": "supersecret"})
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


async def test_register_and_heartbeat(db_session: AsyncSession) -> None:
    worker = await worker_service.register_worker(db_session, "w1", concurrency=4)
    assert worker.id is not None
    assert worker.status == WorkerStatus.online
    first_hb = worker.last_heartbeat_at

    await worker_service.record_heartbeat(db_session, worker.id, in_flight=2)
    await db_session.refresh(worker)
    assert worker.last_heartbeat_at >= first_hb

    hbs, total = await worker_service.list_heartbeats(
        db_session, worker.id, limit=10, offset=0
    )
    assert total == 1
    assert hbs[0].in_flight == 2


async def test_status_transition_to_stopped(db_session: AsyncSession) -> None:
    worker = await worker_service.register_worker(db_session, "w2", concurrency=1)
    await worker_service.set_worker_status(
        db_session, worker.id, WorkerStatus.stopped, stopped=True
    )
    await db_session.refresh(worker)
    assert worker.status == WorkerStatus.stopped
    assert worker.stopped_at is not None


async def test_workers_api_lists_and_fetches(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    worker = await worker_service.register_worker(db_session, "api-w", concurrency=8)
    await worker_service.record_heartbeat(db_session, worker.id, in_flight=0)

    h = await _auth(client, "wapi@example.com")

    listed = await client.get("/api/v1/workers", headers=h)
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["name"] == "api-w"

    one = await client.get(f"/api/v1/workers/{worker.id}", headers=h)
    assert one.status_code == 200
    assert one.json()["concurrency"] == 8

    hbs = await client.get(f"/api/v1/workers/{worker.id}/heartbeats", headers=h)
    assert hbs.status_code == 200
    assert hbs.json()["total"] == 1


async def test_workers_api_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/workers")).status_code == 401
