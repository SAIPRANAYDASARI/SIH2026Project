"""Conversation and message persistence.

A `Conversation` belongs to an anonymous session (signed cookie) or an
authenticated account. `audience` drives the persona (industry vs consumer,
see F5) for every message in the thread. Each assistant `Message` stores its
retrieval/citation metadata as JSONB so the frontend citation panel and the
Step-11 evaluation harness can both read it without a join fan-out.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PortableJSON, TimestampMixin, UUIDPrimaryKeyMixin


class Audience(StrEnum):
    INDUSTRY = "industry"
    CONSUMER = "consumer"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversations"

    session_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    audience: Mapped[Audience] = mapped_column(
        Enum(Audience, name="audience", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        default=Audience.CONSUMER,
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_seed_data: Mapped[bool] = mapped_column(default=False, nullable=False)

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )

    __table_args__ = (Index("ix_conversations_session_created", "session_id", "created_at"),)


class Message(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Populated for assistant messages by the answer engine (Step 5+).
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    citations: Mapped[list[dict[str, object]] | None] = mapped_column(PortableJSON, nullable=True)
    retrieval_debug: Mapped[dict[str, object] | None] = mapped_column(PortableJSON, nullable=True)
    model_backend: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)

    feedback_rating: Mapped[int | None] = mapped_column(nullable=True)  # -1, 0, 1
    feedback_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
