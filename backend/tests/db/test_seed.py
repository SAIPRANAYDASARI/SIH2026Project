"""app.db.seed against a real in-memory SQLite schema — verifies
idempotency and the `is_seed_data` flag.

`Standard.applicable_schemes` is a Postgres `ARRAY` column (see
`app.models.standard`), which SQLite's dialect can't compile a `CREATE
TABLE` for, so `_seed_standards` is exercised only for its data (count,
natural keys), not against a real session here — the same
Postgres-only-type carve-out other tests in this suite already make (see
`tests/conftest.py`'s docstring).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.seed import _LICENCES, _SCHEMES, _STANDARDS, _seed_licences, _seed_schemes
from app.models.certification import Scheme
from app.models.verification import Licence


def test_standards_seed_data_has_unique_is_numbers() -> None:
    is_numbers = [row["is_number"] for row in _STANDARDS]
    assert len(is_numbers) == len(set(is_numbers))
    assert len(is_numbers) >= 4


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Scheme.__table__.create)
        await conn.run_sync(Licence.__table__.create)

    session_maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_seed_inserts_all_rows_and_flags_seed_data(db_session: AsyncSession) -> None:
    schemes_inserted = await _seed_schemes(db_session)
    licences_inserted = await _seed_licences(db_session)
    await db_session.flush()

    assert schemes_inserted == len(_SCHEMES)
    assert licences_inserted == len(_LICENCES)

    licences = (await db_session.execute(select(Licence))).scalars().all()
    assert all(licence.is_seed_data for licence in licences)


@pytest.mark.asyncio
async def test_seed_is_idempotent(db_session: AsyncSession) -> None:
    await _seed_schemes(db_session)
    await _seed_licences(db_session)
    await db_session.flush()

    second_schemes = await _seed_schemes(db_session)
    second_licences = await _seed_licences(db_session)

    assert second_schemes == 0
    assert second_licences == 0
