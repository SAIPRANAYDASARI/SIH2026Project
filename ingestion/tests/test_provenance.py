"""persist_document is idempotent: re-persisting identical fetched content
for the same source returns the existing Document row rather than creating
a duplicate, while a genuine content change creates a new revision."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.document import Document
from ingestion.core.blob_store import BlobStore
from ingestion.core.http_client import FetchResult
from ingestion.core.provenance import ParsedPage, persist_document


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # Only the one table this test needs — the full metadata includes
        # Postgres-only ARRAY columns that SQLite's compiler can't render.
        await conn.run_sync(Document.__table__.create)

    session_maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


def _fetch_result(content: bytes, url: str = "https://example.com/page") -> FetchResult:
    return FetchResult(
        url=url, status_code=200, content=content, fetched_at="2026-08-25T00:00:00+00:00"
    )


@pytest.mark.asyncio
async def test_persist_creates_a_document(db_session: AsyncSession, tmp_path: Path) -> None:
    blob_store = BlobStore(tmp_path)

    document, created = await persist_document(
        db_session,
        blob_store,
        source_name="bis_connect",
        fetch_result=_fetch_result(b"<html><title>IS 15111</title></html>"),
        parsed=ParsedPage(title="IS 15111", is_number="IS 15111"),
    )

    assert created is True
    assert document.title == "IS 15111"
    assert document.is_number == "IS 15111"
    assert blob_store.exists(document.content_hash)


@pytest.mark.asyncio
async def test_repersisting_unchanged_content_is_a_noop(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    blob_store = BlobStore(tmp_path)
    content = b"<html><title>Unchanged page</title></html>"

    first, first_created = await persist_document(
        db_session,
        blob_store,
        source_name="bis_schemes",
        fetch_result=_fetch_result(content),
        parsed=ParsedPage(title="Unchanged page"),
    )
    second, second_created = await persist_document(
        db_session,
        blob_store,
        source_name="bis_schemes",
        fetch_result=_fetch_result(content),
        parsed=ParsedPage(title="Unchanged page"),
    )

    assert first_created is True
    assert second_created is False
    assert first.id == second.id

    result = await db_session.execute(select(Document).where(Document.source_name == "bis_schemes"))
    assert len(result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_changed_content_creates_a_new_revision(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    blob_store = BlobStore(tmp_path)

    _, first_created = await persist_document(
        db_session,
        blob_store,
        source_name="qco",
        fetch_result=_fetch_result(b"version one"),
        parsed=ParsedPage(title="QCO list v1"),
    )
    _, second_created = await persist_document(
        db_session,
        blob_store,
        source_name="qco",
        fetch_result=_fetch_result(b"version two"),
        parsed=ParsedPage(title="QCO list v2"),
    )

    assert first_created is True
    assert second_created is True

    result = await db_session.execute(select(Document).where(Document.source_name == "qco"))
    assert len(result.scalars().all()) == 2
