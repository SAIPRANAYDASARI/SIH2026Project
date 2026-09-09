"""Tests the orchestration logic in app.retrieval.hybrid without a live
Postgres or reranker server, by injecting fakes for every retriever/client:

- `select_candidates` is tested against fake Sparse/Dense/ExactMatch
  retrievers and a fake EmbeddingClient — none of them touch the `session`
  argument, so it's passed as `None` and never used.
- `load_candidate_chunks` is tested against a real in-memory SQLite
  Chunk/Document table (plain SQLAlchemy select/join, no Postgres-only
  functions, so this one genuinely exercises real DB code).
- `rerank_candidates` is tested against a fake RerankerClient.

What this does NOT cover: the actual Postgres full-text/pgvector queries in
sparse.py/dense.py, which need a real Postgres+pgvector database to run at
all (see those modules' docstrings) — verify those against the corpus this
crawls on your machine, e.g. via `python -m app.retrieval.cli query "..."`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.models.document import Chunk, Document
from app.retrieval.hybrid import (
    RERANK_INPUT_CHAR_LIMIT,
    load_candidate_chunks,
    rerank_candidates,
    select_candidates,
)
from app.retrieval.models import RetrievedChunk, RetrieverSource


class FakeSparseRetriever:
    def __init__(self, results: list[tuple[uuid.UUID, float]]) -> None:
        self.results = results

    async def search(self, session, query_text, limit):
        return self.results[:limit]


class FakeDenseRetriever:
    def __init__(self, results: list[tuple[uuid.UUID, float]]) -> None:
        self.results = results

    async def search(self, session, query_vector, limit):
        return self.results[:limit]


class FakeExactMatchRetriever:
    def __init__(self, results: list[uuid.UUID]) -> None:
        self.results = results

    async def search(self, session, identifiers, limit):
        return self.results[:limit]


class FakeEmbeddingClient:
    async def embed_one(self, text: str) -> list[float]:
        return [0.0] * 4

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 4 for _ in texts]


class FakeRerankerClient:
    def __init__(self, score_by_index: dict[int, float]) -> None:
        self.score_by_index = score_by_index
        self.received_documents: list[str] = []

    async def rerank(self, query: str, documents: list[str]):
        from app.ml.reranker_client import RerankResult

        self.received_documents = list(documents)
        return [
            RerankResult(index=i, score=self.score_by_index.get(i, 0.0))
            for i in range(len(documents))
        ]


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


@pytest.mark.asyncio
async def test_select_candidates_prioritizes_exact_match() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    settings = _settings(rrf_k=60, rerank_top_k=8, sparse_candidate_k=10, dense_candidate_k=10)

    analysis, ordered_ids, scores = await select_candidates(
        "What is IS 15111 about?",
        session=None,
        sparse_retriever=FakeSparseRetriever([(b, 0.5), (a, 0.3)]),
        dense_retriever=FakeDenseRetriever([(c, 0.9), (a, 0.7)]),
        exact_match_retriever=FakeExactMatchRetriever([a]),
        embedding_client=FakeEmbeddingClient(),
        settings=settings,
    )

    assert ordered_ids[0] == a  # exact match always first
    assert set(ordered_ids) == {a, b, c}
    assert RetrieverSource.EXACT_MATCH in scores[a].sources
    assert RetrieverSource.SPARSE in scores[a].sources
    assert RetrieverSource.DENSE in scores[a].sources
    assert scores[a].fused_score is not None


@pytest.mark.asyncio
async def test_select_candidates_without_identifiers_skips_exact_match() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    settings = _settings(sparse_candidate_k=10, dense_candidate_k=10)
    exact_match = FakeExactMatchRetriever([a])  # would match if called

    _, ordered_ids, scores = await select_candidates(
        "What is the weather today?",  # no identifiers, out-of-scope-ish
        session=None,
        sparse_retriever=FakeSparseRetriever([(b, 0.5)]),
        dense_retriever=FakeDenseRetriever([(b, 0.5)]),
        exact_match_retriever=exact_match,
        embedding_client=FakeEmbeddingClient(),
        settings=settings,
    )

    assert a not in scores  # exact-match retriever was never invoked
    assert ordered_ids == [b]


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Document.__table__.create)
        await conn.run_sync(Chunk.__table__.create)

    session_maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_load_candidate_chunks_joins_document_metadata(db_session: AsyncSession) -> None:
    document = Document(
        source_url="https://example.com/is-15111",
        source_name="bis_connect",
        title="IS 15111 LED Luminaires",
        content_hash="abc123",
        blob_path="ab/c1/abc123",
        parser_version="1",
        fetched_at="2026-08-25T00:00:00+00:00",
        is_number="IS 15111",
    )
    db_session.add(document)
    await db_session.flush()

    chunk = Chunk(
        document_id=document.id,
        is_number="IS 15111",
        section_path="4.2 Requirements",
        clause_number="4.2.1",
        text_content="Temperature endurance requirements.",
    )
    db_session.add(chunk)
    await db_session.flush()

    from app.retrieval.hybrid import CandidateScores

    scores = {chunk.id: CandidateScores(fused_score=0.5)}
    results = await load_candidate_chunks(db_session, [chunk.id], scores)

    assert len(results) == 1
    assert results[0].document_title == "IS 15111 LED Luminaires"
    assert results[0].document_source_url == "https://example.com/is-15111"
    assert results[0].fused_score == 0.5


@pytest.mark.asyncio
async def test_load_candidate_chunks_skips_missing_ids(db_session: AsyncSession) -> None:
    from app.retrieval.hybrid import CandidateScores

    missing_id = uuid.uuid4()
    results = await load_candidate_chunks(db_session, [missing_id], {missing_id: CandidateScores()})
    assert results == []


def _retrieved_chunk(text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        text_content=text,
        is_number=None,
        section_path=None,
        clause_number=None,
        page_number=None,
        context_header=None,
    )


@pytest.mark.asyncio
async def test_rerank_candidates_reorders_by_score_and_truncates() -> None:
    candidates = [_retrieved_chunk("low"), _retrieved_chunk("high"), _retrieved_chunk("mid")]
    reranker = FakeRerankerClient({0: 0.1, 1: 0.9, 2: 0.5})

    ranked = await rerank_candidates("query", candidates, reranker_client=reranker, top_k=2)

    assert [c.text_content for c in ranked] == ["high", "mid"]
    assert ranked[0].rerank_score == 0.9


@pytest.mark.asyncio
async def test_rerank_candidates_truncates_scoring_text_but_keeps_full_chunk() -> None:
    """Only the cross-encoder's *input* is shortened (it dominates answer
    latency); the chunk handed onward to the answer engine keeps its full
    text, so nothing is lost from the cited context."""
    long_text = "x" * (RERANK_INPUT_CHAR_LIMIT + 500)
    candidates = [_retrieved_chunk(long_text)]
    reranker = FakeRerankerClient({0: 0.9})

    ranked = await rerank_candidates("query", candidates, reranker_client=reranker, top_k=1)

    assert len(reranker.received_documents[0]) == RERANK_INPUT_CHAR_LIMIT
    assert ranked[0].text_content == long_text


@pytest.mark.asyncio
async def test_rerank_candidates_empty_input() -> None:
    ranked = await rerank_candidates("query", [], reranker_client=FakeRerankerClient({}), top_k=5)
    assert ranked == []
