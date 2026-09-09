"""Integration tests for POST /api/v1/verify against a real in-memory
SQLite `licences` table, driven through the actual ASGI app."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.session import get_db
from app.main import app
from app.models.verification import Licence, LicenceStatus, LicenceType


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Licence.__table__.create)

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


@pytest.mark.asyncio
async def test_verify_not_found(client: AsyncClient) -> None:
    response = await client.post("/api/v1/verify", json={"licence_number": "nope"})
    assert response.status_code == 200
    body = response.json()
    assert body["found"] is False


@pytest.mark.asyncio
async def test_verify_found(client: AsyncClient, db_session: AsyncSession) -> None:
    db_session.add(
        Licence(
            licence_number="CML-777",
            licence_type=LicenceType.CML,
            status=LicenceStatus.ACTIVE,
            is_seed_data=True,
        )
    )
    await db_session.flush()

    response = await client.post("/api/v1/verify", json={"licence_number": "CML-777"})
    assert response.status_code == 200
    body = response.json()
    assert body["found"] is True
    assert body["result"]["status"] == "active"
