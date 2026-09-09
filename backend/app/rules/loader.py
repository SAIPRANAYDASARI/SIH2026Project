"""Loads and caches `SchemeRules` from the YAML files in `app/rules/data/`.

Deliberately has zero dependency on the database or any model — the rules
engine is pure, deterministic, file-backed data (decision #2 in
docs/DECISIONS.md), so it can be unit tested with no Postgres/LLM/network in
the loop at all.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from app.rules.schemas import SchemeRules

DATA_DIR = Path(__file__).parent / "data"


def load_scheme_rules(path: Path) -> SchemeRules:
    """Parse a single scheme YAML file into a validated `SchemeRules`."""
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return SchemeRules.model_validate(raw)


@lru_cache(maxsize=1)
def load_all_scheme_rules() -> tuple[SchemeRules, ...]:
    """Load every `*.yaml` file under `app/rules/data/`, sorted by code.

    Cached for process lifetime — these files only change at deploy time.
    Call `load_all_scheme_rules.cache_clear()` in tests that need to reload.
    """
    files = sorted(DATA_DIR.glob("*.yaml"))
    schemes = tuple(load_scheme_rules(f) for f in files)
    return schemes


def get_scheme_rules(code: str) -> SchemeRules | None:
    """Look up one scheme's rules by its `code` (case-insensitive)."""
    code_upper = code.upper()
    for scheme in load_all_scheme_rules():
        if scheme.code.upper() == code_upper:
            return scheme
    return None
