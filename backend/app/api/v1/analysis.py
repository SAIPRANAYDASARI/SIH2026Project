"""Gap analysis endpoint (Step 9)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.verification import GapCheckRequest, GapCheckResponse
from app.services.gap_analysis_service import run_gap_check

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/gap-check", response_model=GapCheckResponse)
async def gap_check(
    payload: GapCheckRequest,
    db: AsyncSession = Depends(get_db),
) -> GapCheckResponse:
    return await run_gap_check(
        db,
        product_description=payload.product_description,
        held_licence_numbers=payload.held_licence_numbers,
    )
