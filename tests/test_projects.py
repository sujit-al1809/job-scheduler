"""Project CRUD and cross-org isolation."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

REGISTER = "/api/v1/auth/register"
PROJECTS = "/api/v1/projects"


async def _register(client: AsyncClient, email: str) -> str:
    resp = await client.post(REGISTER, json={"email": email, "password": "supersecret"})
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_project_crud_happy_path(client: AsyncClient) -> None:
    token = await _register(client, "owner@example.com")
    h = _auth(token)

    # create
    created = await client.post(PROJECTS, json={"name": "billing"}, headers=h)
    assert created.status_code == 201, created.text
    project = created.json()
    pid = project["id"]
    assert project["name"] == "billing"
    assert project["api_key"]

    # get
    got = await client.get(f"{PROJECTS}/{pid}", headers=h)
    assert got.status_code == 200
    assert got.json()["id"] == pid

    # list (envelope shape)
    listed = await client.get(PROJECTS, headers=h)
    assert listed.status_code == 200
    page = listed.json()
    assert page["total"] == 1
    assert page["limit"] == 50 and page["offset"] == 0
    assert len(page["items"]) == 1

    # patch
    patched = await client.patch(
        f"{PROJECTS}/{pid}", json={"name": "payments"}, headers=h
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "payments"

    # delete
    deleted = await client.delete(f"{PROJECTS}/{pid}", headers=h)
    assert deleted.status_code == 204
    gone = await client.get(f"{PROJECTS}/{pid}", headers=h)
    assert gone.status_code == 404
    assert gone.json()["error"]["code"] == "PROJECT_NOT_FOUND"


async def test_duplicate_name_conflicts(client: AsyncClient) -> None:
    h = _auth(await _register(client, "dupe@example.com"))
    first = await client.post(PROJECTS, json={"name": "same"}, headers=h)
    assert first.status_code == 201
    second = await client.post(PROJECTS, json={"name": "same"}, headers=h)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "PROJECT_NAME_TAKEN"


async def test_cross_org_isolation_returns_404(client: AsyncClient) -> None:
    # Alice creates a project.
    alice = _auth(await _register(client, "alice@example.com"))
    created = await client.post(PROJECTS, json={"name": "secret"}, headers=alice)
    pid = created.json()["id"]

    # Bob (different org) cannot see, patch, or delete it — all look like 404.
    bob = _auth(await _register(client, "bob@example.com"))
    assert (await client.get(f"{PROJECTS}/{pid}", headers=bob)).status_code == 404
    assert (
        await client.patch(f"{PROJECTS}/{pid}", json={"name": "x"}, headers=bob)
    ).status_code == 404
    assert (await client.delete(f"{PROJECTS}/{pid}", headers=bob)).status_code == 404

    # Bob's own list is empty; Alice's still has her project.
    bob_list = await client.get(PROJECTS, headers=bob)
    assert bob_list.json()["total"] == 0
    alice_list = await client.get(PROJECTS, headers=alice)
    assert alice_list.json()["total"] == 1


async def test_requires_auth(client: AsyncClient) -> None:
    assert (await client.get(PROJECTS)).status_code == 401
    assert (await client.post(PROJECTS, json={"name": "x"})).status_code == 401
