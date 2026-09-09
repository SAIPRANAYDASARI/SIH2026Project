"""Persists a fetched+parsed page as a `Document` row with full provenance,
idempotently: if a document already exists for the same `(source_name,
content_hash)` pair, the existing row is returned unchanged rather than
duplicated — re-running a crawl on unchanged upstream content is a no-op,
per the code quality bar. A changed hash for the same `source_url` is
treated as a new revision (a new `Document` row); nothing here deletes old
revisions, since Step 3's ingestion pipeline may want to compare them.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from ingestion.core.blob_store import BlobStore
from ingestion.core.http_client import FetchResult

PARSER_VERSION = "1"  # bump when a crawler's parsing logic changes meaningfully


@dataclass(frozen=True)
class ParsedPage:
    title: str | None
    is_number: str | None = None


async def persist_document(
    session: AsyncSession,
    blob_store: BlobStore,
    *,
    source_name: str,
    fetch_result: FetchResult,
    parsed: ParsedPage,
) -> tuple[Document, bool]:
    """Returns (document, was_created)."""
    content_hash = blob_store.put(fetch_result.content)

    existing = await session.scalar(
        select(Document).where(
            Document.source_name == source_name,
            Document.content_hash == content_hash,
        )
    )
    if existing is not None:
        return existing, False

    document = Document(
        source_url=fetch_result.url,
        source_name=source_name,
        title=parsed.title,
        content_hash=content_hash,
        blob_path=blob_store.relative_path(content_hash),
        parser_version=PARSER_VERSION,
        http_status=fetch_result.status_code,
        fetched_at=fetch_result.fetched_at,
        is_number=parsed.is_number,
    )
    session.add(document)
    await session.flush()
    return document, True
