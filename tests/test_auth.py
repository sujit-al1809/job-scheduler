"""Auth flow: registration, login, and protected-route enforcement."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OrgMember, Organization, User

pytestmark = pytest.mark.asyncio

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


async def test_register_creates_user_org_and_membership(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await client.post(
        REGISTER, json={"email": "Alice@Example.com", "password": "supersecret"}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["email"] == "alice@example.com"  # normalized
    assert body["access_token"]
    assert body["token_type"] == "bearer"

    # One user, one org, one owner membership were bootstrapped.
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
    assert (
        await db_session.scalar(select(func.count()).select_from(Organization)) == 1
    )
    membership = await db_session.scalar(select(OrgMember))
    assert membership is not None
    assert membership.role.value == "owner"


async def test_register_duplicate_email_conflicts(client: AsyncClient) -> None:
    payload = {"email": "dupe@example.com", "password": "supersecret"}
    first = await client.post(REGISTER, json=payload)
    assert first.status_code == 201
    second = await client.post(REGISTER, json=payload)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "EMAIL_TAKEN"


async def test_login_returns_jwt(client: AsyncClient) -> None:
    await client.post(
        REGISTER, json={"email": "bob@example.com", "password": "supersecret"}
    )
    resp = await client.post(
        LOGIN, json={"email": "bob@example.com", "password": "supersecret"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]


async def test_login_bad_password_401(client: AsyncClient) -> None:
    await client.post(
        REGISTER, json={"email": "carol@example.com", "password": "supersecret"}
    )
    resp = await client.post(
        LOGIN, json={"email": "carol@example.com", "password": "wrongpassword"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_protected_route_without_token_401(client: AsyncClient) -> None:
    resp = await client.get(ME)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "NOT_AUTHENTICATED"


async def test_protected_route_with_token_ok(client: AsyncClient) -> None:
    reg = await client.post(
        REGISTER, json={"email": "dave@example.com", "password": "supersecret"}
    )
    token = reg.json()["access_token"]
    resp = await client.get(ME, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "dave@example.com"


async def test_protected_route_bad_token_401(client: AsyncClient) -> None:
    resp = await client.get(ME, headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_TOKEN"
