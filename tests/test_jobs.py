"""Job submission (immediate/delayed/idempotent), listing/filters, detail, cancel."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

REGISTER = "/api/v1/auth/register"
PROJECTS = "/api/v1/projects"


async def _setup_queue(client: AsyncClient, email: str) -> tuple[dict[str, str], int]:
    reg = await client.post(REGISTER, json={"email": email, "password": "supersecret"})
    h = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    proj = await client.post(PROJECTS, json={"name": "p"}, headers=h)
    pid = proj.json()["id"]
    q = await client.post(
        f"{PROJECTS}/{pid}/queues", json={"name": "q", "priority": 3}, headers=h
    )
    return h, q.json()["id"]


def _jobs_url(qid: int) -> str:
    return f"/api/v1/queues/{qid}/jobs"


async def test_immediate_job_is_queued(client: AsyncClient) -> None:
    h, qid = await _setup_queue(client, "j1@example.com")
    resp = await client.post(
        _jobs_url(qid), json={"type": "email.send", "payload": {"to": "x"}}, headers=h
    )
    assert resp.status_code == 201, resp.text
    job = resp.json()
    assert job["status"] == "queued"
    assert job["priority"] == 3  # inherited from queue
    assert job["payload"] == {"to": "x"}


async def test_priority_override(client: AsyncClient) -> None:
    h, qid = await _setup_queue(client, "j1b@example.com")
    resp = await client.post(
        _jobs_url(qid), json={"type": "t", "priority": 99}, headers=h
    )
    assert resp.json()["priority"] == 99


async def test_delayed_job_is_scheduled(client: AsyncClient) -> None:
    h, qid = await _setup_queue(client, "j2@example.com")
    resp = await client.post(
        _jobs_url(qid), json={"type": "report", "delay_s": 3600}, headers=h
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "scheduled"


async def test_idempotent_replay_returns_200_and_same_job(client: AsyncClient) -> None:
    h, qid = await _setup_queue(client, "j3@example.com")
    payload = {"type": "charge", "idempotency_key": "abc-123"}
    first = await client.post(_jobs_url(qid), json=payload, headers=h)
    assert first.status_code == 201
    second = await client.post(_jobs_url(qid), json=payload, headers=h)
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


async def test_cancel_queued_job_ok(client: AsyncClient) -> None:
    h, qid = await _setup_queue(client, "j4@example.com")
    created = await client.post(_jobs_url(qid), json={"type": "t"}, headers=h)
    jid = created.json()["id"]
    cancelled = await client.post(f"/api/v1/jobs/{jid}/cancel", headers=h)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


async def test_cancel_already_cancelled_is_409(client: AsyncClient) -> None:
    h, qid = await _setup_queue(client, "j5@example.com")
    created = await client.post(_jobs_url(qid), json={"type": "t"}, headers=h)
    jid = created.json()["id"]
    await client.post(f"/api/v1/jobs/{jid}/cancel", headers=h)
    again = await client.post(f"/api/v1/jobs/{jid}/cancel", headers=h)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "INVALID_TRANSITION"


async def test_detail_embeds_executions_and_logs(client: AsyncClient) -> None:
    h, qid = await _setup_queue(client, "j6@example.com")
    created = await client.post(_jobs_url(qid), json={"type": "t"}, headers=h)
    jid = created.json()["id"]
    detail = await client.get(f"/api/v1/jobs/{jid}", headers=h)
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == jid
    assert body["executions"] == []
    # The creation log line is present.
    assert any("job_created" in log["message"] for log in body["logs"])


async def test_list_filters_by_status_and_type(client: AsyncClient) -> None:
    h, qid = await _setup_queue(client, "j7@example.com")
    await client.post(_jobs_url(qid), json={"type": "alpha"}, headers=h)
    await client.post(_jobs_url(qid), json={"type": "beta", "delay_s": 3600}, headers=h)

    all_jobs = await client.get("/api/v1/jobs", headers=h)
    assert all_jobs.json()["total"] == 2

    queued = await client.get("/api/v1/jobs?status=queued", headers=h)
    assert queued.json()["total"] == 1
    assert queued.json()["items"][0]["type"] == "alpha"

    beta = await client.get("/api/v1/jobs?type=beta", headers=h)
    assert beta.json()["total"] == 1
    assert beta.json()["items"][0]["status"] == "scheduled"

    by_queue = await client.get(f"/api/v1/jobs?queue_id={qid}", headers=h)
    assert by_queue.json()["total"] == 2


async def test_jobs_are_org_scoped(client: AsyncClient) -> None:
    h_a, qid_a = await _setup_queue(client, "ja@example.com")
    created = await client.post(_jobs_url(qid_a), json={"type": "t"}, headers=h_a)
    jid = created.json()["id"]

    h_b, _ = await _setup_queue(client, "jb@example.com")
    assert (await client.get(f"/api/v1/jobs/{jid}", headers=h_b)).status_code == 404
    assert (
        await client.post(f"/api/v1/jobs/{jid}/cancel", headers=h_b)
    ).status_code == 404
    assert (await client.get("/api/v1/jobs", headers=h_b)).json()["total"] == 0
    # Bob can't submit to Alice's queue either.
    assert (
        await client.post(_jobs_url(qid_a), json={"type": "t"}, headers=h_b)
    ).status_code == 404
