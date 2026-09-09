"""Retrieval corpus: source documents and clause-aware chunks.

`Document` records full provenance (source URL, fetch timestamp, HTTP status,
content hash, parser version) per docs/DATA_SOURCES.md so every retrieved
answer can be traced back to exactly what was fetched and when. `Chunk` is
the retrieval unit: clause-aware (not fixed-window), carrying its own section
path/clause number/page number plus a dense embedding column for pgvector
similarity search alongside Postgres full-text search on `text_content`.

The embedding column width (1024) matches BGE-M3's output dimension
(`settings.embedding_dim`); if that model is ever swapped, this column and
the pgvector index must be rebuilt together.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PortableJSON, TimestampMixin, UUIDPrimaryKeyMixin


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "documents"

    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # e.g. bis_connect, bis_scheme_pages, qco_list, hallmarking, consumer

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    blob_path: Mapped[str] = mapped_column(Text, nullable=False)  # raw response, content-addressed
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetched_at: Mapped[str] = mapped_column(String(64), nullable=False)  # ISO 8601
    is_number: Mapped[str | None] = mapped_column(String(64), nullable=True)

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_documents_content_hash_source", "content_hash", "source_name"),)


class Chunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    is_number: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    section_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    clause_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_header: Mapped[str | None] = mapped_column(Text, nullable=True)

    text_content: Mapped[str] = mapped_column(Text, nullable=False)  # markdown; tables preserved
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)
    extra_metadata: Mapped[dict[str, object] | None] = mapped_column(PortableJSON, nullable=True)

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (Index("ix_chunks_document_id", "document_id"),)
