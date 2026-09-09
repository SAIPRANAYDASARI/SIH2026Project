"""PDF → Block list.

QCO notifications and some circulars are published as PDF rather than HTML.
This extracts per-page text via `pypdf` and splits each page on blank lines
into paragraph blocks, tagged with their page number.

Limitation (flagged, not hidden): unlike the HTML parser, this does not
attempt table detection/markdown conversion — PDF table extraction needs
layout analysis (e.g. `pdfplumber`) that's a meaningfully bigger dependency
and failure surface than a hackathon-timeline Step 3 can validate without a
real corpus of QCO PDFs to test against. A PDF's tabular data currently
lands as plain paragraph text. Revisit once Step 2's QCO crawler has pulled
real files to test table extraction against — see docs/DECISIONS.md.
"""

from __future__ import annotations

import io

from pypdf import PdfReader

from ingestion.parsing.blocks import Block, BlockType


def parse_pdf(content: bytes) -> list[Block]:
    reader = PdfReader(io.BytesIO(content))
    blocks: list[Block] = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        for paragraph in _split_paragraphs(text):
            blocks.append(Block(BlockType.PARAGRAPH, paragraph, page_number=page_number))

    return blocks


def _split_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n")]
    return [p for p in paragraphs if p]
