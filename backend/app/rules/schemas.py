"""The typed shape of a scheme's rules YAML file (`app/rules/data/*.yaml`),
loaded by `app/rules/loader.py`. This is decision #2 from the brief,
implemented: fees, timelines, validity periods and document checklists
live here as data, not as anything an LLM authors — the answer engine
(Step 5) may quote a `RuleFee`/`RuleTimeline` value verbatim in a citation,
but never invents one.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RuleFee(BaseModel):
    category: str
    fee_inr: float
    unit: str = "per licence"


class RuleDocument(BaseModel):
    name: str
    required: bool = True
    notes: str | None = None


class SchemeRules(BaseModel):
    code: str
    name: str
    description: str
    # Keywords/product categories this scheme's eligibility check matches
    # against (see app.rules.eligibility) — a simplified MVP heuristic, not
    # a legal eligibility determination. See docs/DECISIONS.md, Step 8.
    product_keywords: list[str] = Field(default_factory=list)
    mandatory: bool = False  # True for QCO-backed compulsory schemes (CRS, some ISI)
    fees: list[RuleFee] = Field(default_factory=list)
    timeline_days: int | None = None
    validity_years: int | None = None
    required_documents: list[RuleDocument] = Field(default_factory=list)
    source_note: str = (
        "Illustrative placeholder values pending verified BIS circulars — "
        "confirm fees, timelines and document requirements directly with "
        "BIS before acting on them."
    )
