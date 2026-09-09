"""Audit log: one row per question, feeding the Step-11 officer dashboard.

Recorded for every chat turn regardless of outcome, per the API surface spec
("audit log recording every question with retrieved chunk ids, model
backend, latency, token counts and validation outcome"). This is also the
raw material the officer dashboard clusters to find unanswered/low-confidence
topics — so `intent`, `confidence` and `validation_outcome` are indexed.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PortableJSON, TimestampMixin, UUIDPrimaryKeyMixin


class AuditLogEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "audit_log"

    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    audience: Mapped[str] = mapped_column(String(16), nullable=False)

    question: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    retrieved_chunk_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String(64)), nullable=True)
    model_backend: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, index=True, nullable=True)
    validation_outcome: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    # e.g. passed, fallback_low_confidence, fallback_citation_failure, refused_out_of_scope

    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra_metadata: Mapped[dict[str, object] | None] = mapped_column(PortableJSON, nullable=True)
    is_seed_data: Mapped[bool] = mapped_column(default=False, nullable=False)

    __table_args__ = (Index("ix_audit_log_created_intent", "created_at", "intent"),)
