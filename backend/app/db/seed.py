"""Demo-data seeding script (Step 13).

Gated by `settings.seed_demo_data` (`SEED_DEMO_DATA=true` in `.env`) so a
production deployment with real crawled/ingested content never
accidentally gets demo rows mixed in. Every row this script inserts sets
`is_seed_data=True` (on the models that have that column —
`Scheme`/`Standard` don't carry demo-vs-real provenance the way
`Licence`/`Conversation` do, since they'd normally come from the Step 2/3
ingestion pipeline instead; this script is a stand-in for that pipeline
when running a fresh demo with no crawl/ingest step performed yet) so they
can be identified and wiped later without a manual audit.

Idempotent: running it twice does not duplicate rows — every insert is
guarded by a "does a row with this natural key already exist" check.

Run via `python -m app.db.seed` (wired into `infra/docker-compose.prod.yml`
as the one-shot `seed` service) or directly for local/dev seeding.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import AsyncSessionLocal
from app.models.certification import Scheme
from app.models.standard import Standard
from app.models.verification import Licence, LicenceStatus, LicenceType

logger = get_logger(__name__)

_STANDARDS: list[dict[str, Any]] = [
    dict(
        is_number="IS 15111",
        title="LED luminaires for general lighting — Safety requirements",
        scope="Safety and performance requirements for LED luminaires used for general lighting.",
        technical_committee="ETD 32",
        is_qco_mandatory=True,
        applicable_schemes=["CRS"],
    ),
    dict(
        is_number="IS 302",
        title="Safety of household and similar electrical appliances",
        scope="General safety requirements for household electrical appliances.",
        technical_committee="ETD 32",
        is_qco_mandatory=True,
        applicable_schemes=["ISI_SCHEME_I"],
    ),
    dict(
        is_number="IS 2347",
        title="Specification for domestic pressure cookers",
        scope="Safety and performance requirements for domestic pressure cookers.",
        technical_committee="FAD 18",
        is_qco_mandatory=True,
        applicable_schemes=["ISI_SCHEME_I"],
    ),
    dict(
        is_number="IS 1417",
        title="Grades of gold/silver alloys, palladium and platinum",
        scope="Purity/fineness grades for hallmarked precious metal jewellery.",
        technical_committee="MTD 25",
        is_qco_mandatory=True,
        applicable_schemes=["HALLMARKING"],
    ),
]

_SCHEMES: list[dict[str, Any]] = [
    dict(
        code="ISI_SCHEME_I",
        name="ISI Mark — Scheme I (Standard Mark of Conformity)",
        rules_yaml_path="app/rules/data/isi_scheme_i.yaml",
    ),
    dict(
        code="CRS",
        name="Compulsory Registration Scheme",
        rules_yaml_path="app/rules/data/crs.yaml",
    ),
    dict(
        code="FMCS",
        name="Foreign Manufacturers Certification Scheme",
        rules_yaml_path="app/rules/data/fmcs.yaml",
    ),
    dict(
        code="HALLMARKING",
        name="Gold/Silver Hallmarking",
        rules_yaml_path="app/rules/data/hallmarking.yaml",
    ),
    dict(code="ECO_MARK", name="Eco Mark", rules_yaml_path="app/rules/data/eco_mark.yaml"),
]

_LICENCES: list[dict[str, Any]] = [
    dict(
        licence_number="CML-DEMO-0001",
        licence_type=LicenceType.CML,
        status=LicenceStatus.ACTIVE,
        holder_name="Demo Electricals Pvt Ltd",
        is_number="IS 302",
        product_category="Electrical appliance",
        valid_from=datetime.date(2024, 1, 1),
        valid_until=datetime.date(2027, 1, 1),
    ),
    dict(
        licence_number="R-DEMO-0002",
        licence_type=LicenceType.CRS_R,
        status=LicenceStatus.ACTIVE,
        holder_name="Demo Lighting Co",
        is_number="IS 15111",
        product_category="LED luminaire",
        valid_from=datetime.date(2024, 6, 1),
        valid_until=datetime.date(2026, 6, 1),
    ),
    dict(
        licence_number="HUID-DEMOAB12",
        licence_type=LicenceType.HUID,
        status=LicenceStatus.ACTIVE,
        holder_name="Demo Jewellers",
        product_category="Gold jewellery",
    ),
    dict(
        licence_number="CML-DEMO-EXPIRED",
        licence_type=LicenceType.CML,
        status=LicenceStatus.EXPIRED,
        holder_name="Lapsed Demo Manufacturer",
        is_number="IS 2347",
        product_category="Pressure cooker",
        valid_from=datetime.date(2020, 1, 1),
        valid_until=datetime.date(2022, 1, 1),
    ),
]


async def _seed_standards(session: AsyncSession) -> int:
    inserted = 0
    for row in _STANDARDS:
        existing = await session.execute(
            select(Standard).where(Standard.is_number == row["is_number"])
        )
        if existing.scalars().first() is not None:
            continue
        session.add(Standard(**row))
        inserted += 1
    return inserted


async def _seed_schemes(session: AsyncSession) -> int:
    inserted = 0
    for row in _SCHEMES:
        existing = await session.execute(select(Scheme).where(Scheme.code == row["code"]))
        if existing.scalars().first() is not None:
            continue
        session.add(Scheme(**row))
        inserted += 1
    return inserted


async def _seed_licences(session: AsyncSession) -> int:
    inserted = 0
    for row in _LICENCES:
        existing = await session.execute(
            select(Licence).where(Licence.licence_number == row["licence_number"])
        )
        if existing.scalars().first() is not None:
            continue
        session.add(Licence(**row, is_seed_data=True))
        inserted += 1
    return inserted


async def run_seed() -> None:
    settings = get_settings()
    if not settings.seed_demo_data:
        logger.info("seed_skipped", reason="SEED_DEMO_DATA is not set to true")
        return

    async with AsyncSessionLocal() as session:
        standards_inserted = await _seed_standards(session)
        schemes_inserted = await _seed_schemes(session)
        licences_inserted = await _seed_licences(session)
        await session.commit()

    logger.info(
        "seed_complete",
        standards_inserted=standards_inserted,
        schemes_inserted=schemes_inserted,
        licences_inserted=licences_inserted,
    )


def main() -> None:
    configure_logging()
    asyncio.run(run_seed())


if __name__ == "__main__":
    main()
