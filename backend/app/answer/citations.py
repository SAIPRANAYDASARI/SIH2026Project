"""Parses the `[1]`, `[2][3]`-style citation markers the prompt asks the
model to produce (see `app.answer.prompts`) and maps them back to the
actual retrieved chunks, so the frontend citation panel (Step 7) always
points at a real, indexed source rather than trusting the model's prose.

This is the "citation validator" named in the brief's Step 5 scope. It
does two jobs: resolve valid markers to real chunk metadata, and flag
markers the model invented (out-of-range numbers) — a real failure mode of
numbered-citation prompting, especially on smaller/free-tier hosted models,
which is exactly what this system is likely to be run against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.retrieval.models import RetrievedChunk

_CITATION_PATTERN = re.compile(r"\[(\d+)\]")


@dataclass(frozen=True)
class Citation:
    marker: int  # 1-indexed, as it appeared in the answer text
    chunk_id: str
    is_number: str | None
    clause_number: str | None
    document_title: str | None
    document_source_url: str | None


@dataclass
class CitationValidationResult:
    citations: list[Citation]
    invalid_markers: list[int]  # cited numbers with no matching context block
    cited_chunk_indices: set[int]  # which context blocks (1-indexed) were actually used
    has_any_citation: bool


def extract_citation_markers(text: str) -> list[int]:
    """Every `[N]` occurrence, in order, duplicates included — order and
    duplication matter to callers that want the first citation, or a count
    of how often a source was leaned on."""
    return [int(match.group(1)) for match in _CITATION_PATTERN.finditer(text)]


def validate_citations(text: str, chunks: list[RetrievedChunk]) -> CitationValidationResult:
    markers = extract_citation_markers(text)
    citations: list[Citation] = []
    invalid: list[int] = []
    seen: set[int] = set()

    for marker in markers:
        if marker in seen:
            continue
        seen.add(marker)
        if marker < 1 or marker > len(chunks):
            invalid.append(marker)
            continue
        chunk = chunks[marker - 1]
        citations.append(
            Citation(
                marker=marker,
                chunk_id=str(chunk.chunk_id),
                is_number=chunk.is_number,
                clause_number=chunk.clause_number,
                document_title=chunk.document_title,
                document_source_url=chunk.document_source_url,
            )
        )

    return CitationValidationResult(
        citations=sorted(citations, key=lambda c: c.marker),
        invalid_markers=sorted(set(invalid)),
        cited_chunk_indices=seen - set(invalid),
        has_any_citation=bool(citations),
    )
