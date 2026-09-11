"""HSN import/export compliance lookup.

The matrix is a lookup table, not prose: these tests exist to prove that a
code lookup returns the exact row (no similarity ranking, no LLM guessing),
that leading zeros and mojibake don't silently break it, and that a
compliance question routes to the matrix rather than into the BIS PDF
pipeline or a refusal.
"""

import sqlite3

import pytest

from rag import answer as answer_mod
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


# ── detect_intent ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("question,expected", [
    ("what import documents do I need for HSN 1011010?", "import"),
    ("documents required to import this HSN code", "import"),
    ("what export documents for HSN 71141910?", "export"),
    ("documents needed to export this HSN code", "export"),
    ("what is HSN 1011010?", "both"),
    ("what documents for HSN 1011010, both import and export?", "both"),
    ("importers and exporters of HSN 1011010 need what?", "both"),
])
def test_detect_intent(question, expected):
    assert hsn.detect_intent(question) == expected


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


def test_import_intent_omits_the_export_section(conn):
    """Asking specifically about import documents must not also dump the
    export section — that dumping-everything behaviour is the exact
    complaint this filtering exists to fix."""
    row = hsn.lookup_by_code(conn, "1011010")
    text = hsn.format_answer([row], language="English", intent="import")
    assert "To import:" in text
    assert "Bill of Entry" in text          # an import field
    assert "To export:" not in text
    assert "Shipping Bill" not in text      # an export-only field


def test_export_intent_omits_the_import_section(conn):
    row = hsn.lookup_by_code(conn, "1011010")
    text = hsn.format_answer([row], language="English", intent="export")
    assert "To export:" in text
    assert "Shipping Bill" in text          # an export field
    assert "To import:" not in text
    assert "Bill of Entry" not in text      # an import-only field


def test_both_intent_is_the_full_row(conn):
    row = hsn.lookup_by_code(conn, "1011010")
    text = hsn.format_answer([row], language="English", intent="both")
    assert "To import:" in text and "To export:" in text


def test_hindi_import_intent_also_omits_export_section(conn):
    row = hsn.lookup_by_code(conn, "1011010")
    text = hsn.format_answer([row], language="Hindi", intent="import")
    assert "आयात के लिए" in text
    assert "निर्यात के लिए" not in text


def test_mojibake_is_repaired_on_ingest(tmp_path):
    """The source workbook has smart-punctuation mojibake in some cells
    (UTF-8 bytes re-decoded as cp1252). Confirms the fix round-trips
    correctly rather than mangling already-clean text."""
    assert hsn._fix_mojibake("Not notified â€” verify") == "Not notified — verify"
    clean = "Plain ASCII text, nothing to fix"
    assert hsn._fix_mojibake(clean) == clean
    assert hsn._fix_mojibake(None) is None


# ── wiring into answer_question ──────────────────────────────────────────

def test_hsn_question_short_circuits_before_the_scope_gate(monkeypatch, conn):
    """An HSN question must never hit the generic BIS scope gate — its
    vocabulary ("HSN", "tariff") is not in scope.py's domain list, so
    routing it there would produce a wrong refusal instead of an answer."""
    monkeypatch.setattr(answer_mod.store, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(answer_mod.scope, "check_scope",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("scope gate must not run for HSN questions")))

    result = answer_mod.answer_question("what documents for HSN 1011010?", language="en")
    assert result.grounded is True
    assert "LIVE HORSES" in result.text


def test_import_only_question_gets_import_only_answer_end_to_end(monkeypatch, conn):
    """The behaviour actually reported as the problem: asking about import
    documents for an HSN code must not also return the export section."""
    monkeypatch.setattr(answer_mod.store, "connect", lambda *a, **k: conn)

    result = answer_mod.answer_question(
        "what import documents do I need for HSN 1011010?", language="en"
    )
    assert "To import:" in result.text
    assert "To export:" not in result.text
    assert "Shipping Bill" not in result.text
    assert result.model == "hsn matrix lookup (no model call)"


def test_hsn_question_with_no_match_still_short_circuits(monkeypatch, conn):
    """A "not found" HSN answer must not fall through to the BIS pipeline —
    that would risk the general-knowledge path inventing compliance
    requirements for a code that is not actually in the matrix."""
    monkeypatch.setattr(answer_mod.store, "connect", lambda *a, **k: conn)

    def boom(*a, **k):
        raise AssertionError("must not reach the generic search pipeline")
    monkeypatch.setattr(answer_mod, "search", boom)

    result = answer_mod.answer_question("what is HSN 99999999?", language="en")
    assert result.grounded is False
    assert result.refused is False
    assert "No row" in result.text


def test_non_hsn_question_is_unaffected(monkeypatch):
    """A normal BIS question must not be intercepted just because the HSN
    hook exists in the pipeline."""
    called = {}
    def fake_search(*a, **k):
        called["yes"] = True
        return []
    monkeypatch.setattr(answer_mod, "search", fake_search)

    answer_mod.answer_question("what is IS 9873?", language="en")
    assert called.get("yes"), "generic search must still run for non-HSN questions"


def test_hsn_takes_no_llm_budget(monkeypatch, conn):
    """The whole point of a deterministic lookup is that it costs nothing —
    an HSN question must never touch the LLM client."""
    monkeypatch.setattr(answer_mod.store, "connect", lambda *a, **k: conn)
    def boom(*a, **k):
        raise AssertionError("HSN lookup must not call the LLM")
    monkeypatch.setattr(answer_mod.llm, "chat", boom)

    answer_mod.answer_question("HSN 1011010 import documents", language="en")
