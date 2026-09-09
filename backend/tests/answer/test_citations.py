"""extract_citation_markers / validate_citations: valid markers resolve to
real chunk metadata, out-of-range markers (a model citing a source number
that doesn't exist) are flagged rather than silently dropped or crashing."""

from __future__ import annotations

import uuid

from app.answer.citations import extract_citation_markers, validate_citations
from app.retrieval.models import RetrievedChunk


def _chunk(is_number: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        text_content="text",
        is_number=is_number,
        section_path=None,
        clause_number="4.2.1",
        page_number=None,
        context_header=None,
        document_title=f"{is_number} title",
        document_source_url="https://example.com",
    )


def test_extract_citation_markers_in_order_with_duplicates() -> None:
    assert extract_citation_markers("A [1] and B [2] then [1] again") == [1, 2, 1]


def test_extract_citation_markers_none_present() -> None:
    assert extract_citation_markers("no citations here") == []


def test_validate_citations_resolves_valid_markers() -> None:
    chunks = [_chunk("IS 1"), _chunk("IS 2")]
    result = validate_citations("Claim one [1]. Claim two [2].", chunks)

    assert [c.marker for c in result.citations] == [1, 2]
    assert result.citations[0].is_number == "IS 1"
    assert result.citations[1].is_number == "IS 2"
    assert result.invalid_markers == []
    assert result.has_any_citation is True


def test_validate_citations_flags_out_of_range_marker() -> None:
    chunks = [_chunk("IS 1")]
    result = validate_citations("Made up source [5].", chunks)

    assert result.citations == []
    assert result.invalid_markers == [5]
    assert result.has_any_citation is False


def test_validate_citations_no_citations_in_text() -> None:
    result = validate_citations("Plain answer, no brackets.", [_chunk("IS 1")])
    assert result.has_any_citation is False
    assert result.citations == []
    assert result.invalid_markers == []


def test_validate_citations_deduplicates_repeated_marker() -> None:
    chunks = [_chunk("IS 1")]
    result = validate_citations("[1] and again [1]", chunks)
    assert len(result.citations) == 1
    assert result.cited_chunk_indices == {1}
