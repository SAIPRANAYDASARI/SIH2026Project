"""Shared retrieval data shapes.

`RetrievedChunk` deliberately carries every score a chunk earned at each
retrieval stage (sparse, dense, fused, rerank) plus which retriever(s)
surfaced it — the brief calls this transparency "a demo asset" meant to
surface in the UI (Step 7), not just an internal implementation detail.
These become Pydantic response schemas once Step 6 exposes them over the
API; kept as plain dataclasses here since this module has no FastAPI
dependency of its own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum


class RetrieverSource(StrEnum):
    SPARSE = "sparse"
    DENSE = "dense"
    EXACT_MATCH = "exact_match"


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    text_content: str
    is_number: str | None
    section_path: str | None
    clause_number: str | None
    page_number: int | None
    context_header: str | None

    sources: set[RetrieverSource] = field(default_factory=set)
    sparse_rank: int | None = None
    sparse_score: float | None = None
    dense_rank: int | None = None
    dense_score: float | None = None
    fused_score: float | None = None
    rerank_score: float | None = None

    # Citation metadata, populated once the owning Document is joined in
    # (see hybrid.py) — kept optional so fusion/rerank logic can be tested
    # against bare chunk data without needing a Document row at all.
    document_title: str | None = None
    document_source_url: str | None = None
    document_fetched_at: str | None = None
