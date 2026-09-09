"""Detects exact identifiers in a query (IS numbers, CM/L numbers, CRS
R-numbers, HUIDs, clause references) so they can be routed to exact-match
lookup ahead of fuzzy retrieval, and classifies the query into one of the
seven intents from the brief.

Intent classification here is a small, fast, keyword-based heuristic — not
a trained or LLM-based classifier. It exists so the retrieval core (Step 4)
and its CLI are usable and testable before the answer engine (Step 5) has
an LLM in the loop at all, per the "How to proceed" ordering. Step 5's
intent-specific instruction blocks should treat this as a first pass to
refine, not a finished classifier — see docs/DECISIONS.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum


class Intent(StrEnum):
    STANDARD_LOOKUP = "standard_lookup"
    PRODUCT_TO_STANDARD = "product_to_standard"
    SCHEME_ELIGIBILITY = "scheme_eligibility"
    PROCESS_HOWTO = "process_howto"
    VERIFICATION = "verification"
    CONSUMER_SAFETY = "consumer_safety"
    OUT_OF_SCOPE = "out_of_scope"


class IdentifierType(StrEnum):
    IS_NUMBER = "is_number"
    CML_NUMBER = "cml_number"
    CRS_R_NUMBER = "crs_r_number"
    HUID = "huid"
    CLAUSE_REFERENCE = "clause_reference"


@dataclass(frozen=True)
class Identifier:
    type: IdentifierType
    value: str  # normalized form, e.g. "IS 15111", "CM/L 1234567"
    raw: str  # exactly as it appeared in the query


@dataclass(frozen=True)
class QueryAnalysis:
    intent: Intent
    identifiers: list[Identifier] = field(default_factory=list)

    def identifiers_of(self, type_: IdentifierType) -> list[Identifier]:
        return [i for i in self.identifiers if i.type is type_]


# --- Identifier patterns -----------------------------------------------------
# Written forms per the brief: "IS numbers in all written forms, CM/L
# numbers, R-numbers, HUIDs, clause references".

_IS_NUMBER = re.compile(
    r"\bIS[\s:-]?(\d{3,6})(?:\s*\(Part\s*\d+\))?(?:\s*:\s*\d{4})?\b", re.IGNORECASE
)
_CML_NUMBER = re.compile(r"\bCM/?L[\s:-]?(\d{6,9})\b", re.IGNORECASE)
_CRS_R_NUMBER = re.compile(r"\bR[\s:-](\d{6,9})\b", re.IGNORECASE)
_HUID = re.compile(r"\bHUID[\s:-]?([A-Z0-9]{6})\b", re.IGNORECASE)
_CLAUSE_REFERENCE = re.compile(
    r"\bclause\s+(\d+(?:\.\d+){0,4})\b|\b(\d+\.\d+(?:\.\d+){0,3})\b", re.IGNORECASE
)


def extract_identifiers(query: str) -> list[Identifier]:
    identifiers: list[Identifier] = []

    for match in _IS_NUMBER.finditer(query):
        identifiers.append(
            Identifier(IdentifierType.IS_NUMBER, f"IS {match.group(1)}", match.group(0))
        )
    for match in _CML_NUMBER.finditer(query):
        identifiers.append(
            Identifier(IdentifierType.CML_NUMBER, f"CM/L {match.group(1)}", match.group(0))
        )
    for match in _CRS_R_NUMBER.finditer(query):
        identifiers.append(
            Identifier(IdentifierType.CRS_R_NUMBER, f"R-{match.group(1)}", match.group(0))
        )
    for match in _HUID.finditer(query):
        identifiers.append(Identifier(IdentifierType.HUID, match.group(1).upper(), match.group(0)))
    for match in _CLAUSE_REFERENCE.finditer(query):
        clause = match.group(1) or match.group(2)
        identifiers.append(Identifier(IdentifierType.CLAUSE_REFERENCE, clause, match.group(0)))

    return identifiers


# --- Intent classification --------------------------------------------------

_DOMAIN_KEYWORDS = (
    "bis",
    "standard",
    "certification",
    "certificate",
    "isi",
    "crs",
    "fmcs",
    "hallmark",
    "hallmarking",
    "scheme",
    "licence",
    "license",
    "cm/l",
    "cml",
    "huid",
    "mark",
    "qco",
    "compulsory registration",
    "eco mark",
    "quality control order",
    "clause",
)
_VERIFICATION_KEYWORDS = (
    "verify",
    "genuine",
    "fake",
    "counterfeit",
    "valid",
    "expired",
    "cm/l",
    "cml",
    "r-number",
    "r number",
    "huid",
    "check this mark",
    "check the mark",
    "authentic",
)
_SCHEME_KEYWORDS = (
    "scheme",
    "isi mark",
    "crs",
    "fmcs",
    "hallmark",
    "eco mark",
    "which certification",
    "need certification",
    "eligib",
    "compulsory",
)
_PROCESS_KEYWORDS = (
    "how to",
    "how do i",
    "steps",
    "process",
    "apply",
    "application",
    "procedure",
    "documents required",
    "document checklist",
    "timeline",
    "fee",
    "cost",
    "how long",
)
_CONSUMER_SAFETY_KEYWORDS = (
    "safe",
    "safety",
    "fake",
    "counterfeit",
    "complain",
    "complaint",
    "duplicate",
    "harm",
    "injur",
    "report a",
    "cheated",
)
_PRODUCT_LOOKUP_KEYWORDS = (
    "which standard",
    "which is number",
    "what standard",
    "standard for",
    "standard applies",
    "applicable standard",
)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def classify_intent(query: str, identifiers: list[Identifier]) -> Intent:
    text = query.lower()

    # A query counts as in-domain if it names BIS/standards vocabulary, an
    # exact identifier, or reads as a consumer-safety/verification report
    # (e.g. "fake helmet", "is this genuine") — those don't always mention
    # "BIS" or "standard" by name but are squarely in scope.
    in_domain = (
        _contains_any(text, _DOMAIN_KEYWORDS)
        or _contains_any(text, _CONSUMER_SAFETY_KEYWORDS)
        or _contains_any(text, _VERIFICATION_KEYWORDS)
        or bool(identifiers)
    )
    if not in_domain:
        return Intent.OUT_OF_SCOPE

    has_verification_identifier = any(
        i.type in (IdentifierType.CML_NUMBER, IdentifierType.CRS_R_NUMBER, IdentifierType.HUID)
        for i in identifiers
    )
    if has_verification_identifier:
        return Intent.VERIFICATION

    # Consumer-safety keywords ("fake", "safe") overlap with verification
    # keywords ("fake", "genuine"), but wording like "safe to use" / "I want
    # to complain" is a stronger signal of a consumer-safety report than a
    # standalone licence/mark check, so it's checked first when there's no
    # explicit verification identifier (CM/L, R-number, HUID) in the query.
    if _contains_any(text, _CONSUMER_SAFETY_KEYWORDS):
        return Intent.CONSUMER_SAFETY

    if _contains_any(text, _VERIFICATION_KEYWORDS):
        return Intent.VERIFICATION

    if _contains_any(text, _SCHEME_KEYWORDS):
        return Intent.SCHEME_ELIGIBILITY

    if _contains_any(text, _PROCESS_KEYWORDS):
        return Intent.PROCESS_HOWTO

    has_is_number = any(i.type is IdentifierType.IS_NUMBER for i in identifiers)
    if has_is_number and not _contains_any(text, _PRODUCT_LOOKUP_KEYWORDS):
        return Intent.STANDARD_LOOKUP

    if _contains_any(text, _PRODUCT_LOOKUP_KEYWORDS) or not identifiers:
        return Intent.PRODUCT_TO_STANDARD

    return Intent.STANDARD_LOOKUP


def analyze_query(query: str) -> QueryAnalysis:
    identifiers = extract_identifiers(query)
    intent = classify_intent(query, identifiers)
    return QueryAnalysis(intent=intent, identifiers=identifiers)
