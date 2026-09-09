"""Licence verification endpoint (Step 9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.verification import VerifyRequest, VerifyResponse, VerifyResult
from app.services.verification_service import find_licence

router = APIRouter(prefix="/verify", tags=["verification"])


@router.post("", response_model=VerifyResponse)
async def verify_licence(
    payload: VerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> VerifyResponse:
    licence = await find_licence(
        db, licence_number=payload.licence_number, licence_type=payload.licence_type
    )
    if licence is None:
        return VerifyResponse(
            found=False,
            result=None,
            message=(
                "No licence found matching that number in our records. This does "
                "not necessarily mean the mark is fake — our dataset is a small "
                "illustrative demo set, not a live sync with BIS's official "
                "registries. Cross-check on the official BIS CARE portal."
            ),
        )
    note = " (demo/seed data, not a live BIS record)" if licence.is_seed_data else ""
    return VerifyResponse(
        found=True,
        result=VerifyResult.model_validate(licence),
        message=f"Licence found — status: {licence.status.value}{note}.",
    )
