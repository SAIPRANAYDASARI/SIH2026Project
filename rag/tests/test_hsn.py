"""HSN import/export compliance lookup.

This is a dedicated, deterministic lookup tool — like rag/marks.py's
licence/HUID decoder — surfaced through its own UI tab and API endpoint,
NOT wired into chat/answer_question. An earlier version routed HSN-looking
chat questions through fuzzy product-name search automatically, which
produced wrong answers (a "electric kettle" compliance question returning a
ceramic-tile row, because common English words in the question happened to
overlap with that row's wording) and no clear way for a user to tell a
confident exact match from a fuzzy guess. Exact code lookup is precise by
construction; free-text intent detection is not, so it was pulled out of
chat entirely in favour of a form the user fills in themselves.

These tests exist to prove the code lookup returns the exact row (no
similarity ranking involved at all), that leading zeros and mojibake don't
silently break it, and that the product-name search — used only when the
user explicitly asks to search by name, never automatically from a chat
question — filters out compliance-question wrapper words that would
otherwise drown out the real product terms.
"""

import sqlite3

import pytest

from rag import hsn


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    hsn.init_schema(c)
    rows = [
        # (hsn_cd, level, chapter, chapter_title, heading, product, import_core_docs,
        #  import_bis_is, import_dgft_policy, import_licence_required,
        #  import_monitoring_system, import_coo, import_other_noc,
        #  export_core_docs, export_dgft_policy, export_other_noc,
        #  primary_regulator, verify_against)
        ("1011010", "Tariff Item", "1", "Live animals", "101",
         "LIVE HORSES PURE-BRED BREEDING ANIMALS",
         "Bill of Entry; IEC", "Not notified", "Restricted",
         "Yes", None, "Preferential CoO", "Sanitary Import Permit",
         "Shipping Bill", "Free", "Veterinary Certificate",
         "DAHD", "DGFT ITC(HS)"),
        ("71141910", "Tariff Item", "71", "Natural pearls, precious stones", "7114",
         "ARTICLES OF GOLD",
         "Bill of Entry; IEC", "IS 1417 hallmarking", "Free",
         None, None, None, None,
         "Shipping Bill", "Free", None,
         "BIS", "BIS hallmarking scheme"),
        # Real row from the workbook, kept verbatim: its wording happens to
        # share several common English words ("whether", "the", "is") with
        # an ordinary compliance question, which is exactly what caused the
        # reported bug (a kettle question returning this ceramic-tile row).
        ("690710", "Tariff Item", "69", "Ceramic products", "6907",
         "TILES, CUBES AND SIMILAR ARTICLES, WHETHER OR NOT RECTANGULAR, "
         "THE LARGEST SURFACE AREA OF WHICH IS CAPABLE OF BEING ENCLOSED "
         "IN A SQUARE THE SIDE OF WHICH IS LESS THAN 7 CM",
         "Bill of Entry; IEC", "Not notified", "Free",
         None, None, None, None,
         "Shipping Bill", "Free", None,
         "BIS", "BIS QCO list"),
        ("95038010", "Tariff Item", "95", "Toys, games and sports requisites", "9503",
         "OTHER TOYS; REDUCED-SIZE MODELS AND SIMILAR RECREATIONAL MODELS",
         "Bill of Entry; IEC", "IS 9873 toy safety", "Free",
         None, None, None, None,
         "Shipping Bill", "Free", None,
         "BIS", "BIS toy QCO"),
    ]
    c.executemany(
        """INSERT INTO hsn_codes (
            hsn_cd, level, chapter, chapter_title, heading, product,
            import_core_docs, import_bis_is, import_dgft_policy,
            import_licence_required, import_monitoring_system, import_coo,
            import_other_noc, export_core_docs, export_dgft_policy,
            export_other_noc, primary_regulator, verify_against
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        rows,
    )
    c.execute("INSERT INTO hsn_fts(hsn_fts) VALUES('rebuild')")
    c.commit()
    return c


# ── lookup_by_code ───────────────────────────────────────────────────────

def test_exact_code_lookup(conn):
    row = hsn.lookup_by_code(conn, "1011010")
    assert row is not None
    assert row.product == "LIVE HORSES PURE-BRED BREEDING ANIMALS"


def test_leading_zeros_are_normalised(conn):
    """A user typing the full 8-digit form with a leading zero must find the
    same row as the bare integer stored from the workbook."""
    assert hsn.lookup_by_code(conn, "01011010").hsn_cd == \
           hsn.lookup_by_code(conn, "1011010").hsn_cd


def test_unmatched_code_returns_none(conn):
    assert hsn.lookup_by_code(conn, "99999999") is None


def test_non_numeric_input_does_not_crash(conn):
    assert hsn.lookup_by_code(conn, "not a code") is None
    assert hsn.lookup_by_code(conn, "") is None


# ── search_by_product ────────────────────────────────────────────────────

def test_product_search_finds_the_right_row(conn):
    rows = hsn.search_by_product(conn, "gold articles")
    assert rows and rows[0].hsn_cd == "71141910"


def test_product_search_no_match_returns_empty(conn):
    assert hsn.search_by_product(conn, "spacecraft parts") == []


# ── mentions_hsn / extract_code ──────────────────────────────────────────

@pytest.mark.parametrize("question,expected", [
    ("what is HSN 1011010?", True),
    ("documents to import HS code 1011010", True),
    ("tariff code for gold jewellery", True),
    ("what is IS 9873?", False),
    ("hello there", False),
    ("how do I renew a CRS registration?", False),
])
def test_mentions_hsn(question, expected):
    assert hsn.mentions_hsn(question) is expected


def test_extract_code_gets_the_number():
    assert hsn.extract_code("what is HSN 1011010 required for?") == "1011010"


def test_strip_trigger_words_removes_hsn_but_keeps_product():
    cleaned = hsn.strip_trigger_words("what documents for HSN gold jewellery")
    assert "hsn" not in cleaned.lower()
    assert "gold" in cleaned.lower()


# ── strip_filler_words / search_by_product regression ────────────────────
#
# Reported bug: "I sell electric kettles in India. What is the HSN code, GST
# rate, and whether BIS certification is required?" returned a ceramic tile
# row and other unrelated products. Root cause was search_by_product sending
# every word in the question (including "is", "the", "and", "whether") into
# an unfiltered OR query — words that happened to also appear inside the
# tariff's own verbose legal wording ("...WHETHER OR NOT RECTANGULAR, THE
# LARGEST...IS CAPABLE...").

def test_compliance_question_does_not_match_an_unrelated_ceramic_row(conn):
    """The exact bug report: a compliance question about one product must
    not surface a completely unrelated row just because they share common
    English words."""
    question = (
        "I sell electric kettles in India. What is the HSN code, GST rate, "
        "and whether BIS certification is required?"
    )
    rows = hsn.search_by_product(conn, hsn.strip_filler_words(question), top_k=5)
    assert all(r.hsn_cd != "690710" for r in rows), (
        "the ceramic tile row must not appear for a question that never "
        "mentions ceramics, tiles, or anything related to them"
    )


def test_compliance_question_finds_the_real_product_despite_wrapper_words(conn):
    """"I manufacture toys, what HSN code and documents are required?" must
    find the toy row — "manufacture"/"required"/"documents" are compliance
    wrapper words, not product words, and must not drown out "toys"."""
    question = "I manufacture toys, what HSN code and documents are required?"
    rows = hsn.search_by_product(conn, hsn.strip_filler_words(question), top_k=3)
    assert rows and rows[0].hsn_cd == "95038010"


@pytest.mark.parametrize("word", [
    "sell", "buy", "gst", "rate", "certification", "required", "documents",
    "compliance", "licence", "import", "export", "bis", "india", "code",
    "whether", "manufacture", "manufacturing", "product",
])
def test_filler_word_is_actually_removed(word):
    cleaned = hsn.strip_filler_words(f"what {word} do I need for this item")
    assert word not in cleaned.lower().split()


# ── format_answer ────────────────────────────────────────────────────────

def test_format_answer_no_rows_says_so_in_the_right_language():
    assert "No row" in hsn.format_answer([], language="English")
    assert "नहीं मिली" in hsn.format_answer([], language="Hindi")


def test_format_answer_never_invents_a_field_the_row_lacks(conn):
    """The gold row has no Import_Licence_Required value — the answer must
    not print a placeholder or a guessed value for it."""
    row = hsn.lookup_by_code(conn, "71141910")
    text = hsn.format_answer([row], language="English")
    assert "Import licence" not in text  # field was None, must be omitted
    assert "IS 1417 hallmarking" in text  # field that WAS present is shown


def test_format_answer_includes_both_import_and_export(conn):
    row = hsn.lookup_by_code(conn, "1011010")
    text = hsn.format_answer([row], language="English")
    assert "To import:" in text and "To export:" in text


def test_mojibake_is_repaired_on_ingest(tmp_path):
    """The source workbook has smart-punctuation mojibake in some cells
    (UTF-8 bytes re-decoded as cp1252). Confirms the fix round-trips
    correctly rather than mangling already-clean text."""
    assert hsn._fix_mojibake("Not notified â€” verify") == "Not notified — verify"
    clean = "Plain ASCII text, nothing to fix"
    assert hsn._fix_mojibake(clean) == clean
    assert hsn._fix_mojibake(None) is None


