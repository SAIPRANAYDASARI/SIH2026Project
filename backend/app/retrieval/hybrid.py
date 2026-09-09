"""Orchestrates the full retrieval pipeline described in the brief's
architecture section: query understanding → exact-match lookup → BM25 +
dense search → reciprocal rank fusion → cross-encoder rerank → top-k.

Split into three pieces specifically so the fusion/ranking *logic* is unit
testable without a live Postgres or a live reranker server:

- `select_candidates` combines exact-match, sparse and dense results via
  RRF. Its retriever/embedding-client parameters are Protocols
  (`SparseRetriever`, `DenseRetriever`, `ExactMatchRetriever`,
  `EmbeddingClient`), so tests inject fakes that never touch a database.
- `load_candidate_chunks` is the one function that actually needs a real
  Postgres database (joins `Chunk`+`Document`) — see
  `tests/retrieval/test_hybrid.py` for what is and isn't covered without one.
- `rerank_candidates` calls the reranker client and re-sorts; also testable
  with a fake `RerankerClient` against hand-built `RetrievedChunk`s.

`hybrid_search` wires the three together with real Postgres/Ollama/Infinity
backends by default, overridable for tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.ml.embedding_client import EmbeddingClient, get_embedding_client
from app.ml.reranker_client import RerankerClient, get_reranker_client
from app.models.document import Chunk, Document
from app.retrieval.dense import DenseRetriever, PgVectorRetriever
from app.retrieval.exact_match import (
    ChunkExactMatchRetriever,
    ExactMatchRetriever,
    has_chunk_routable_identifier,
)
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.models import RetrievedChunk, RetrieverSource
from app.retrieval.query_understanding import QueryAnalysis, analyze_query
from app.retrieval.sparse import PostgresFTSRetriever, SparseRetriever


# How much of each chunk is handed to the cross-encoder for scoring. See
# `rerank_candidates` for why this is truncated and why it doesn't cost
# answer quality.
RERANK_INPUT_CHAR_LIMIT = 1200


@dataclass
class CandidateScores:
    sources: set[RetrieverSource] = field(default_factory=set)
    sparse_rank: int | None = None
    sparse_score: float | None = None
    dense_rank: int | None = None
    dense_score: float | None = None
    fused_score: float | None = None


async def select_candidates(
    query: str,
    session: AsyncSession,
    *,
    sparse_retriever: SparseRetriever,
    dense_retriever: DenseRetriever,
    exact_match_retriever: ExactMatchRetriever,
    embedding_client: EmbeddingClient,
    settings: Settings,
) -> tuple[QueryAnalysis, list[uuid.UUID], dict[uuid.UUID, CandidateScores]]:
    """Returns (query_analysis, ordered candidate ids, per-id score
    breakdown). Ordering: exact matches first (deduplicated), then the
    RRF-fused hybrid ranking for whatever isn't already an exact match."""
    analysis = analyze_query(query)
    scores: dict[uuid.UUID, CandidateScores] = {}

    exact_ids: list[uuid.UUID] = []
    if has_chunk_routable_identifier(analysis.identifiers):
        exact_ids = await exact_match_retriever.search(
            session, analysis.identifiers, settings.rerank_top_k
        )
        for chunk_id in exact_ids:
            scores.setdefault(chunk_id, CandidateScores()).sources.add(RetrieverSource.EXACT_MATCH)

    sparse_results = await sparse_retriever.search(session, query, settings.sparse_candidate_k)
    for rank, (chunk_id, score) in enumerate(sparse_results, start=1):
        entry = scores.setdefault(chunk_id, CandidateScores())
        entry.sources.add(RetrieverSource.SPARSE)
        entry.sparse_rank = rank
        entry.sparse_score = score

    query_vector = await embedding_client.embed_one(query)
    dense_results = await dense_retriever.search(session, query_vector, settings.dense_candidate_k)
    for rank, (chunk_id, score) in enumerate(dense_results, start=1):
        entry = scores.setdefault(chunk_id, CandidateScores())
        entry.sources.add(RetrieverSource.DENSE)
        entry.dense_rank = rank
        entry.dense_score = score

    fused = reciprocal_rank_fusion(
        [
            [chunk_id for chunk_id, _ in sparse_results],
            [chunk_id for chunk_id, _ in dense_results],
        ],
        k=settings.rrf_k,
    )
    for chunk_id, fused_score in fused.items():
        scores[chunk_id].fused_score = fused_score

    fused_order = sorted(fused.keys(), key=lambda cid: fused.get(cid, 0.0), reverse=True)
    ordered_ids = [*exact_ids, *[cid for cid in fused_order if cid not in set(exact_ids)]]

    return analysis, ordered_ids, scores


async def load_candidate_chunks(
    session: AsyncSession,
    candidate_ids: list[uuid.UUID],
    scores: dict[uuid.UUID, CandidateScores],
) -> list[RetrievedChunk]:
    if not candidate_ids:
        return []

    stmt = (
        select(Chunk, Document)
        .join(Document, Chunk.document_id == Document.id)
        .where(Chunk.id.in_(candidate_ids))
    )
    rows = (await session.execute(stmt)).all()
    by_id = {chunk.id: (chunk, document) for chunk, document in rows}

    retrieved: list[RetrievedChunk] = []
    for chunk_id in candidate_ids:
        if chunk_id not in by_id:
            continue  # deleted between candidate selection and load; skip
        chunk, document = by_id[chunk_id]
        score = scores.get(chunk_id, CandidateScores())
        retrieved.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                text_content=chunk.text_content,
                is_number=chunk.is_number,
                section_path=chunk.section_path,
                clause_number=chunk.clause_number,
                page_number=chunk.page_number,
                context_header=chunk.context_header,
                sources=score.sources,
                sparse_rank=score.sparse_rank,
                sparse_score=score.sparse_score,
                dense_rank=score.dense_rank,
                dense_score=score.dense_score,
                fused_score=score.fused_score,
                document_title=document.title,
                document_source_url=document.source_url,
                document_fetched_at=document.fetched_at,
            )
        )
    return retrieved


async def rerank_candidates(
    query: str,
    candidates: list[RetrievedChunk],
    *,
    reranker_client: RerankerClient,
    top_k: int,
) -> list[RetrievedChunk]:
    if not candidates:
        return []

    # Score the *opening* of each chunk rather than the whole thing. The
    # cross-encoder's cost scales with document length, and on CPU that
    # dominates end-to-end answer latency: measured against this corpus
    # (~2.4k chars/chunk, 16 candidates) reranking took ~39s at full length
    # versus ~13s truncated here — a 3x saving on the slowest stage.
    #
    # This only changes the text the *scorer* sees. The full `text_content`
    # is what still gets handed to the answer engine as context, so nothing
    # is lost from the answer itself; and bge-reranker-v2-m3 truncates long
    # inputs to its own max sequence length internally anyway, so much of
    # the tail was never influencing the score to begin with.
    scoring_texts = [c.text_content[:RERANK_INPUT_CHAR_LIMIT] for c in candidates]

    results = await reranker_client.rerank(query, scoring_texts)
    for result in results:
        candidates[result.index].rerank_score = result.score

    ranked = sorted(
        candidates,
        key=lambda c: c.rerank_score if c.rerank_score is not None else float("-inf"),
        reverse=True,
    )
    return ranked[:top_k]


async def hybrid_search(
    session: AsyncSession,
    query: str,
    *,
    settings: Settings | None = None,
    sparse_retriever: SparseRetriever | None = None,
    dense_retriever: DenseRetriever | None = None,
    exact_match_retriever: ExactMatchRetriever | None = None,
    embedding_client: EmbeddingClient | None = None,
    reranker_client: RerankerClient | None = None,
) -> tuple[QueryAnalysis, list[RetrievedChunk]]:
    settings = settings or get_settings()
    sparse_retriever = sparse_retriever or PostgresFTSRetriever()
    dense_retriever = dense_retriever or PgVectorRetriever()
    exact_match_retriever = exact_match_retriever or ChunkExactMatchRetriever()
    embedding_client = embedding_client or get_embedding_client()
    reranker_client = reranker_client or get_reranker_client()

    analysis, candidate_ids, scores = await select_candidates(
        query,
        session,
        sparse_retriever=sparse_retriever,
        dense_retriever=dense_retriever,
        exact_match_retriever=exact_match_retriever,
        embedding_client=embedding_client,
        settings=settings,
    )

    # Cap the pool handed to the (comparatively expensive) reranker — no
    # point cross-encoding every fused candidate when only the top handful
    # will ever be shown. Kept tight (2x rather than 3x) since this pool
    # size is the single biggest lever on end-to-end answer latency.
    pool = candidate_ids[: max(settings.rerank_top_k * 2, 12)]
    candidates = await load_candidate_chunks(session, pool, scores)

    ranked = await rerank_candidates(
        query, candidates, reranker_client=reranker_client, top_k=settings.rerank_top_k
    )
    return analysis, ranked
