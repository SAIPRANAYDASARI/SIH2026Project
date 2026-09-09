"""initial schema: standards, schemes, documents/chunks, conversations,
licences, audit log

Revision ID: 0001
Revises:
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def _timestamp_columns() -> list[sa.Column]:
    """The created_at/updated_at pair every table gets, matching
    `app.db.base.TimestampMixin`. Factored out purely to keep each
    `create_table` call's column list under the line-length limit."""
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "standards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("is_number", sa.String(64), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("scope", sa.Text, nullable=True),
        sa.Column("technical_committee", sa.String(128), nullable=True),
        sa.Column("ics_code", sa.String(32), nullable=True),
        sa.Column("publication_year", sa.Integer, nullable=True),
        sa.Column("amendment_status", sa.String(64), nullable=True),
        sa.Column("reaffirmation_status", sa.String(64), nullable=True),
        sa.Column("is_qco_mandatory", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("applicable_schemes", postgresql.ARRAY(sa.String(32)), nullable=True),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("fetched_at", sa.String(64), nullable=True),
        *_timestamp_columns(),
    )
    op.create_index("ix_standards_is_number", "standards", ["is_number"], unique=True)

    op.create_table(
        "schemes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("rules_yaml_path", sa.String(256), nullable=True),
        sa.Column("source_url", sa.Text, nullable=True),
        *_timestamp_columns(),
    )
    op.create_index("ix_schemes_code", "schemes", ["code"], unique=True)

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("source_name", sa.String(128), nullable=False),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("blob_path", sa.Text, nullable=False),
        sa.Column("parser_version", sa.String(32), nullable=False),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("fetched_at", sa.String(64), nullable=False),
        sa.Column("is_number", sa.String(64), nullable=True),
        *_timestamp_columns(),
    )
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])
    op.create_index(
        "ix_documents_content_hash_source", "documents", ["content_hash", "source_name"]
    )

    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_number", sa.String(64), nullable=True),
        sa.Column("section_path", sa.Text, nullable=True),
        sa.Column("clause_number", sa.String(64), nullable=True),
        sa.Column("page_number", sa.Integer, nullable=True),
        sa.Column("context_header", sa.Text, nullable=True),
        sa.Column("text_content", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("extra_metadata", postgresql.JSONB, nullable=True),
        *_timestamp_columns(),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_is_number", "chunks", ["is_number"])
    # Full-text search index; the text-search configuration tuned so
    # alphanumeric identifiers (IS 15111, CM/L 1234567) survive tokenisation
    # is introduced in Step 3's ingestion migration, not here.
    op.execute(
        "CREATE INDEX ix_chunks_text_fts ON chunks "
        "USING GIN (to_tsvector('english', text_content))"
    )
    op.execute(
        "CREATE INDEX ix_chunks_embedding_ivfflat ON chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    audience_enum = postgresql.ENUM("industry", "consumer", name="audience")
    message_role_enum = postgresql.ENUM("user", "assistant", "system", name="message_role")

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("audience", audience_enum, nullable=False, server_default="consumer"),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("is_seed_data", sa.Boolean, nullable=False, server_default=sa.false()),
        *_timestamp_columns(),
    )
    op.create_index("ix_conversations_session_id", "conversations", ["session_id"])
    op.create_index(
        "ix_conversations_session_created", "conversations", ["session_id", "created_at"]
    )

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", message_role_enum, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("intent", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("citations", postgresql.JSONB, nullable=True),
        sa.Column("retrieval_debug", postgresql.JSONB, nullable=True),
        sa.Column("model_backend", sa.String(128), nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("feedback_rating", sa.Integer, nullable=True),
        sa.Column("feedback_comment", sa.Text, nullable=True),
        *_timestamp_columns(),
    )

    licence_type_enum = postgresql.ENUM("cml", "crs_r", "huid", name="licence_type")
    licence_status_enum = postgresql.ENUM(
        "active", "expired", "suspended", "cancelled", "not_found", name="licence_status"
    )

    op.create_table(
        "licences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("licence_number", sa.String(64), nullable=False),
        sa.Column("licence_type", licence_type_enum, nullable=False),
        sa.Column("status", licence_status_enum, nullable=False),
        sa.Column("holder_name", sa.Text, nullable=True),
        sa.Column("is_number", sa.String(64), nullable=True),
        sa.Column("product_category", sa.String(256), nullable=True),
        sa.Column("valid_from", sa.Date, nullable=True),
        sa.Column("valid_until", sa.Date, nullable=True),
        sa.Column("is_seed_data", sa.Boolean, nullable=False, server_default=sa.false()),
        *_timestamp_columns(),
    )
    op.create_index("ix_licences_licence_number", "licences", ["licence_number"])

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("audience", sa.String(16), nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("intent", sa.String(64), nullable=True),
        sa.Column("retrieved_chunk_ids", postgresql.ARRAY(sa.String(64)), nullable=True),
        sa.Column("model_backend", sa.String(128), nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("validation_outcome", sa.String(32), nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("prompt_tokens", sa.Integer, nullable=True),
        sa.Column("completion_tokens", sa.Integer, nullable=True),
        sa.Column("extra_metadata", postgresql.JSONB, nullable=True),
        sa.Column("is_seed_data", sa.Boolean, nullable=False, server_default=sa.false()),
        *_timestamp_columns(),
    )
    op.create_index("ix_audit_log_intent", "audit_log", ["intent"])
    op.create_index("ix_audit_log_confidence", "audit_log", ["confidence"])
    op.create_index("ix_audit_log_validation_outcome", "audit_log", ["validation_outcome"])
    op.create_index("ix_audit_log_created_intent", "audit_log", ["created_at", "intent"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("licences")
    postgresql.ENUM(name="licence_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="licence_type").drop(op.get_bind(), checkfirst=True)
    op.drop_table("messages")
    op.drop_table("conversations")
    postgresql.ENUM(name="message_role").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="audience").drop(op.get_bind(), checkfirst=True)
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("schemes")
    op.drop_table("standards")
