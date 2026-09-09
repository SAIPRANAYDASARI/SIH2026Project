from __future__ import annotations

from app.rules.eligibility import match_schemes


def test_matches_led_bulb_to_crs() -> None:
    matches = match_schemes("I want to sell an LED light in India")
    codes = [m.scheme.code for m in matches]
    assert "CRS" in codes


def test_matches_gold_jewellery_to_hallmarking() -> None:
    matches = match_schemes("gold jewellery for my showroom")
    assert matches
    assert matches[0].scheme.code == "HALLMARKING"


def test_no_match_returns_empty_list() -> None:
    matches = match_schemes("a completely unrelated widget xyz123")
    assert matches == []


def test_limit_is_respected() -> None:
    matches = match_schemes("electrical appliance cable steel led light imported", limit=2)
    assert len(matches) <= 2


def test_matches_are_ranked_by_hit_count() -> None:
    matches = match_schemes("cement steel switch cable")
    assert matches
    for earlier, later in zip(matches, matches[1:], strict=False):
        assert earlier.score >= later.score
