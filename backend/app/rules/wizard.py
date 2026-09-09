"""The certification wizard: a stateless multi-step Q&A state machine.

Deliberately holds no server-side session state — the client resubmits all
answers collected so far on every call (`WizardAnswers`), and this module
decides, purely as a function of those answers, whether to ask another
question or return a final result. This avoids a whole class of "wizard
session expired/mismatched" bugs and needs no new database table.

Question order:
  1. `product_description` — free text, used for keyword-based scheme matching.
  2. `manufactured_in_india` — bool, disambiguates ISI Scheme I vs FMCS when
     both would otherwise match (both are the "general" BIS product
     certification family; the country of manufacture is what actually
     decides the scheme, not the product itself).

Once both are answered, the wizard returns the best-matched scheme(s) with
their fee/timeline/document data from the rules engine, plus the
`source_note` disclaimer surfaced verbatim so the result can never look like
an authoritative BIS fee quote.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.rules.eligibility import SchemeMatch, match_schemes
from app.rules.schemas import SchemeRules


class WizardAnswers(BaseModel):
    product_description: str | None = None
    manufactured_in_india: bool | None = None


class WizardQuestion(BaseModel):
    field: str
    prompt: str
    input_type: str  # "text" | "boolean"


class WizardResultScheme(BaseModel):
    scheme: SchemeRules
    matched_keywords: list[str]


class WizardResponse(BaseModel):
    done: bool
    next_question: WizardQuestion | None = None
    results: list[WizardResultScheme] = []
    disclaimer: str | None = None


_PRODUCT_QUESTION = WizardQuestion(
    field="product_description",
    prompt="Describe the product you want to certify (e.g. 'LED bulb', 'gold jewellery').",
    input_type="text",
)

_ORIGIN_QUESTION = WizardQuestion(
    field="manufactured_in_india",
    prompt="Is the product manufactured in India?",
    input_type="boolean",
)

_GENERAL_SCHEME_CODES = {"ISI_SCHEME_I", "FMCS"}


def _resolve_origin_ambiguity(
    matches: list[SchemeMatch], manufactured_in_india: bool
) -> list[SchemeMatch]:
    """When both ISI Scheme I and FMCS matched, keep only the one that fits
    the manufacturing-location answer — they are mutually exclusive routes
    to the same underlying product standard.
    """
    codes_present = {m.scheme.code for m in matches}
    if not _GENERAL_SCHEME_CODES.issubset(codes_present):
        return matches
    wanted = "ISI_SCHEME_I" if manufactured_in_india else "FMCS"
    return [
        m for m in matches if m.scheme.code == wanted or m.scheme.code not in _GENERAL_SCHEME_CODES
    ]


def advance_wizard(answers: WizardAnswers) -> WizardResponse:
    """Given the answers collected so far, return the next question or the
    final matched-scheme result.
    """
    if not answers.product_description or not answers.product_description.strip():
        return WizardResponse(done=False, next_question=_PRODUCT_QUESTION)

    matches = match_schemes(answers.product_description)

    needs_origin = {m.scheme.code for m in matches} & _GENERAL_SCHEME_CODES
    if len(needs_origin) > 1 and answers.manufactured_in_india is None:
        return WizardResponse(done=False, next_question=_ORIGIN_QUESTION)

    if answers.manufactured_in_india is not None:
        matches = _resolve_origin_ambiguity(matches, answers.manufactured_in_india)

    results = [
        WizardResultScheme(scheme=m.scheme, matched_keywords=m.matched_keywords) for m in matches
    ]
    disclaimer = (
        results[0].scheme.source_note
        if results
        else (
            "No scheme matched this description from the current keyword table. "
            "This is a small illustrative demo dataset (5 schemes) — it is not "
            "an exhaustive list of BIS certification schemes. Consult BIS "
            "directly for a definitive determination."
        )
    )
    return WizardResponse(done=True, results=results, disclaimer=disclaimer)
