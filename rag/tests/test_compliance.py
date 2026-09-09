"""Compliance timeline correctness.

The date on a compliance timeline is the whole product. An amendment shown at
the wrong year tells a manufacturer their obligation started six years earlier
or two years later than it did, so these tests pin the exact mistakes that
were caught while building this.
"""

from __future__ import annotations

from datetime import date

import pytest

from rag.compliance import (
    OrderKind,
    classify,
    known_products,
    parse_notification_date,
    product_name,
)


# ── Dates ────────────────────────────────────────────────────────────────

def test_reads_the_english_gazette_masthead():
    text = "NEW DELHI, TUESDAY, FEBRUARY 11, 2025/MAGHA 22, 1946 ... ORDER"
    d, source = parse_notification_date(text)
    assert d == date(2025, 2, 11)
    assert "masthead" in source


def test_reads_the_hindi_dateline_when_english_is_absent():
    # Every gazette leads with the Hindi page; the leading syllable of दिल्ली
    # is often mangled to ददल्ली by the PDF's broken font.
    text = "आदेि नई ददल्ली, 11 फरवरी, 2025 का.आ. 695(अ).— भारतीय मानक"
    d, source = parse_notification_date(text)
    assert d == date(2025, 2, 11)
    assert "Hindi" in source


def test_ignores_the_date_of_the_order_being_amended():
    """Regression: an amendment quotes the original order's date. Reading that
    put a February 2025 amendment on the timeline at December 2019."""
    text = (
        "NEW DELHI, TUESDAY, FEBRUARY 11, 2025 ... in the Air Conditioner "
        "(Quality Control) Order, 2019 published vide S.O. 4354(E) dated the "
        "5th December, 2019, the following amendments are made"
    )
    d, _ = parse_notification_date(text)
    assert d == date(2025, 2, 11)


def test_does_not_mistake_an_enforcement_deadline_for_a_notification_date():
    """Regression: 'shall come into force on 31st March 2027' was being read
    as the order's own date, putting it in the future."""
    text = "This order shall come into force on the 31st March, 2027 for all goods."
    d, source = parse_notification_date(text)
    assert d is None
    assert source == "not stated in document"


def test_unparseable_date_is_reported_not_guessed():
    d, source = parse_notification_date("An order with no recognisable dateline at all.")
    assert d is None and source == "not stated in document"


def test_invalid_calendar_date_is_rejected():
    d, _ = parse_notification_date("NEW DELHI, MONDAY, FEBRUARY 31, 2025")
    assert d is None


# ── Classification ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "filename,expected",
    [
        ("Acetone-Extension__dup2.pdf", OrderKind.EXTENSION),
        ("Air-Conditioner-QCO-Amendment-Order-2025.pdf", OrderKind.AMENDMENT),
        ("Footwear-made-from-Leather-Quality-Control-Order.pdf", OrderKind.ORIGINAL),
    ],
)
def test_classifies_order_kind(filename, expected):
    assert classify(filename, "") == expected


def test_amendment_detected_from_text_when_filename_is_silent():
    assert classify("SO-1234.pdf", "further to amend the said order") == OrderKind.AMENDMENT


# ── Product naming ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "filename,expected_word",
    [
        ("Acetone-Extension-2__dup2.pdf", "Acetone"),
        ("Amendment-in-the-Acetone-Quality-Control-Order-2020__dup2.pdf", "Acetone"),
        ("Toys-Quality-Control-Second-Amendment-Order-2020.pdf", "Toys"),
    ],
)
def test_product_name_survives_the_boilerplate(filename, expected_word):
    assert expected_word in product_name(filename)


def test_product_name_drops_duplicate_and_year_markers():
    name = product_name("Acid-Oil-Quality-Control-Amendment-Order-2025__dup2.pdf")
    assert "dup" not in name.lower() and "2025" not in name


# ── Live corpus checks ───────────────────────────────────────────────────

def test_known_products_excludes_administrative_filenames():
    """'Date of Implementation...' names a notification, not a product."""
    names = {n.lower() for n, _ in known_products()}
    for junk in ("date implementation", "enforcement date", "chemicals march"):
        assert junk not in names


def test_known_products_only_lists_real_chains():
    for _, count in known_products(min_orders=2):
        assert count >= 2
