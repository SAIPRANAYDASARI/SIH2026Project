"""app.services.gap_analysis_service against a real in-memory SQLite
`licences` table, combined with the real (file-backed) rules engine."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.verification import Licence, LicenceStatus, LicenceType
from app.services.gap_analysis_service import run_gap_check


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
async def test_no_held_licences_flags_mandatory_scheme_missing(
    db_session: AsyncSession,
) -> None:
    result = await run_gap_check(
        db_session, product_description="LED light bulb", held_licence_numbers=[]
    )
    assert "CRS" in result.matched_scheme_codes
    assert any(m.code == "CRS" for m in result.missing_mandatory)
    assert result.covered_scheme_codes == []


@pytest.mark.asyncio
async def test_active_matching_licence_covers_the_scheme(db_session: AsyncSession) -> None:
    db_session.add(
        Licence(
            licence_number="R-999",
            licence_type=LicenceType.CRS_R,
            status=LicenceStatus.ACTIVE,
            is_seed_data=True,
        )
    )
    await db_session.flush()

    result = await run_gap_check(
        db_session,
        product_description="LED light bulb",
        held_licence_numbers=["R-999"],
    )
    assert "CRS" in result.covered_scheme_codes
    assert not any(m.code == "CRS" for m in result.missing_mandatory)


@pytest.mark.asyncio
async def test_expired_licence_does_not_count_as_coverage(db_session: AsyncSession) -> None:
    db_session.add(
        Licence(
            licence_number="R-EXP",
            licence_type=LicenceType.CRS_R,
            status=LicenceStatus.EXPIRED,
            is_seed_data=True,
        )
    )
    await db_session.flush()

    result = await run_gap_check(
        db_session,
        product_description="LED light bulb",
        held_licence_numbers=["R-EXP"],
    )
    assert "CRS" not in result.covered_scheme_codes
    assert any(m.code == "CRS" for m in result.missing_mandatory)


@pytest.mark.asyncio
async def test_disclaimer_always_present(db_session: AsyncSession) -> None:
    result = await run_gap_check(
        db_session, product_description="gold jewellery", held_licence_numbers=[]
    )
    assert result.disclaimer
