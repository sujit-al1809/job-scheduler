"""Queue CRUD, config validation, retry policies, pause/resume, and stats."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

REGISTER = "/api/v1/auth/register"
PROJECTS = "/api/v1/projects"


async def _setup_project(client: AsyncClient, email: str) -> tuple[dict[str, str], int]:
    reg = await client.post(REGISTER, json={"email": email, "password": "supersecret"})
    token = reg.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    proj = await client.post(PROJECTS, json={"name": "proj"}, headers=h)
    return h, proj.json()["id"]


def _queues_url(pid: int) -> str:
    return f"{PROJECTS}/{pid}/queues"


async def test_create_queue_with_inline_retry_policy(client: AsyncClient) -> None:
    h, pid = await _setup_project(client, "q1@example.com")
    body = {
        "name": "emails",
        "priority": 5,
        "concurrency_limit": 3,
        "retry_policy": {
            "strategy": "exponential",
            "base_delay_s": 2,
            "max_attempts": 4,
        },
    }
    resp = await client.post(_queues_url(pid), json=body, headers=h)
    assert resp.status_code == 201, resp.text
    q = resp.json()
    assert q["name"] == "emails"
    assert q["priority"] == 5
    assert q["concurrency_limit"] == 3
    assert q["is_paused"] is False
    assert q["retry_policy_id"] is not None


async def test_concurrency_must_be_at_least_one(client: AsyncClient) -> None:
    h, pid = await _setup_project(client, "q2@example.com")
    resp = await client.post(
        _queues_url(pid),
        json={"name": "bad", "concurrency_limit": 0},
        headers=h,
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_invalid_retry_strategy_rejected(client: AsyncClient) -> None:
    h, pid = await _setup_project(client, "q3@example.com")
    resp = await client.post(
        _queues_url(pid),
        json={"name": "bad", "retry_policy": {"strategy": "quantum"}},
        headers=h,
    )
    assert resp.status_code == 422


async def test_retry_policy_id_and_inline_are_mutually_exclusive(
    client: AsyncClient,
) -> None:
    h, pid = await _setup_project(client, "q4@example.com")
    resp = await client.post(
        _queues_url(pid),
        json={
            "name": "amb",
            "retry_policy_id": 999,
            "retry_policy": {"strategy": "fixed"},
        },
        headers=h,
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "RETRY_POLICY_AMBIGUOUS"


async def test_duplicate_queue_name_conflicts(client: AsyncClient) -> None:
    h, pid = await _setup_project(client, "q5@example.com")
    await client.post(_queues_url(pid), json={"name": "dup"}, headers=h)
    second = await client.post(_queues_url(pid), json={"name": "dup"}, headers=h)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "QUEUE_NAME_TAKEN"


async def test_pause_and_resume_flips_flag(client: AsyncClient) -> None:
    h, pid = await _setup_project(client, "q6@example.com")
    created = await client.post(_queues_url(pid), json={"name": "work"}, headers=h)
    qid = created.json()["id"]

    paused = await client.post(f"{_queues_url(pid)}/{qid}/pause", headers=h)
    assert paused.status_code == 200
    assert paused.json()["is_paused"] is True

    resumed = await client.post(f"{_queues_url(pid)}/{qid}/resume", headers=h)
    assert resumed.status_code == 200
    assert resumed.json()["is_paused"] is False


async def test_stats_empty_queue(client: AsyncClient) -> None:
    h, pid = await _setup_project(client, "q7@example.com")
    created = await client.post(_queues_url(pid), json={"name": "s"}, headers=h)
    qid = created.json()["id"]

    stats = await client.get(f"{_queues_url(pid)}/{qid}/stats", headers=h)
    assert stats.status_code == 200
    body = stats.json()
    assert body["queue_id"] == qid
    assert body["total"] == 0
    assert body["by_status"]["queued"] == 0
    assert body["oldest_queued_age_s"] is None
    assert body["avg_duration_ms"] is None
    assert body["in_flight"] == 0


async def test_update_queue_config(client: AsyncClient) -> None:
    h, pid = await _setup_project(client, "q8@example.com")
    created = await client.post(_queues_url(pid), json={"name": "u"}, headers=h)
    qid = created.json()["id"]
    patched = await client.patch(
        f"{_queues_url(pid)}/{qid}",
        json={"priority": 9, "concurrency_limit": 7},
        headers=h,
    )
    assert patched.status_code == 200
    assert patched.json()["priority"] == 9
    assert patched.json()["concurrency_limit"] == 7


async def test_cross_org_queue_isolation(client: AsyncClient) -> None:
    h_a, pid_a = await _setup_project(client, "qa@example.com")
    created = await client.post(_queues_url(pid_a), json={"name": "priv"}, headers=h_a)
    qid = created.json()["id"]

    h_b, _ = await _setup_project(client, "qb@example.com")
    # Bob cannot reach Alice's project or its queue — both look like 404.
    assert (await client.get(_queues_url(pid_a), headers=h_b)).status_code == 404
    assert (
        await client.get(f"{_queues_url(pid_a)}/{qid}", headers=h_b)
    ).status_code == 404
