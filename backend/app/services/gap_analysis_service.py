"""Compares the rules engine's matched schemes for a product against the
licences a user says they hold, to flag mandatory certifications they are
missing.

MVP mapping: each `LicenceType` corresponds to one scheme code in our small
5-scheme demo dataset (`LicenceType.CML` -> `ISI_SCHEME_I`, `CRS_R` ->
`CRS`, `HUID` -> `HALLMARKING`). A production system would need a real
scheme<->licence-type mapping table (a product can have multiple applicable
schemes of the same licence "family"), not a hardcoded 1:1 dict — flagged
here as a scope decision, see docs/DECISIONS.md Step 9.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.verification import LicenceStatus, LicenceType
from app.rules.eligibility import match_schemes
from app.schemas.verification import GapCheckResponse, MissingScheme
from app.services.verification_service import find_licence

_LICENCE_TYPE_TO_SCHEME_CODE = {
    LicenceType.CML: "ISI_SCHEME_I",
    LicenceType.CRS_R: "CRS",
    LicenceType.HUID: "HALLMARKING",
}

DISCLAIMER = (
    "This gap check is based on a small illustrative 5-scheme demo dataset and "
    "keyword matching, not a legal or exhaustive determination of every "
    "certification your product needs. Verify directly with BIS."
)


async def run_gap_check(
    session: AsyncSession,
    *,
    product_description: str,
    held_licence_numbers: list[str],
) -> GapCheckResponse:
    matches = match_schemes(product_description, limit=5)

    covered_codes: set[str] = set()
    for number in held_licence_numbers:
        licence = await find_licence(session, licence_number=number)
        if licence is None or licence.status != LicenceStatus.ACTIVE:
            continue
        scheme_code = _LICENCE_TYPE_TO_SCHEME_CODE.get(licence.licence_type)
        if scheme_code:
            covered_codes.add(scheme_code)

    missing_mandatory: list[MissingScheme] = []
    missing_voluntary: list[MissingScheme] = []
    for match in matches:
        if match.scheme.code in covered_codes:
            continue
        entry = MissingScheme(
            code=match.scheme.code,
            name=match.scheme.name,
            mandatory=match.scheme.mandatory,
            reason=f"Matched on: {', '.join(match.matched_keywords)}",
        )
        if match.scheme.mandatory:
            missing_mandatory.append(entry)
        else:
            missing_voluntary.append(entry)

    return GapCheckResponse(
        matched_scheme_codes=[m.scheme.code for m in matches],
        missing_mandatory=missing_mandatory,
        missing_voluntary=missing_voluntary,
        covered_scheme_codes=sorted(covered_codes),
        disclaimer=DISCLAIMER,
    )
