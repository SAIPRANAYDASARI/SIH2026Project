"""Officer analytics dashboard endpoint (Step 11).

No auth/role-check yet — there is no login system in this build (Step 6's
`app.core.session` is anonymous-only). A production deployment would gate
this behind an authenticated "officer" role; flagged in docs/DECISIONS.md
as an explicit scope gap, not something to silently pretend is handled.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.analytics import AnalyticsSummary
from app.services.analytics_service import compute_summary

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummary)
async def analytics_summary(db: AsyncSession = Depends(get_db)) -> AnalyticsSummary:
    return await compute_summary(db)
