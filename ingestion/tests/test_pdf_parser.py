"""PDF parsing extracts per-page paragraph blocks with correct page
numbers. Uses fpdf2 to generate a real, minimal PDF fixture with actual
text — not a hand-built byte string — so this exercises real PDF text
extraction, not just that pypdf doesn't crash on garbage bytes."""

from __future__ import annotations

from fpdf import FPDF

from ingestion.parsing.blocks import BlockType
from ingestion.parsing.pdf_parser import parse_pdf


def _build_pdf(pages: list[str]) -> bytes:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for page_text in pages:
        pdf.add_page()
        pdf.multi_cell(0, 10, page_text)
    return bytes(pdf.output())


def test_extracts_text_per_page_with_page_numbers() -> None:
    pdf_bytes = _build_pdf(["First page content.", "Second page content."])

    blocks = parse_pdf(pdf_bytes)

    assert all(b.type is BlockType.PARAGRAPH for b in blocks)
    page_numbers = {b.page_number for b in blocks}
    assert page_numbers == {1, 2}
    joined = " ".join(b.text for b in blocks)
    assert "First page content" in joined
    assert "Second page content" in joined


def test_empty_pdf_produces_no_blocks() -> None:
    pdf_bytes = _build_pdf([])

    blocks = parse_pdf(pdf_bytes)

    assert blocks == []
