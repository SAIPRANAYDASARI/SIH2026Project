"""Identifier extraction handles the written forms named in the brief (IS
numbers, CM/L numbers, R-numbers, HUIDs, clause references); intent
classification covers all seven intents on representative queries."""

from __future__ import annotations

import pytest

from app.retrieval.query_understanding import (
    IdentifierType,
    Intent,
    analyze_query,
    classify_intent,
    extract_identifiers,
)


@pytest.mark.parametrize(
    ("text", "expected_type", "expected_value"),
    [
        ("What is IS 15111 about?", IdentifierType.IS_NUMBER, "IS 15111"),
        ("Governed by IS15111", IdentifierType.IS_NUMBER, "IS 15111"),
        ("Per IS 15111:2019", IdentifierType.IS_NUMBER, "IS 15111"),
        ("Check licence CM/L 1234567", IdentifierType.CML_NUMBER, "CM/L 1234567"),
        ("Check licence CML1234567", IdentifierType.CML_NUMBER, "CM/L 1234567"),
        ("Verify R-1234567", IdentifierType.CRS_R_NUMBER, "R-1234567"),
        ("Is HUID AZ4526 genuine?", IdentifierType.HUID, "AZ4526"),
        ("See clause 4.2.1 for details", IdentifierType.CLAUSE_REFERENCE, "4.2.1"),
    ],
)
def test_extracts_each_identifier_form(
    text: str, expected_type: IdentifierType, expected_value: str
) -> None:
    identifiers = extract_identifiers(text)
    matching = [i for i in identifiers if i.type is expected_type]
    assert any(i.value == expected_value for i in matching)


def test_bare_clause_number_without_keyword_is_detected() -> None:
    identifiers = extract_identifiers("What does 4.2.1 require?")
    matching = [i for i in identifiers if i.type is IdentifierType.CLAUSE_REFERENCE]
    assert any(i.value == "4.2.1" for i in matching)


def test_no_identifiers_in_plain_query() -> None:
    assert extract_identifiers("What is the weather today?") == []


@pytest.mark.parametrize(
    ("query", "expected_intent"),
    [
        ("What is the weather today?", Intent.OUT_OF_SCOPE),
        ("Verify CM/L 1234567", Intent.VERIFICATION),
        ("Is this HUID genuine?", Intent.VERIFICATION),
        ("Which scheme applies to LED drivers, ISI or CRS?", Intent.SCHEME_ELIGIBILITY),
        ("How do I apply for a BIS certification licence?", Intent.PROCESS_HOWTO),
        ("What is IS 15111 about?", Intent.STANDARD_LOOKUP),
        ("Which standard applies to my LED driver?", Intent.PRODUCT_TO_STANDARD),
        ("Is this fake helmet safe to use, I want to complain", Intent.CONSUMER_SAFETY),
    ],
)
def test_classifies_intent(query: str, expected_intent: Intent) -> None:
    identifiers = extract_identifiers(query)
    assert classify_intent(query, identifiers) is expected_intent


def test_analyze_query_returns_both_intent_and_identifiers() -> None:
    analysis = analyze_query("What is IS 15111 about?")
    assert analysis.intent is Intent.STANDARD_LOOKUP
    assert len(analysis.identifiers) == 1
    assert analysis.identifiers_of(IdentifierType.IS_NUMBER)[0].value == "IS 15111"
