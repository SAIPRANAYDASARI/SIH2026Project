"""app.services.verification_service against a real in-memory SQLite
`licences` table — plain SQLAlchemy select, no Postgres-only functions."""

from __future__ import annotations

import datetime
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.verification import Licence, LicenceStatus, LicenceType
from app.services.verification_service import find_licence


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Licence.__table__.create)

    session_maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_find_licence_by_exact_number(db_session: AsyncSession) -> None:
    licence = Licence(
        licence_number="CML-12345",
        licence_type=LicenceType.CML,
        status=LicenceStatus.ACTIVE,
        holder_name="Demo Manufacturer Pvt Ltd",
        is_number="IS 302",
        product_category="Electrical appliance",
        valid_from=datetime.date(2024, 1, 1),
        valid_until=datetime.date(2026, 1, 1),
        is_seed_data=True,
    )
    db_session.add(licence)
    await db_session.flush()

    found = await find_licence(db_session, licence_number="CML-12345")
    assert found is not None
    assert found.holder_name == "Demo Manufacturer Pvt Ltd"


@pytest.mark.asyncio
async def test_find_licence_case_insensitive(db_session: AsyncSession) -> None:
    db_session.add(
        Licence(
            licence_number="HUID-ABC999",
            licence_type=LicenceType.HUID,
            status=LicenceStatus.ACTIVE,
            is_seed_data=True,
        )
    )
    await db_session.flush()

    found = await find_licence(db_session, licence_number="huid-abc999")
    assert found is not None


@pytest.mark.asyncio
async def test_find_licence_scoped_by_type_excludes_mismatched_type(
    db_session: AsyncSession,
) -> None:
    db_session.add(
        Licence(
            licence_number="X-1",
            licence_type=LicenceType.CML,
            status=LicenceStatus.ACTIVE,
            is_seed_data=True,
        )
    )
    await db_session.flush()

    found = await find_licence(db_session, licence_number="X-1", licence_type=LicenceType.HUID)
    assert found is None


@pytest.mark.asyncio
async def test_find_licence_not_found_returns_none(db_session: AsyncSession) -> None:
    found = await find_licence(db_session, licence_number="does-not-exist")
    assert found is None
