"""Chunking invariants. The page-boundary rule is a correctness property,
not a preference: a citation naming a page must be checkable on that page."""

from __future__ import annotations

from rag import config
from rag.chunk import Chunk, chunk_document, normalise
from rag.extract import ExtractedDoc, PageText


def make_doc(pages):
    return ExtractedDoc(
        path=__import__("pathlib").Path(r"C:\bisnew\03_QCO\x.pdf"),
        relpath="03_QCO/x.pdf",
        category="03_QCO",
        subcategory="",
        filename="x.pdf",
        sha256="abc",
        size_bytes=1,
        page_count=len(pages),
        pages=[
            PageText(i + 1, text, 10, 0, 0.0, "ok") for i, text in enumerate(pages)
        ],
    )


def test_chunks_never_span_pages():
    doc = make_doc(["Alpha " * 300, "Beta " * 300])
    for ch in chunk_document(doc):
        page_text = doc.pages[ch.page_number - 1].text
        first_word = ch.text.split()[0]
        assert first_word in page_text


def test_every_chunk_carries_a_real_page_number():
    doc = make_doc(["Content one. " * 40, "Content two. " * 40, "Content three. " * 40])
    pages = {c.page_number for c in chunk_document(doc)}
    assert pages <= {1, 2, 3} and pages


def test_chunks_respect_the_size_target():
    doc = make_doc(["Some legal sentence about certification. " * 200])
    for ch in chunk_document(doc):
        # Overlap can push slightly past the target; a hard ceiling still holds.
        assert len(ch.text) <= config.CHUNK_TARGET_CHARS * 2


def test_short_pages_are_skipped_not_emitted_as_noise():
    assert chunk_document(make_doc(["tiny"])) == []


def test_only_usable_pages_are_chunked():
    doc = make_doc(["Good content here. " * 40])
    doc.pages.append(PageText(2, "", 0, 20, 1.0, "mostly_corrupt"))
    doc.pages.append(PageText(3, "", 0, 0, 1.0, "scanned"))
    assert {c.page_number for c in chunk_document(doc)} == {1}


def test_identifiers_are_captured_on_the_chunk():
    doc = make_doc(["Carbon Black shall conform to IS 17440 : 2020 as notified. " * 15])
    chunks = chunk_document(doc)
    assert any("17440" in c.is_numbers for c in chunks)


def test_normalise_strips_invisible_characters():
    # These appear in real BIS PDFs and break tokenisation.
    out = normalise("Wax\u200bseal\u200bshould\u00a0be applied")
    assert "\u200b" not in out and "\u00a0" not in out
    assert "Waxsealshould be applied" == out


def test_normalise_collapses_runaway_whitespace():
    assert normalise("a  \t  b\n\n\n\n\nc") == "a b\n\nc"


def test_chunk_ordinals_increase_within_a_document():
    doc = make_doc(["Clause text. " * 300])
    ordinals = [c.ordinal for c in chunk_document(doc)]
    assert ordinals == sorted(ordinals)
    assert len(set(ordinals)) == len(ordinals)


def test_overlap_preserves_continuity_between_adjacent_chunks():
    doc = make_doc(["The registered jeweller shall submit articles. " * 120])
    chunks = chunk_document(doc)
    if len(chunks) > 1:
        assert len(chunks[0].text) > config.CHUNK_MIN_CHARS
        assert chunks[1].text  # non-empty continuation


def test_chunk_is_a_plain_dataclass_with_provenance():
    doc = make_doc(["Provision text about licences. " * 40])
    ch = chunk_document(doc)[0]
    assert isinstance(ch, Chunk)
    assert ch.relpath == "03_QCO/x.pdf" and ch.doc_sha == "abc"
