"""PDF text extraction with provenance and a quality gate.

PyMuPDF is used rather than pypdf because a meaningful slice of this corpus
(the 2018 hallmarking gazettes in particular) makes pypdf emit literal
"/uni0909" escapes where a glyph has no Unicode mapping — measured at 2,880
such escapes on a single page. PyMuPDF resolves those to real characters and
drops the escape artifacts to zero on the same pages.

Every page carries the document it came from and its 1-based page number, so
an answer can cite a location a person can actually open and check.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from rag import config
from rag.quality import clean_page

# Identifiers worth pulling out for exact lookup: "IS 17440 : 2020",
# "IS/IEC 62368-1", "IS 1867:2023", "S.O. 3927(E)".
#
# Case-sensitive on purpose. Matching case-insensitively turns ordinary prose
# such as "the fee is 500 rupees" into a citation of the non-existent standard
# "IS 500", which would then be indexed as a real identifier and boosted by
# exact-match lookup. Standards are always written uppercase in this corpus.
IS_NUMBER = re.compile(
    r"\bIS(?:\s*/\s*(?:IEC|ISO|EN))?\s*:?\s*\d{3,5}"
    r"(?:\s*-\s*\d{1,2}(?!\d))?"  # part suffix as in IS/IEC 62368-1
    r"(?:\s*\(?\s*(?:Part|Pt\.?)\s*\d+\s*\)?)?"
    r"(?:\s*[:\-]\s*(?:19|20)\d{2})?"  # edition year
)
GAZETTE_NO = re.compile(r"\b(?:S\.?\s?O\.?|G\.?S\.?R\.?)\s*\.?\s*\d{1,5}\s*\(\s*E\s*\)", re.IGNORECASE)


@dataclass
class PageText:
    page_number: int
    text: str
    kept_lines: int
    dropped_lines: int
    drop_ratio: float
    status: str  # "ok" | "scanned" | "mostly_corrupt" | "empty"
    scripts: dict[str, int] = field(default_factory=dict)
    dropped_reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class ExtractedDoc:
    path: Path
    relpath: str
    category: str
    subcategory: str
    filename: str
    sha256: str
    size_bytes: int
    page_count: int
    pages: list[PageText]
    error: str | None = None

    @property
    def usable_pages(self) -> list[PageText]:
        return [p for p in self.pages if p.status == "ok"]

    @property
    def title(self) -> str:
        """A human-readable title derived from the filename.

        Filenames in this corpus are descriptive ("Air-Conditioner-and-its-
        related-parts.pdf"), so this is honest metadata rather than a guess at
        the document's formal legal title, which is not asserted anywhere.
        """
        stem = self.path.stem
        stem = re.sub(r"__dup\d*__?", " ", stem)
        stem = re.sub(r"[_\-]+", " ", stem)
        return re.sub(r"\s+", " ", stem).strip()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def iter_pdfs(root: Path = config.CORPUS_ROOT):
    for path in sorted(root.rglob("*.pdf")):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] in config.EXCLUDED_DIRS:
            continue
        yield path


def extract_identifiers(text: str) -> tuple[list[str], list[str]]:
    is_nums = []
    for m in IS_NUMBER.findall(text):
        norm = re.sub(r"\s+", " ", m).strip().upper().rstrip(":-").strip()
        if norm not in is_nums:
            is_nums.append(norm)
    gaz = []
    for m in GAZETTE_NO.findall(text):
        norm = re.sub(r"\s+", " ", m).strip().upper()
        if norm not in gaz:
            gaz.append(norm)
    return is_nums, gaz


def extract_pdf(path: Path, root: Path = config.CORPUS_ROOT) -> ExtractedDoc:
    rel = path.relative_to(root)
    parts = rel.parts
    doc = ExtractedDoc(
        path=path,
        relpath=str(rel),
        category=parts[0] if parts else "",
        subcategory=parts[1] if len(parts) > 2 else "",
        filename=path.name,
        sha256=sha256_of(path),
        size_bytes=path.stat().st_size,
        page_count=0,
        pages=[],
    )

    try:
        pdf = pymupdf.open(path)
    except Exception as exc:  # corrupt/encrypted file — record, do not crash
        doc.error = f"{type(exc).__name__}: {exc}"
        return doc

    try:
        doc.page_count = pdf.page_count
        for index in range(pdf.page_count):
            try:
                raw = pdf[index].get_text("text") or ""
            except Exception as exc:
                doc.pages.append(
                    PageText(index + 1, "", 0, 0, 1.0, f"error: {type(exc).__name__}")
                )
                continue

            if len(raw.strip()) < config.MIN_PAGE_CHARS:
                # No extractable text layer: a scanned image page. Recorded so
                # the coverage report can show what OCR would add, never
                # guessed at.
                doc.pages.append(
                    PageText(index + 1, "", 0, 0, 1.0, "scanned" if raw.strip() == "" else "empty")
                )
                continue

            pq = clean_page(raw)
            status = "ok"
            if pq.drop_ratio > config.MAX_PAGE_DROP_RATIO:
                status = "mostly_corrupt"
            elif len(pq.kept_text.strip()) < config.MIN_PAGE_CHARS:
                status = "empty"

            doc.pages.append(
                PageText(
                    page_number=index + 1,
                    text=pq.kept_text if status == "ok" else "",
                    kept_lines=pq.kept_lines,
                    dropped_lines=pq.dropped_lines,
                    drop_ratio=pq.drop_ratio,
                    status=status,
                    scripts=pq.scripts,
                    dropped_reasons=pq.dropped_reasons,
                )
            )
    finally:
        pdf.close()

    return doc
