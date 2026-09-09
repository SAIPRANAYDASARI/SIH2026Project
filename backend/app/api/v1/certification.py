"""Certification scheme lookup + wizard (Step 8).

Both endpoints are pure/deterministic and hit the YAML rules engine only —
no database, no LLM. `POST /wizard` is stateless: see `app.rules.wizard`
docstring for why the client resubmits the full answers dict each call.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.rules.loader import load_all_scheme_rules
from app.rules.schemas import SchemeRules
from app.rules.wizard import WizardAnswers, WizardResponse, advance_wizard

router = APIRouter(prefix="/certification", tags=["certification"])


@router.get("/schemes", response_model=list[SchemeRules])
async def list_schemes() -> list[SchemeRules]:
    return list(load_all_scheme_rules())


@router.post("/wizard", response_model=WizardResponse)
async def wizard_step(answers: WizardAnswers) -> WizardResponse:
    return advance_wizard(answers)
