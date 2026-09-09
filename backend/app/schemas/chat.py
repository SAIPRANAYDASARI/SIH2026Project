"""Request/response contracts for the chat API (Step 6).

`Message.citations`/`retrieval_debug` are stored as JSONB (see
`app.models.conversation`); `CitationSchema` is the typed shape written into
that column and read back for `GET /conversations/{id}/messages`, kept in
one place so the write side (`app.services.conversation_service`) and the
read side (this schema) can't drift.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.conversation import Audience, MessageRole


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=4000)
    audience: Audience | None = None
    # ISO 639-1 code — "en" or "hi" (see app.api.v1.chat.SUPPORTED_LANGUAGES;
    # anything else falls back to "en"). The LLM is asked to write the whole
    # answer natively in this language (app.answer.prompts), not translated
    # after the fact.
    target_language: str | None = None


class CitationSchema(BaseModel):
    marker: int
    chunk_id: str
    is_number: str | None = None
    clause_number: str | None = None
    document_title: str | None = None
    document_source_url: str | None = None


class MessageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    intent: str | None = None
    citations: list[CitationSchema] | None = None
    model_backend: str | None = None
    latency_ms: int | None = None
    created_at: datetime


class ConversationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    audience: Audience
    title: str | None = None
    created_at: datetime
