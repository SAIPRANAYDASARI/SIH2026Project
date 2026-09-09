"""Orchestrates parse → chunk → embed → persist for one already-crawled
`Document` row, and is idempotent: if the document already has chunks
tagged with the current `CHUNKING_VERSION`, it's a no-op; if it has chunks
from an older version, they're deleted and regenerated; if the document
type is unrecognized or parses to zero blocks, that's reported rather than
silently skipped.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.document import Chunk, Document
from ingestion.chunking.chunker import chunk_blocks
from ingestion.core.blob_store import BlobStore
from ingestion.embeddings.client import EmbeddingClient
from ingestion.parsing.blocks import Block
from ingestion.parsing.html_parser import parse_html
from ingestion.parsing.pdf_parser import parse_pdf

logger = get_logger(__name__)

# Bump when chunking/parsing logic changes meaningfully enough that existing
# chunks should be regenerated rather than left as stale no-ops.
CHUNKING_VERSION = "1"

_PDF_MAGIC = b"%PDF-"


@dataclass(frozen=True)
class ProcessResult:
    status: str  # "created" | "unchanged" | "skipped_empty"
    chunk_count: int


def _parse(content: bytes) -> list[Block]:
    if content.lstrip()[:5] == _PDF_MAGIC:
        return parse_pdf(content)
    return parse_html(content)


async def process_document(
    session: AsyncSession,
    blob_store: BlobStore,
    document: Document,
    embedding_client: EmbeddingClient,
) -> ProcessResult:
    existing = list(
        (await session.execute(select(Chunk).where(Chunk.document_id == document.id))).scalars()
    )
    if existing and all(
        (c.extra_metadata or {}).get("chunking_version") == CHUNKING_VERSION for c in existing
    ):
        return ProcessResult(status="unchanged", chunk_count=len(existing))

    if existing:
        await session.execute(delete(Chunk).where(Chunk.document_id == document.id))

    content = blob_store.get(document.content_hash)
    blocks = _parse(content)
    if not blocks:
        logger.warning(
            "no_blocks_parsed", document_id=str(document.id), source=document.source_name
        )
        return ProcessResult(status="skipped_empty", chunk_count=0)

    doc_label = document.is_number or document.title or document.source_url
    drafts = chunk_blocks(blocks, doc_label=doc_label)
    if not drafts:
        return ProcessResult(status="skipped_empty", chunk_count=0)

    embeddings = await embedding_client.embed_batch([draft.text for draft in drafts])

    for draft, embedding in zip(drafts, embeddings, strict=True):
        session.add(
            Chunk(
                document_id=document.id,
                is_number=document.is_number,
                section_path=draft.section_path,
                clause_number=draft.clause_number,
                page_number=draft.page_number,
                context_header=draft.context_header,
                text_content=draft.text,
                token_count=draft.token_count,
                embedding=embedding,
                extra_metadata={"chunking_version": CHUNKING_VERSION},
            )
        )

    await session.commit()
    logger.info("document_processed", document_id=str(document.id), chunk_count=len(drafts))
    return ProcessResult(status="created", chunk_count=len(drafts))
