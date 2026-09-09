"""ChunkExactMatchRetriever: prefers the IS-number + clause-number
intersection when both are present, falls back to a bare IS-number or
clause-number match otherwise. Uses plain SQLAlchemy select/where/in_ (no
Postgres-only functions), so it's tested against a real in-memory SQLite
Chunk table rather than mocked."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.document import Chunk, Document
from app.retrieval.exact_match import ChunkExactMatchRetriever, has_chunk_routable_identifier
from app.retrieval.query_understanding import Identifier, IdentifierType


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


def _document() -> Document:
    return Document(
        source_url="https://example.com",
        source_name="bis_connect",
        content_hash="deadbeef",
        blob_path="de/ad/deadbeef",
        parser_version="1",
        fetched_at="2026-08-25T00:00:00+00:00",
    )


def _chunk(document_id: uuid.UUID, is_number: str | None, clause_number: str | None) -> Chunk:
    return Chunk(
        document_id=document_id,
        is_number=is_number,
        clause_number=clause_number,
        text_content=f"{is_number} {clause_number}",
    )


@pytest.mark.asyncio
async def test_matches_is_number_and_clause_intersection(db_session: AsyncSession) -> None:
    document = _document()
    db_session.add(document)
    await db_session.flush()

    target = _chunk(document.id, "IS 15111", "4.2.1")
    other_clause_same_standard = _chunk(document.id, "IS 15111", "5.1")
    other_standard_same_clause = _chunk(document.id, "IS 302", "4.2.1")
    db_session.add_all([target, other_clause_same_standard, other_standard_same_clause])
    await db_session.flush()

    identifiers = [
        Identifier(IdentifierType.IS_NUMBER, "IS 15111", "IS 15111"),
        Identifier(IdentifierType.CLAUSE_REFERENCE, "4.2.1", "4.2.1"),
    ]
    retriever = ChunkExactMatchRetriever()
    result = await retriever.search(db_session, identifiers, limit=10)

    assert result == [target.id]


@pytest.mark.asyncio
async def test_falls_back_to_bare_is_number_when_no_intersection(db_session: AsyncSession) -> None:
    document = _document()
    db_session.add(document)
    await db_session.flush()

    chunk = _chunk(document.id, "IS 15111", "9.9.9")  # no clause 4.2.1 exists
    db_session.add(chunk)
    await db_session.flush()

    identifiers = [
        Identifier(IdentifierType.IS_NUMBER, "IS 15111", "IS 15111"),
        Identifier(IdentifierType.CLAUSE_REFERENCE, "4.2.1", "4.2.1"),
    ]
    retriever = ChunkExactMatchRetriever()
    result = await retriever.search(db_session, identifiers, limit=10)

    assert result == [chunk.id]


@pytest.mark.asyncio
async def test_no_identifiers_returns_empty(db_session: AsyncSession) -> None:
    retriever = ChunkExactMatchRetriever()
    result = await retriever.search(db_session, [], limit=10)
    assert result == []


def test_has_chunk_routable_identifier() -> None:
    assert has_chunk_routable_identifier(
        [Identifier(IdentifierType.IS_NUMBER, "IS 15111", "IS 15111")]
    )
    assert not has_chunk_routable_identifier([Identifier(IdentifierType.HUID, "AZ4526", "AZ4526")])
    assert not has_chunk_routable_identifier([])
