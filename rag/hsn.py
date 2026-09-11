"""HSN import/export compliance lookup.

This is a lookup table, not prose. Almost every real question against it is
one of two exact shapes:

    "what documents do I need to import HSN 1011010?"   -> exact code match
    "what do I need to export live horses?"              -> product-name match

Running this through the PDF vector pipeline (rag/embed.py) would replace an
exact answer with a similarity-ranked guess, so it is not indexed as chunks
at all: a code lookup is a plain SQL WHERE clause, and a product lookup is
the same FTS5 keyword search the corpus already uses for BM25 — just against
a different table. See rag/marks.py for the same choice made the same way,
for the same reason: a licence/HUID format check is deterministic, so it is
not something to ask a language model to reconstruct from memory.

The source workbook has known mojibake in a handful of columns — smart
punctuation that was decoded as Windows-1252 and re-saved, e.g. "â€”" where
an em dash belongs. `_fix_mojibake` reverses it where the bytes round-trip
cleanly; anything that does not round-trip is left as-is rather than mangled
further.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from rag import config

# The columns of the source workbook, in order, mapped to the hsn_codes
# schema. Kept explicit rather than inferred from the header row so a
# reordered or renamed column in a future export fails loudly instead of
# silently loading the wrong field into the wrong place.
_COLUMNS = [
    ("HSN_CD", "hsn_cd"),
    ("Level", "level"),
    ("Chapter", "chapter"),
    ("Chapter_Title", "chapter_title"),
    ("Heading", "heading"),
    ("Product", "product"),
    ("Import_Core_Docs", "import_core_docs"),
    ("Import_BIS_IS", "import_bis_is"),
    ("Import_DGFT_Policy", "import_dgft_policy"),
    ("Import_Licence_Required", "import_licence_required"),
    ("Import_Monitoring_System", "import_monitoring_system"),
    ("Import_CoO", "import_coo"),
    ("Import_Other_NOC", "import_other_noc"),
    ("Export_Core_Docs", "export_core_docs"),
    ("Export_DGFT_Policy", "export_dgft_policy"),
    ("Export_Other_NOC", "export_other_noc"),
    ("Primary_Regulator", "primary_regulator"),
    ("Verify_Against", "verify_against"),
]

# Field labels for the plain-language answer, grouped the way a person
# actually asks: "what do I need to import" vs "what do I need to export".
_IMPORT_FIELDS = [
    ("import_core_docs", "Core documents", "मुख्य दस्तावेज़"),
    ("import_licence_required", "Import licence", "आयात लाइसेंस"),
    ("import_bis_is", "BIS / Indian Standard", "BIS / भारतीय मानक"),
    ("import_dgft_policy", "DGFT import policy", "DGFT आयात नीति"),
    ("import_coo", "Certificate of Origin", "मूल प्रमाण पत्र"),
    ("import_monitoring_system", "Import monitoring system", "आयात निगरानी प्रणाली"),
    ("import_other_noc", "Other NOC / clearance", "अन्य एनओसी / मंज़ूरी"),
]
_EXPORT_FIELDS = [
    ("export_core_docs", "Core documents", "मुख्य दस्तावेज़"),
    ("export_dgft_policy", "DGFT export policy", "DGFT निर्यात नीति"),
    ("export_other_noc", "Other NOC / clearance", "अन्य एनओसी / मंज़ूरी"),
]


def _fix_mojibake(text: str | None) -> str | None:
    if not text:
        return text
    try:
        fixed = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    # Only trust the round-trip if it actually removed the tell-tale bytes;
    # otherwise a coincidental cp1252-encodable string could be corrupted
    # further by "fixing" text that was never broken.
    return fixed if ("â" in text and "â" not in fixed) else text


@dataclass
class HsnRow:
    hsn_cd: str
    level: str
    chapter_title: str | None
    heading: str | None
    product: str
    fields: dict[str, str | None] = field(default_factory=dict)


def init_schema(conn: sqlite3.Connection) -> None:
    """hsn_codes/hsn_fts are part of the shared schema (rag/store.py); this
    just makes intent explicit at the one call site that populates them."""
    from rag import store

    store.init_schema(conn)


def ingest_matrix(conn: sqlite3.Connection, xlsx_path: Path) -> int:
    """Load the compliance matrix workbook into hsn_codes + hsn_fts.

    Replaces any existing rows: this is a reference table refreshed whole
    from a new export, not something merged incrementally.
    """
    import openpyxl

    init_schema(conn)
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    ws = wb.active

    header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    index_of = {name: i for i, name in enumerate(header)}
    missing = [src for src, _ in _COLUMNS if src not in index_of]
    if missing:
        raise ValueError(f"Workbook is missing expected column(s): {missing}")

    conn.execute("DELETE FROM hsn_codes")
    conn.execute("DELETE FROM hsn_fts")

    rows = []
    for excel_row in ws.iter_rows(min_row=2, values_only=True):
        values = {}
        for src, dest in _COLUMNS:
            v = excel_row[index_of[src]]
            if isinstance(v, str):
                v = _fix_mojibake(v.strip()) or None
            values[dest] = v
        if not values.get("hsn_cd") or not values.get("product"):
            continue
        values["hsn_cd"] = str(values["hsn_cd"]).strip()
        rows.append(values)

    cols = [dest for _, dest in _COLUMNS]
    placeholders = ",".join("?" * len(cols))
    conn.executemany(
        f"INSERT INTO hsn_codes ({','.join(cols)}) VALUES ({placeholders})",
        [tuple(r[c] for c in cols) for r in rows],
    )
    # External-content FTS5 table: populated by asking it to rebuild from
    # hsn_codes rather than by mirroring inserts, since this is a one-shot
    # bulk load rather than a live-updated table.
    conn.execute("INSERT INTO hsn_fts(hsn_fts) VALUES('rebuild')")
    conn.commit()
    return len(rows)


def _row_to_hsn(row: sqlite3.Row) -> HsnRow:
    keys = row.keys()
    return HsnRow(
        hsn_cd=row["hsn_cd"],
        level=row["level"],
        chapter_title=row["chapter_title"],
        heading=row["heading"],
        product=row["product"],
        fields={k: row[k] for k in keys if k not in ("id", "hsn_cd", "level", "chapter_title", "heading", "product")},
    )


def lookup_by_code(conn: sqlite3.Connection, code: str) -> HsnRow | None:
    """Exact match. HSN codes are numeric but often typed with leading
    zeros ("01011010"), which `int()` normalises before comparing."""
    digits = re.sub(r"\D", "", code or "")
    if not digits:
        return None
    try:
        normalised = str(int(digits))
    except ValueError:
        return None
    row = conn.execute(
        "SELECT * FROM hsn_codes WHERE hsn_cd = ? LIMIT 1", (normalised,)
    ).fetchone()
    return _row_to_hsn(row) if row else None


def search_by_product(conn: sqlite3.Connection, query: str, top_k: int = 5) -> list[HsnRow]:
    """Keyword search over product name / heading / chapter title.

    Prefers the most specific matching level (a Tariff Item over the Chapter
    it belongs to) so "documents for live horses" returns the actual line
    item rather than the whole "Live animals" chapter it is filed under.
    """
    terms = re.findall(r"[A-Za-z0-9]+", query or "")
    if not terms:
        return []
    fts_query = " OR ".join(terms)
    rows = conn.execute(
        """
        SELECT hc.* FROM hsn_fts f
        JOIN hsn_codes hc ON hc.id = f.rowid
        WHERE hsn_fts MATCH ?
        ORDER BY bm25(hsn_fts),
                 CASE hc.level
                   WHEN 'Tariff Item' THEN 0
                   WHEN '7-digit' THEN 0
                   WHEN 'Sub-heading' THEN 1
                   WHEN '5-digit' THEN 1
                   WHEN 'Heading' THEN 2
                   ELSE 3
                 END
        LIMIT ?
        """,
        (fts_query, top_k),
    ).fetchall()
    return [_row_to_hsn(r) for r in rows]


# A bare number could just as easily be an IS standard, a year, or a fee
# figure, so a number alone is not enough to trigger this path — the word
# "HSN" (or a clear synonym) has to be present too. This mirrors how
# rag/scope.py requires digits before treating "is" as a standards
# reference: one weak signal is not trusted alone.
_HSN_WORD = re.compile(r"\bhsn\b|\bhs\s*code\b|\btariff\s*(?:code|heading|item)\b", re.IGNORECASE)
_CODE_IN_TEXT = re.compile(r"\b\d{2,8}\b")


def mentions_hsn(question: str) -> bool:
    return bool(_HSN_WORD.search(question or ""))


def extract_code(question: str) -> str | None:
    """The first number in the question, once it has already been decided
    (via `mentions_hsn`) that the question is about an HSN code at all."""
    m = _CODE_IN_TEXT.search(question or "")
    return m.group(0) if m else None


def strip_trigger_words(question: str) -> str:
    """The question with "HSN"/"HS code"/"tariff code" removed, for feeding
    to the product-name search — otherwise the trigger word itself, present
    in every HSN question by definition, would out-rank the actual product
    in the keyword match."""
    return _HSN_WORD.sub(" ", question or "")


_IMPORT_WORD = re.compile(r"\bimport(?:ed|ing|er|ers)?\b", re.IGNORECASE)
_EXPORT_WORD = re.compile(r"\bexport(?:ed|ing|er|ers)?\b", re.IGNORECASE)


def detect_intent(question: str) -> str:
    """"import", "export", or "both" — which half of the row the question
    is actually asking about.

    A question that names only one direction ("what documents do I need to
    IMPORT this?") gets only that direction's fields. Naming both, or
    naming neither ("what is HSN 1011010?"), returns everything: the second
    case is a plain lookup with no stated intent, and guessing which half to
    hide would drop information the user never said they didn't want.
    """
    has_import = bool(_IMPORT_WORD.search(question or ""))
    has_export = bool(_EXPORT_WORD.search(question or ""))
    if has_import and not has_export:
        return "import"
    if has_export and not has_import:
        return "export"
    return "both"


def format_answer(rows: list[HsnRow], *, language: str = "English", intent: str = "both") -> str:
    """Plain-language answer built directly from the matrix — no model call,
    so nothing here can be paraphrased into something the row does not say.

    `intent` ("import", "export", or "both") drops the section the question
    did not ask about, rather than always printing the full row. Asking
    specifically about import documents and getting the export section back
    too is exactly the "dumps everything" behaviour this exists to avoid.
    """
    hindi = language.startswith("Hindi")
    if not rows:
        return (
            "इस उत्पाद या HSN कोड के लिए compliance matrix में कोई पंक्ति नहीं मिली। "
            "कृपया सही HSN कोड जाँचें या उत्पाद का नाम स्पष्ट करें।"
            if hindi else
            "No row in the HSN compliance matrix matched that code or product. "
            "Check the HSN code, or try naming the product differently."
        )

    parts: list[str] = []
    for row in rows:
        # The product name and HSN code are the same in either language —
        # they come from the customs tariff, not from translated prose.
        parts.append(f"HSN {row.hsn_cd} — {row.product}")
        if row.chapter_title:
            parts.append(
                f"अध्याय: {row.chapter_title}" if hindi else f"Chapter: {row.chapter_title}"
            )

        if intent in ("import", "both"):
            parts.append("")
            parts.append("आयात के लिए (Import):" if hindi else "To import:")
            for key, label_en, label_hi in _IMPORT_FIELDS:
                val = row.fields.get(key)
                if val:
                    parts.append(f"  - {label_hi if hindi else label_en}: {val}")

        if intent in ("export", "both"):
            parts.append("")
            parts.append("निर्यात के लिए (Export):" if hindi else "To export:")
            for key, label_en, label_hi in _EXPORT_FIELDS:
                val = row.fields.get(key)
                if val:
                    parts.append(f"  - {label_hi if hindi else label_en}: {val}")

        regulator = row.fields.get("primary_regulator")
        if regulator:
            parts.append("")
            parts.append(
                f"मुख्य नियामक: {regulator}" if hindi else f"Primary regulator: {regulator}"
            )
        verify = row.fields.get("verify_against")
        if verify:
            parts.append(
                f"इससे पुष्टि करें: {verify}" if hindi else f"Verify against: {verify}"
            )
        parts.append("")

    note = (
        "यह जानकारी HSN Import-Export Compliance Matrix की उस पंक्ति से ली गई है, "
        "किसी सारांश से नहीं। नियम बदल सकते हैं — फाइल करने से पहले संबंधित नियामक से पुष्टि करें।"
        if hindi else
        "This is read directly from the matching row of the HSN Import-Export "
        "Compliance Matrix, not summarised. Requirements change — confirm with "
        "the named regulator before filing."
    )
    parts.append(note)
    return "\n".join(parts).strip()
