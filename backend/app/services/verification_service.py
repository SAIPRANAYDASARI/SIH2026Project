"""Licence lookup against the `Licence` table (CM/L, CRS R-number, HUID).

MVP scope: this queries our own `licences` table, which in a real
deployment would be kept in sync with BIS's actual licence databases (CM/L
search, CRS portal, HUID registry) via a scheduled ingestion job — not
something this hackathon build has live access to. `is_seed_data` on every
row (see `app/models/verification.py`) makes that provenance explicit in
every response so a demo lookup is never mistaken for a live BIS query.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.verification import Licence, LicenceType


async def find_licence(
    session: AsyncSession,
    *,
    licence_number: str,
    licence_type: LicenceType | None = None,
) -> Licence | None:
    """Case-insensitive exact match on `licence_number`, optionally scoped to
    a specific `licence_type` (useful when the same number format could
    collide across licence types).
    """
    stmt = select(Licence).where(Licence.licence_number.ilike(licence_number.strip()))
    if licence_type is not None:
        stmt = stmt.where(Licence.licence_type == licence_type)
    result = await session.execute(stmt)
    return result.scalars().first()
