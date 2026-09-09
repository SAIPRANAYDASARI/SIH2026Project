"""Product compliance timelines built from the Quality Control Order corpus.

A Quality Control Order is rarely a single document. Acetone is governed by an
original 2020 order, an amendment to it, and two separate extensions; air
conditioners span five documents. 77 of the 92 QCO files in this corpus are
amendments or extensions rather than principal orders.

That is a genuine problem for a manufacturer: the obligation that actually
binds them today is the sum of a chain of gazette notifications, and nothing
on bis.gov.in assembles that chain for them. The corpus's own metadata gave up
on it, recording enforcement dates as
"NOT_DETERMINED_requires_reading_all_amendments_in_order".

This module assembles the chain. It reads the gazette notification number and
date out of each order's own text — not out of the filename, which carries a
usable year in only half the files — groups the orders by product, and puts
them in date order.

What it will not do is invent the missing pieces. A date that is not stated in
a document is reported as unknown, and the answer says which documents were
consulted so a person can check the chain themselves. An incomplete timeline
that is honest about its gaps is useful; a complete-looking one that guessed a
compliance deadline is dangerous.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from rag import store

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

# The dateline directly under the ministry name — "New Delhi, the 11th
# February, 2025" — is the order's OWN date. Anchoring on "New Delhi" matters:
# an amendment also quotes the date of the order it amends ("...vide S.O.
# 4354(E) dated the 5th December, 2019"), and reading that instead puts a
# 2025 amendment on the timeline six years early.
_EN_MONTHS = ("january|february|march|april|may|june|july|august|september|"
              "october|november|december")
# Gazette masthead: "NEW DELHI, TUESDAY, FEBRUARY 11, 2025/MAGHA 22, 1946".
# This is the issue's publication date and the most reliable line in the file.
MASTHEAD_EN = re.compile(
    rf"new\s+delhi\s*,\s*(?:\w+\s*,\s*)?({_EN_MONTHS})\s+(\d{{1,2}})\s*,\s*((?:19|20)\d{{2}})",
    re.IGNORECASE,
)
# Order dateline: "New Delhi, the 11th February, 2025".
DATELINE_EN = re.compile(
    r"new\s+delhi\s*,?\s*(?:the\s+)?(\d{1,2})\s*(?:st|nd|rd|th)?\s+"
    rf"({_EN_MONTHS})\s*,?\s*((?:19|20)\d{{2}})",
    re.IGNORECASE,
)

# Every gazette leads with the Hindi page, so the Hindi dateline is usually
# the first date in the file: "नई दिल्ली, 11 फरवरी, 2025". Month spellings are
# matched loosely because the Devanagari in these PDFs is often mangled
# (see rag/quality.py) — "दिसम्बर" can extract as "ददसम् बर".
_HI_MONTHS = {
    "जनवर": 1, "फरवर": 2, "मार": 3, "अप्रैल": 4, "अप्रै": 4, "मई": 5,
    "जून": 6, "िून": 6, "जुलाई": 7, "िुलाई": 7, "अगस": 8,
    "जसतम": 9, "सितम": 9, "जसतंबर": 9, "अक्ट": 10, "अक्ि": 10, "अक् ि": 10,
    "नवम": 11, "नवंबर": 11, "ददसम": 12, "दिसम": 12, "ददसंबर": 12, "दिसंबर": 12,
}
# "नई ददल्ली, 11 फरवरी, 2025". Anchored on "ल्ली" rather than the full "दिल्ली"
# because the leading syllable is frequently mangled ("ददल्ली").
DATELINE_HI = re.compile(
    r"ल्ली\s*,?\s*(\d{1,2})\s+([^\s,0-9]{2,14})\s*,?\s*((?:19|20)\d{2})"
)
# Hindi masthead form: "नई ददल्ली, ंंगलवार, जसतम् बर 15, 2020" (weekday, then
# month, then day).
MASTHEAD_HI = re.compile(
    r"ल्ली\s*,?\s*[^\s,0-9]{2,14}\s*,\s*([^\s,0-9]{2,14}(?:\s[^\s,0-9]{1,6})?)\s+(\d{1,2})\s*,\s*((?:19|20)\d{2})"
)

# There is deliberately NO loose "any date in the text" fallback. Orders are
# full of other dates — the enforcement deadline, the date of the order being
# amended — and picking one of those put a 2025 amendment on the timeline at
# 2027. On a compliance timeline a wrong date is worse than no date, so an
# unrecognised dateline stays unknown.
GAZETTE_NUMBER = re.compile(r"\b(?:S\.?\s?O\.?|G\.?S\.?R\.?)\s*\.?\s*(\d{1,5})\s*\(\s*E\s*\)", re.IGNORECASE)
YEAR_IN_NAME = re.compile(r"(?:19|20)\d{2}")

# Boilerplate stripped from a filename to leave the product behind.
_NOISE = re.compile(
    r"\b(quality\s*control|qco|order|orders|amendment|amendments|amended|extension|"
    r"extensions|notification|gazette|final|draft|compressed|dup\d*|copy|new|revised|"
    r"dated|for|of|the|and|in|its|related|various)\b",
    re.IGNORECASE,
)


# Leading words that survive filename cleaning but describe the notification
# rather than the goods it regulates.
_NOT_PRODUCTS = {
    "date", "dates", "enforcement", "implementation", "list", "corrigendum",
    "notification", "misc", "miscellaneous", "chemicals", "chemical",
    "products", "product", "goods", "items", "annexure", "schedule",
}


class OrderKind(str):
    ORIGINAL = "original"
    AMENDMENT = "amendment"
    EXTENSION = "extension"
    UNKNOWN = "unknown"


@dataclass
class OrderDoc:
    """One gazette order, with everything we could establish about it."""

    doc_sha: str
    relpath: str
    filename: str
    title: str
    kind: str
    gazette_numbers: list[str] = field(default_factory=list)
    notified_on: date | None = None
    date_source: str = "not stated in document"
    is_numbers: list[str] = field(default_factory=list)
    first_page: int = 1

    @property
    def date_label(self) -> str:
        return self.notified_on.strftime("%d %b %Y") if self.notified_on else "date not stated"

    @property
    def sort_key(self) -> tuple:
        # Undated documents sort last rather than pretending to a position.
        return (0, self.notified_on) if self.notified_on else (1, date.max)


@dataclass
class ProductTimeline:
    product: str
    orders: list[OrderDoc]

    @property
    def standards(self) -> list[str]:
        seen: list[str] = []
        for o in self.orders:
            for n in o.is_numbers:
                if n not in seen:
                    seen.append(n)
        return seen

    @property
    def latest(self) -> OrderDoc | None:
        dated = [o for o in self.orders if o.notified_on]
        return max(dated, key=lambda o: o.notified_on) if dated else None

    @property
    def undated_count(self) -> int:
        return sum(1 for o in self.orders if not o.notified_on)

    @property
    def amendments(self) -> int:
        return sum(1 for o in self.orders if o.kind in (OrderKind.AMENDMENT, OrderKind.EXTENSION))


def classify(filename: str, text: str) -> str:
    name = filename.lower()
    if "extension" in name or "extend" in name:
        return OrderKind.EXTENSION
    if "amend" in name:
        return OrderKind.AMENDMENT
    head = text[:3000].lower()
    if "further to amend" in head or "amendment" in head:
        return OrderKind.AMENDMENT
    if "quality control" in name or "qco" in name or "order" in name:
        return OrderKind.ORIGINAL
    return OrderKind.UNKNOWN


def _build(day: int, month: int, year: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _hindi_month(word: str) -> int | None:
    for stem, num in _HI_MONTHS.items():
        if word.startswith(stem) or stem in word:
            return num
    return None


def parse_notification_date(text: str) -> tuple[date | None, str]:
    """The order's OWN notification date.

    Tried in descending order of confidence. Filenames are never used: only
    half carry a year, and a filename year can disagree with the notification
    inside. A wrong date on a compliance timeline is worse than no date, so
    anything unrecognised is reported as unknown rather than guessed.
    """
    m = MASTHEAD_EN.search(text)          # "NEW DELHI, TUESDAY, FEBRUARY 11, 2025"
    if m:
        d = _build(int(m.group(2)), MONTHS[m.group(1).lower()], int(m.group(3)))
        if d:
            return d, "gazette masthead (English)"

    m = DATELINE_EN.search(text)          # "New Delhi, the 11th February, 2025"
    if m:
        d = _build(int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3)))
        if d:
            return d, "order dateline (English)"

    m = DATELINE_HI.search(text)          # "नई दिल्ली, 11 फरवरी, 2025"
    if m:
        month = _hindi_month(m.group(2))
        if month:
            d = _build(int(m.group(1)), month, int(m.group(3)))
            if d:
                return d, "order dateline (Hindi)"

    m = MASTHEAD_HI.search(text)          # "नई दिल्ली, मंगलवार, सितम्बर 15, 2020"
    if m:
        month = _hindi_month(m.group(1))
        if month:
            d = _build(int(m.group(2)), month, int(m.group(3)))
            if d:
                return d, "gazette masthead (Hindi)"

    return None, "not stated in document"


def product_name(filename: str) -> str:
    """Best-effort product name from a filename, for grouping only.

    Deliberately conservative: this labels a group, it is never presented as
    the legal scope of an order. The order documents themselves are shown
    alongside so the real scope can be read.
    """
    stem = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
    stem = re.sub(r"__dup\d*__?", " ", stem)
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = YEAR_IN_NAME.sub(" ", stem)
    stem = _NOISE.sub(" ", stem)
    stem = re.sub(r"\b\d+\b", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" -,.")
    return stem.title()


def load_orders(conn=None) -> list[OrderDoc]:
    own = conn is None
    conn = conn or store.connect()
    try:
        rows = conn.execute(
            """SELECT d.sha256, d.relpath, d.filename, d.title
               FROM documents d
               WHERE d.category = '03_QCO' OR d.relpath LIKE '%qco%'
               ORDER BY d.filename"""
        ).fetchall()

        orders: list[OrderDoc] = []
        for r in rows:
            # Wide enough to reach the English half of a bilingual gazette,
            # which follows the Hindi pages and carries the IS numbers.
            chunks = conn.execute(
                "SELECT text, is_numbers, gazette_refs, page_number FROM chunks "
                "WHERE doc_sha=? ORDER BY page_number, ordinal LIMIT 40",
                (r["sha256"],),
            ).fetchall()
            if not chunks:
                continue
            text = "\n".join(c["text"] for c in chunks)

            gazettes: list[str] = []
            for c in chunks:
                for g in (c["gazette_refs"] or "").split("|"):
                    g = g.strip()
                    if g and g not in gazettes:
                        gazettes.append(g)
            if not gazettes:
                for m in GAZETTE_NUMBER.finditer(text):
                    g = f"S.O. {m.group(1)}(E)"
                    if g not in gazettes:
                        gazettes.append(g)

            is_nums: list[str] = []
            for c in chunks:
                for n in (c["is_numbers"] or "").split("|"):
                    n = n.strip()
                    if n and n not in is_nums:
                        is_nums.append(n)

            notified, source = parse_notification_date(text)
            orders.append(
                OrderDoc(
                    doc_sha=r["sha256"],
                    relpath=r["relpath"],
                    filename=r["filename"],
                    title=r["title"],
                    kind=classify(r["filename"], text),
                    gazette_numbers=gazettes[:4],
                    notified_on=notified,
                    date_source=source,
                    is_numbers=is_nums[:6],
                    first_page=chunks[0]["page_number"],
                )
            )
        return orders
    finally:
        if own:
            conn.close()


def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"\W+", name.lower()) if len(t) > 3}


def timeline_for(query: str, conn=None, *, limit: int = 25) -> ProductTimeline:
    """Every order whose product name overlaps the query, in date order."""
    orders = load_orders(conn)
    wanted = _tokens(query)
    if not wanted:
        return ProductTimeline(product=query.strip(), orders=[])

    scored: list[tuple[int, OrderDoc]] = []
    for o in orders:
        name = product_name(o.filename)
        haystack = _tokens(name) | _tokens(o.title)
        overlap = len(wanted & haystack)
        # Substring catches "air conditioner" inside a long compound filename.
        if not overlap and query.strip().lower() in o.filename.lower().replace("-", " "):
            overlap = 1
        if overlap:
            scored.append((overlap, o))

    scored.sort(key=lambda p: (-p[0], p[1].sort_key))
    chosen = [o for _, o in scored[:limit]]
    chosen.sort(key=lambda o: o.sort_key)
    return ProductTimeline(product=query.strip().title(), orders=chosen)


def known_products(conn=None, *, min_orders: int = 2, limit: int = 40) -> list[tuple[str, int]]:
    """Products with more than one order — the ones with a chain worth showing."""
    orders = load_orders(conn)
    groups: dict[str, int] = {}
    for o in orders:
        name = product_name(o.filename)
        if not name or len(name) < 4:
            continue
        # Group on the leading words, so "Acetone Extension 2" joins "Acetone".
        key = " ".join(name.split()[:2])
        # Filenames like "Date-of-Implementation-..." leave administrative
        # words behind after cleaning; they name a notification, not a product.
        if key.split()[0].lower() in _NOT_PRODUCTS:
            continue
        groups[key] = groups.get(key, 0) + 1
    ranked = sorted(
        ((k, v) for k, v in groups.items() if v >= min_orders),
        key=lambda kv: (-kv[1], kv[0]),
    )
    return ranked[:limit]
