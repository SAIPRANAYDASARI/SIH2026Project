"""process_document orchestrates parse → chunk → embed → persist, and is
idempotent: reprocessing a document that already has chunks at the current
CHUNKING_VERSION is a no-op that makes zero embedding calls."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.document import Chunk, Document
from ingestion.core.blob_store import BlobStore
from ingestion.embeddings.client import EmbeddingClient
from ingestion.pipeline import CHUNKING_VERSION, process_document

SAMPLE_HTML = b"""
<html><body>
    <h1>IS 15111 : 2019 LED Luminaires</h1>
    <p>4.1 Scope. This standard covers general safety requirements.</p>
    <h2>4.2 Requirements</h2>
    <p>4.2.1 The luminaire shall withstand a temperature of 85 degrees Celsius
    for a continuous period without failure of any internal component.</p>
</body></html>
"""


class FakeEmbeddingClient(EmbeddingClient):
    def __init__(self) -> None:
        self.call_count = 0

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        return [[0.1] * 1024 for _ in texts]


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


def _make_document(content_hash: str, blob_path: str) -> Document:
    return Document(
        source_url="https://example.com/is-15111",
        source_name="bis_connect",
        title="IS 15111 : 2019 LED Luminaires",
        content_hash=content_hash,
        blob_path=blob_path,
        parser_version="1",
        http_status=200,
        fetched_at="2026-08-25T00:00:00+00:00",
        is_number="IS 15111",
    )


@pytest.mark.asyncio
async def test_process_document_creates_chunks(db_session: AsyncSession, tmp_path: Path) -> None:
    blob_store = BlobStore(tmp_path)
    content_hash = blob_store.put(SAMPLE_HTML)
    document = _make_document(content_hash, blob_store.relative_path(content_hash))
    db_session.add(document)
    await db_session.flush()

    embedding_client = FakeEmbeddingClient()
    result = await process_document(db_session, blob_store, document, embedding_client)

    assert result.status == "created"
    assert result.chunk_count > 0
    assert embedding_client.call_count == 1

    chunks = (
        (await db_session.execute(select(Chunk).where(Chunk.document_id == document.id)))
        .scalars()
        .all()
    )
    assert len(chunks) == result.chunk_count
    for chunk in chunks:
        assert chunk.is_number == "IS 15111"
        # pgvector returns a numpy array on read, hence list(...) before comparing.
        assert list(chunk.embedding) == [0.1] * 1024
        assert chunk.extra_metadata == {"chunking_version": CHUNKING_VERSION}


@pytest.mark.asyncio
async def test_reprocessing_unchanged_document_is_a_noop(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    blob_store = BlobStore(tmp_path)
    content_hash = blob_store.put(SAMPLE_HTML)
    document = _make_document(content_hash, blob_store.relative_path(content_hash))
    db_session.add(document)
    await db_session.flush()

    embedding_client = FakeEmbeddingClient()
    first = await process_document(db_session, blob_store, document, embedding_client)
    second = await process_document(db_session, blob_store, document, embedding_client)

    assert first.status == "created"
    assert second.status == "unchanged"
    assert second.chunk_count == first.chunk_count
    # The second call made no new embedding requests at all.
    assert embedding_client.call_count == 1


@pytest.mark.asyncio
async def test_stale_chunking_version_triggers_reprocessing(
    db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blob_store = BlobStore(tmp_path)
    content_hash = blob_store.put(SAMPLE_HTML)
    document = _make_document(content_hash, blob_store.relative_path(content_hash))
    db_session.add(document)
    await db_session.flush()

    embedding_client = FakeEmbeddingClient()
    await process_document(db_session, blob_store, document, embedding_client)

    monkeypatch.setattr("ingestion.pipeline.CHUNKING_VERSION", "2")
    result = await process_document(db_session, blob_store, document, embedding_client)

    assert result.status == "created"
    assert embedding_client.call_count == 2

    chunks = (
        (await db_session.execute(select(Chunk).where(Chunk.document_id == document.id)))
        .scalars()
        .all()
    )
    assert all(c.extra_metadata == {"chunking_version": "2"} for c in chunks)


@pytest.mark.asyncio
async def test_empty_document_is_reported_not_silently_dropped(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    blob_store = BlobStore(tmp_path)
    empty_html = b"<html><body><script>only boilerplate</script></body></html>"
    content_hash = blob_store.put(empty_html)
    document = _make_document(content_hash, blob_store.relative_path(content_hash))
    db_session.add(document)
    await db_session.flush()

    embedding_client = FakeEmbeddingClient()
    result = await process_document(db_session, blob_store, document, embedding_client)

    assert result.status == "skipped_empty"
    assert result.chunk_count == 0
    assert embedding_client.call_count == 0
