"""Test fixtures: a real Postgres test DB (db_test on :5433), truncated per test.

We truncate rather than roll back so the same fixtures work for the multi-worker
concurrency tests later, which depend on real commits across independent sessions
(SELECT ... FOR UPDATE SKIP LOCKED needs committed rows and separate transactions).
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.config import settings
from app.core.db import Base, get_session
from app.main import app as fastapi_app

TEST_URL = settings.test_database_url


@pytest.fixture(scope="session", autouse=True)
def _create_schema() -> None:
    """Create the schema once for the whole test session.

    A plain (sync) fixture running its own short-lived event loop, so it never
    entangles with the per-test loops of the async fixtures below.
    """

    async def _setup() -> None:
        engine = create_async_engine(TEST_URL)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(_setup())


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Fresh engine + sessionmaker per test, with all tables truncated first."""
    engine = create_async_engine(TEST_URL)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """HTTP client bound to the app, with get_session pointed at the test DB."""

    async def _override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=fastapi_app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        fastapi_app.dependency_overrides.clear()
