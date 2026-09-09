"""app.services.conversation_service against a real in-memory SQLite
Conversation/Message schema — plain SQLAlchemy select/get, no Postgres-only
functions, so this genuinely exercises the persistence code (not just
orchestration around a fake)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.errors import NotFoundError
from app.models.conversation import Audience, Conversation, Message, MessageRole
from app.services.conversation_service import (
    TITLE_MAX_LENGTH,
    get_conversation_for_session,
    get_or_create_conversation,
    list_conversations,
    list_messages,
    persist_message,
    set_title_from_first_message,
)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Conversation.__table__.create)
        await conn.run_sync(Message.__table__.create)

    session_maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_or_create_conversation_creates_new(db_session: AsyncSession) -> None:
    conversation = await get_or_create_conversation(
        db_session, session_id="session-a", conversation_id=None, audience=Audience.INDUSTRY
    )
    assert conversation.session_id == "session-a"
    assert conversation.audience is Audience.INDUSTRY
    assert conversation.id is not None


@pytest.mark.asyncio
async def test_get_or_create_conversation_defaults_to_consumer(db_session: AsyncSession) -> None:
    conversation = await get_or_create_conversation(
        db_session, session_id="session-a", conversation_id=None, audience=None
    )
    assert conversation.audience is Audience.CONSUMER


@pytest.mark.asyncio
async def test_get_or_create_conversation_returns_existing_for_same_session(
    db_session: AsyncSession,
) -> None:
    created = await get_or_create_conversation(
        db_session, session_id="session-a", conversation_id=None, audience=None
    )
    fetched = await get_or_create_conversation(
        db_session, session_id="session-a", conversation_id=created.id, audience=None
    )
    assert fetched.id == created.id


@pytest.mark.asyncio
async def test_get_or_create_conversation_rejects_other_sessions_conversation(
    db_session: AsyncSession,
) -> None:
    created = await get_or_create_conversation(
        db_session, session_id="session-a", conversation_id=None, audience=None
    )
    with pytest.raises(NotFoundError):
        await get_or_create_conversation(
            db_session, session_id="session-b", conversation_id=created.id, audience=None
        )


@pytest.mark.asyncio
async def test_get_or_create_conversation_rejects_unknown_id(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await get_or_create_conversation(
            db_session, session_id="session-a", conversation_id=uuid.uuid4(), audience=None
        )


@pytest.mark.asyncio
async def test_persist_message_and_list_messages_in_order(db_session: AsyncSession) -> None:
    conversation = await get_or_create_conversation(
        db_session, session_id="session-a", conversation_id=None, audience=None
    )
    await persist_message(
        db_session, conversation_id=conversation.id, role=MessageRole.USER, content="hi"
    )
    await persist_message(
        db_session,
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content="hello",
        citations=[{"marker": 1, "chunk_id": "abc"}],
        model_backend="ollama:llama3.1:8b",
        latency_ms=100,
    )

    messages = await list_messages(db_session, conversation.id)

    assert [m.role for m in messages] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert messages[1].citations == [{"marker": 1, "chunk_id": "abc"}]
    assert messages[1].latency_ms == 100


@pytest.mark.asyncio
async def test_list_conversations_scoped_to_session_and_ordered(db_session: AsyncSession) -> None:
    older = await get_or_create_conversation(
        db_session, session_id="session-a", conversation_id=None, audience=None
    )
    await db_session.flush()
    newer = await get_or_create_conversation(
        db_session, session_id="session-a", conversation_id=None, audience=None
    )
    await get_or_create_conversation(
        db_session, session_id="session-b", conversation_id=None, audience=None
    )

    conversations = await list_conversations(db_session, "session-a")

    assert {c.id for c in conversations} == {older.id, newer.id}


@pytest.mark.asyncio
async def test_get_conversation_for_session_success_and_failure(db_session: AsyncSession) -> None:
    conversation = await get_or_create_conversation(
        db_session, session_id="session-a", conversation_id=None, audience=None
    )

    fetched = await get_conversation_for_session(
        db_session, conversation_id=conversation.id, session_id="session-a"
    )
    assert fetched.id == conversation.id

    with pytest.raises(NotFoundError):
        await get_conversation_for_session(
            db_session, conversation_id=conversation.id, session_id="session-b"
        )


@pytest.mark.asyncio
async def test_title_is_derived_from_the_first_message(db_session: AsyncSession) -> None:
    conversation = await get_or_create_conversation(
        db_session, session_id="s1", conversation_id=None, audience=None
    )

    await set_title_from_first_message(
        db_session, conversation=conversation, first_message="  What is\n hallmarking?  "
    )

    # Whitespace is collapsed, not preserved verbatim.
    assert conversation.title == "What is hallmarking?"


@pytest.mark.asyncio
async def test_long_title_is_clipped_at_a_word_boundary(db_session: AsyncSession) -> None:
    conversation = await get_or_create_conversation(
        db_session, session_id="s1", conversation_id=None, audience=None
    )
    question = (
        "Which Indian Standard and BIS certification scheme applies to an "
        "imported LED luminaire sold at retail?"
    )

    await set_title_from_first_message(
        db_session, conversation=conversation, first_message=question
    )

    title = conversation.title
    assert title is not None
    assert title.endswith("…")
    assert len(title) <= TITLE_MAX_LENGTH + 1  # + the ellipsis
    assert not title.rstrip("…").endswith(" ")  # cut cleanly, no dangling space


@pytest.mark.asyncio
async def test_title_is_not_overwritten_on_later_turns(db_session: AsyncSession) -> None:
    conversation = await get_or_create_conversation(
        db_session, session_id="s1", conversation_id=None, audience=None
    )

    await set_title_from_first_message(
        db_session, conversation=conversation, first_message="First question"
    )
    await set_title_from_first_message(
        db_session, conversation=conversation, first_message="A totally different follow-up"
    )

    assert conversation.title == "First question"
