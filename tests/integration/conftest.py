"""Integration-test harness: a real Postgres via TEST_DATABASE_URL.

Skipped entirely when TEST_DATABASE_URL is unset, so `pytest` stays green
without infrastructure. Locally:

    docker compose up -d postgres
    TEST_DATABASE_URL=postgresql+asyncpg://alphaquant:change-me@localhost:5432/alphaquant \
        .venv/bin/pytest tests/integration -m integration
"""

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from alphaquant.data.repositories.db import Base, create_engine_and_sessionmaker

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.integration


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    if not TEST_DB_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    engine, factory = create_engine_and_sessionmaker(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()
