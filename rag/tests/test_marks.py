"""Mark and licence decoding.

The safety property here is narrow and absolute: this tool must never imply
that a number is genuine. It checks shape. A counterfeit licence number has
a perfectly valid shape, so wording like "valid" or "genuine" would turn the
tool into a laundering device for fakes.
"""

from __future__ import annotations

import pytest

from rag.marks import decode


@pytest.mark.parametrize(
    "value",
    ["CM/L 6300082303", "CM/L-6300082303", "cm/l 6300082303", "CML6300082303"],
)
def test_recognises_licence_number_formats(value):
    r = decode(value)
    assert r.kind == "licence" and r.recognised


def test_licence_with_unusual_digit_count_is_flagged_not_rejected():
    r = decode("CM/L 12345678901")   # 11 digits
    assert r.recognised
    assert any("10 digits" in w for w in r.warnings)


def test_recognises_huid():
    r = decode("A1B2C3")
    assert r.kind == "hallmark" and r.recognised


def test_six_letters_without_a_digit_is_not_assumed_to_be_a_huid():
    # "LEATHER"-style words shouldn't be read as hallmark codes.
    assert decode("ABCDEF").kind != "hallmark"


@pytest.mark.parametrize("value", ["IS 17440", "IS 17440:2020", "IS/IEC 62368-1"])
def test_recognises_standard_references(value):
    r = decode(value)
    assert r.kind == "standard" and r.recognised


def test_standard_is_explained_as_not_being_a_licence():
    assert "not a licence" in decode("IS 17440").explanation.lower()


def test_unrecognised_input_is_not_called_fake():
    r = decode("hello there 123")
    assert not r.recognised
    assert "not proof" in r.caution.lower()


def test_empty_input_is_handled():
    assert decode("").kind == "unknown"
    assert decode("   ").recognised is False


@pytest.mark.parametrize("value", ["CM/L 6300082303", "A1B2C3", "R-1234567890"])
def test_never_claims_a_number_is_genuine(value):
    """The core guarantee: format recognition is not authentication."""
    r = decode(value)
    blob = f"{r.explanation} {r.format_note} {r.caution}".lower()
    for forbidden in ("is genuine", "is valid", "verified", "authentic", "confirmed valid"):
        assert forbidden not in blob, f"{value}: leaked '{forbidden}'"
    assert "format check only" in r.caution.lower()


@pytest.mark.parametrize("value", ["CM/L 6300082303", "A1B2C3", "R-1234567890"])
def test_recognised_identifiers_point_at_an_official_check(value):
    r = decode(value)
    assert r.verify_at is not None
    assert r.verify_at[1].startswith("https://")


def test_crs_shape_check_admits_it_is_weaker():
    # The CRS format is not documented in the corpus, so the claim is hedged.
    assert "not documented in the indexed corpus" in decode("R-1234567890").caution
