from __future__ import annotations

from app.rules.loader import get_scheme_rules, load_all_scheme_rules
from app.rules.schemas import SchemeRules


def test_loads_all_yaml_files() -> None:
    schemes = load_all_scheme_rules()
    codes = {s.code for s in schemes}
    assert codes == {"ISI_SCHEME_I", "CRS", "FMCS", "HALLMARKING", "ECO_MARK"}


def test_every_scheme_is_valid() -> None:
    for scheme in load_all_scheme_rules():
        assert isinstance(scheme, SchemeRules)
        assert scheme.name
        assert scheme.source_note


def test_get_scheme_rules_case_insensitive() -> None:
    scheme = get_scheme_rules("crs")
    assert scheme is not None
    assert scheme.code == "CRS"


def test_get_scheme_rules_unknown_returns_none() -> None:
    assert get_scheme_rules("NOT_A_REAL_SCHEME") is None


def test_mandatory_schemes_flagged_correctly() -> None:
    crs = get_scheme_rules("CRS")
    isi = get_scheme_rules("ISI_SCHEME_I")
    assert crs is not None and crs.mandatory is True
    assert isi is not None and isi.mandatory is False
