"""Chunking.

Chunks never span a page boundary. That costs some context at page joins but
buys the thing this system actually needs: every chunk has one unambiguous
page number, so a citation points at a page a person can open and verify.
Splitting prefers clause boundaries ("(3)", "4.2", "Provided that") because
that is where BIS legal text naturally divides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rag import config
from rag.extract import ExtractedDoc, extract_identifiers

# Zero-width characters appear *inside* words in some BIS PDFs
# ("Wax​seal​should") and break tokenisation, so they are deleted.
_ZERO_WIDTH = re.compile("[​‌‍﻿]")
# A non-breaking space is a real space and must become one rather than
# vanish; deleting it would fuse two words into one unsearchable token.
_NBSP = re.compile("[   ]")

# Start of a numbered clause / sub-clause / proviso.
_CLAUSE_START = re.compile(
    r"(?=^\s*(?:\(\s*[0-9ivxa-z]{1,4}\s*\)|\d{1,2}\.\d{0,2}\s|Provided\b|PROVIDED\b))",
    re.MULTILINE,
)


@dataclass
class Chunk:
    doc_sha: str
    relpath: str
    page_number: int
    ordinal: int
    text: str
    is_numbers: str
    gazette_refs: str


def normalise(text: str) -> str:
    text = _ZERO_WIDTH.sub("", text)
    text = _NBSP.sub(" ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_units(text: str) -> list[str]:
    """Break a page into the smallest units we are willing to keep together."""
    units = [u.strip() for u in _CLAUSE_START.split(text) if u.strip()]
    out: list[str] = []
    for unit in units:
        if len(unit) <= config.CHUNK_TARGET_CHARS:
            out.append(unit)
            continue
        # Still too long: fall back to sentence boundaries, then hard wrap.
        parts = re.split(r"(?<=[.;:])\s+(?=[A-Z(ऀ-ॿ])", unit)
        buf = ""
        for part in parts:
            if len(part) > config.CHUNK_TARGET_CHARS:
                if buf:
                    out.append(buf.strip())
                    buf = ""
                for i in range(0, len(part), config.CHUNK_TARGET_CHARS):
                    out.append(part[i : i + config.CHUNK_TARGET_CHARS].strip())
            elif len(buf) + len(part) + 1 > config.CHUNK_TARGET_CHARS:
                out.append(buf.strip())
                buf = part
            else:
                buf = f"{buf} {part}".strip()
        if buf:
            out.append(buf.strip())
    return [u for u in out if u]


def chunk_document(doc: ExtractedDoc) -> list[Chunk]:
    chunks: list[Chunk] = []
    ordinal = 0

    for page in doc.usable_pages:
        text = normalise(page.text)
        if len(text) < config.CHUNK_MIN_CHARS:
            continue

        buf = ""
        for unit in _split_units(text):
            if buf and len(buf) + len(unit) + 1 > config.CHUNK_TARGET_CHARS:
                chunks.append(_make(doc, page.page_number, ordinal, buf))
                ordinal += 1
                tail = buf[-config.CHUNK_OVERLAP_CHARS :]
                # Resume from a word boundary so the overlap is readable.
                cut = tail.find(" ")
                buf = (tail[cut + 1 :] if cut != -1 else "") + " " + unit
            else:
                buf = f"{buf} {unit}".strip()

        if len(buf.strip()) >= config.CHUNK_MIN_CHARS:
            chunks.append(_make(doc, page.page_number, ordinal, buf))
            ordinal += 1
        elif buf.strip() and chunks and chunks[-1].page_number == page.page_number:
            # Don't strand a short tail: fold it into the previous chunk.
            chunks[-1].text = f"{chunks[-1].text} {buf.strip()}"

    return chunks


def _make(doc: ExtractedDoc, page_number: int, ordinal: int, text: str) -> Chunk:
    text = text.strip()
    is_nums, gaz = extract_identifiers(text)
    return Chunk(
        doc_sha=doc.sha256,
        relpath=doc.relpath,
        page_number=page_number,
        ordinal=ordinal,
        text=text,
        is_numbers=" | ".join(is_nums),
        gazette_refs=" | ".join(gaz),
    )
