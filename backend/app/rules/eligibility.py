"""Deterministic keyword-based scheme matching.

This is an **MVP heuristic**, not a legal eligibility determination: it
matches a free-text product description against each scheme's
`product_keywords` list and ranks by keyword-hit count. A real deployment
would need a proper product-classification model (e.g. against the QCO
Schedule / HSN codes) reviewed by a BIS subject-matter expert — see
docs/DECISIONS.md, Step 8, for why this scope was chosen for the hackathon
build and what a production version would need instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.rules.loader import load_all_scheme_rules
from app.rules.schemas import SchemeRules


@dataclass(frozen=True)
class SchemeMatch:
    scheme: SchemeRules
    matched_keywords: list[str]
    score: int


def match_schemes(product_description: str, *, limit: int = 3) -> list[SchemeMatch]:
    """Rank schemes by how many `product_keywords` appear in the description.

    Case-insensitive substring matching. Returns only schemes with at least
    one keyword hit, most-matches-first, capped at `limit`. Ties broken by
    scheme code for determinism.
    """
    text = product_description.lower()
    matches: list[SchemeMatch] = []
    for scheme in load_all_scheme_rules():
        hits = [kw for kw in scheme.product_keywords if kw.lower() in text]
        if hits:
            matches.append(SchemeMatch(scheme=scheme, matched_keywords=hits, score=len(hits)))
    matches.sort(key=lambda m: (-m.score, m.scheme.code))
    return matches[:limit]
