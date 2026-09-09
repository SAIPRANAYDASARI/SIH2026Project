"""Persistence for conversations and messages — the "persistence" half of
Step 6's "FastAPI surface + persistence" scope. Route handlers
(`app.api.v1.chat`) call these functions rather than touching the ORM
models directly, so the persistence shape can change without route code
changing (the brief's "no business logic in `app.api`" rule from Step 1's
`DECISIONS.md` component-boundary notes).

Every function takes an already-open `AsyncSession` and does not commit —
the caller controls the transaction boundary (important for the streaming
chat endpoint, which persists the user message before the LLM call and the
assistant message only after it succeeds).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.conversation import Audience, Conversation, Message, MessageRole


async def get_or_create_conversation(
    session: AsyncSession,
    *,
    session_id: str,
    conversation_id: uuid.UUID | None,
    audience: Audience | None,
) -> Conversation:
    if conversation_id is not None:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.session_id != session_id:
            # Deliberately the same 404 for "doesn't exist" and "belongs to
            # someone else's session" — distinguishing them would leak
            # whether a given conversation id exists to a caller who
            # doesn't own it.
            raise NotFoundError(f"No conversation {conversation_id} for this session.")
        return conversation

    conversation = Conversation(session_id=session_id, audience=audience or Audience.CONSUMER)
    session.add(conversation)
    await session.flush()
    return conversation


async def persist_message(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    role: MessageRole,
    content: str,
    intent: str | None = None,
    citations: list[dict[str, object]] | None = None,
    retrieval_debug: dict[str, object] | None = None,
    model_backend: str | None = None,
    latency_ms: int | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        intent=intent,
        citations=citations,
        retrieval_debug=retrieval_debug,
        model_backend=model_backend,
        latency_ms=latency_ms,
    )
    session.add(message)
    await session.flush()
    return message


#: Longest auto-generated conversation title. Comfortably under the
#: `Conversation.title` column's 256-char limit, and short enough to fit a
#: history sidebar row without wrapping.
TITLE_MAX_LENGTH = 60


def _derive_title(first_message: str) -> str:
    """Condense a user's first message into a sidebar-friendly label.

    Titles are derived rather than model-generated on purpose: naming a
    thread shouldn't cost an extra LLM round-trip (the hosted free tier is
    both slow and rate-limited here), and the first question is almost
    always what the thread is about.
    """
    condensed = " ".join(first_message.split())
    if len(condensed) <= TITLE_MAX_LENGTH:
        return condensed
    # Prefer cutting at a word boundary so the ellipsis doesn't land
    # mid-word; fall back to a hard cut for input with no spaces.
    clipped = condensed[:TITLE_MAX_LENGTH]
    boundary = clipped.rfind(" ")
    if boundary > TITLE_MAX_LENGTH // 2:
        clipped = clipped[:boundary]
    return clipped.rstrip(" ,.;:") + "…"


async def set_title_from_first_message(
    session: AsyncSession, *, conversation: Conversation, first_message: str
) -> None:
    """Give a brand-new conversation a title taken from its opening
    question. No-op once a title exists, so continuing a thread never
    renames it."""
    if conversation.title:
        return
    conversation.title = _derive_title(first_message)
    await session.flush()


async def list_messages(session: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return list((await session.execute(stmt)).scalars())


async def list_conversations(
    session: AsyncSession, session_id: str, *, limit: int = 50
) -> list[Conversation]:
    stmt = (
        select(Conversation)
        .where(Conversation.session_id == session_id)
        .order_by(Conversation.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars())


async def record_feedback(
    session: AsyncSession,
    *,
    message_id: uuid.UUID,
    rating: int,
    comment: str | None = None,
) -> Message:
    """Sets `feedback_rating`/`feedback_comment` on an assistant message.
    `rating` is -1 (thumbs down), 0 (neutral/cleared), or 1 (thumbs up) —
    validated at the schema layer (`app.schemas.analytics.FeedbackRequest`),
    not here."""
    message = await session.get(Message, message_id)
    if message is None:
        raise NotFoundError(f"No message {message_id}.")
    message.feedback_rating = rating
    message.feedback_comment = comment
    await session.flush()
    return message


async def get_conversation_for_session(
    session: AsyncSession, *, conversation_id: uuid.UUID, session_id: str
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.session_id != session_id:
        raise NotFoundError(f"No conversation {conversation_id} for this session.")
    return conversation
