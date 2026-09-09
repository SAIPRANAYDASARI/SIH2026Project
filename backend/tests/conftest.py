"""Shared pytest fixtures.

Uses an in-memory SQLite database (via aiosqlite) for fast API integration
tests instead of spinning up Postgres — good enough for exercising route
wiring and dependency overrides. Anything that needs pgvector, full-text
search or Postgres-specific types gets a real Postgres test database in
Step 3+ (see docs/RUNBOOK.md once that's added), not this fixture.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.session import get_db
from app.main import app


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
