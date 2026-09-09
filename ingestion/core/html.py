"""Minimal shared HTML helpers used by every Step-2 crawler's `parse()`.

Deliberately generic (title tag + a regex for IS-number-shaped tokens)
rather than per-site CSS selectors: this sandbox has no live network access
to BIS's site to inspect real markup and hand-tune selectors against it
(flagged as a design decision — see docs/DECISIONS.md). Runs correctly
against any HTML and extracts a real title and any IS numbers present, which
is enough to prove the fetch → parse → provenance pipeline end-to-end; Step
3's clause-aware chunking is where source-specific structure (tables,
headings, clause numbers) gets parsed properly, once selectors can be
validated against a live fetch on a machine with real network access.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

# Matches "IS 15111", "IS15111", "IS 15111 (Part 2)", "IS 15111:2019" etc.
IS_NUMBER_PATTERN = re.compile(
    r"\bIS\s?(\d{3,6})(?:\s*\(Part\s*\d+\))?(?::\d{4})?\b", re.IGNORECASE
)


def extract_title(html: bytes) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        return str(soup.title.string).strip()
    h1 = soup.find("h1")
    if h1:
        return str(h1.get_text(strip=True))
    return None


def extract_first_is_number(html: bytes) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    match = IS_NUMBER_PATTERN.search(text)
    if not match:
        return None
    return f"IS {match.group(1)}"
