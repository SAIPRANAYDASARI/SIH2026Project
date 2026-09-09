"""Integration tests for POST /chat and GET /conversations(/…/messages)
against a real (in-memory SQLite) Conversation/Message schema — driven
through the actual ASGI app so SSE framing, cookie issuance, and
persistence are all exercised together.

`app.answer.engine.stream_answer` is monkeypatched to a fake async
generator rather than re-verified here — its own behavior (streaming,
citation validation, guardrails) is covered by `tests/answer/test_engine.py`
(Step 5). This layer's job is the API/persistence wiring around it: does a
session cookie get issued and honored, do both turns get persisted, does
the SSE stream carry the right event types in the right order, and is
conversation history correctly scoped to the caller's session and nobody
else's.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.api.v1.chat as chat_module
from app.answer.engine import AnswerResult, FinalEvent, TokenEvent
from app.db.session import get_db
from app.main import app
from app.models.conversation import Conversation, Message
from app.retrieval.query_understanding import Intent, QueryAnalysis


async def _fake_stream_answer(session, query, *, audience, settings=None, **_):  # noqa: ANN001, ARG001
    yield TokenEvent(text="Hello ")
    yield TokenEvent(text="world [1].")
    yield FinalEvent(
        result=AnswerResult(
            text="Hello world [1].",
            citations=[],
            invalid_citation_markers=[],
            guardrail_violations=[],
            query_analysis=QueryAnalysis(intent=Intent.STANDARD_LOOKUP, identifiers=[]),
            chunks=[],
            model_backend="fake:test-model",
            latency_ms=42,
        )
    )


@pytest_asyncio.fixture
async def chat_session_maker() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Conversation.__table__.create)
        await conn.run_sync(Message.__table__.create)
    session_maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    yield session_maker
    await engine.dispose()


@pytest_asyncio.fixture
async def chat_client(
    chat_session_maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[AsyncClient, None]:
    monkeypatch.setattr(chat_module, "AsyncSessionLocal", chat_session_maker)
    monkeypatch.setattr(chat_module, "stream_answer", _fake_stream_answer)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with chat_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _parse_sse_events(raw_text: str) -> list[tuple[str, str]]:
    events = []
    for block in raw_text.strip().split("\n\n"):
        lines = block.splitlines()
        event_line = next(line for line in lines if line.startswith("event:"))
        data_line = next(line for line in lines if line.startswith("data:"))
        events.append(
            (event_line.removeprefix("event:").strip(), data_line.removeprefix("data:").strip())
        )
    return events


@pytest.mark.asyncio
async def test_chat_streams_conversation_token_and_final_events(chat_client: AsyncClient) -> None:
    response = await chat_client.post("/api/v1/chat", json={"message": "what is IS 15111?"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "ms_session" in response.cookies

    event_types = [event for event, _ in _parse_sse_events(response.text)]
    assert event_types == ["conversation", "token", "token", "final"]


@pytest.mark.asyncio
async def test_chat_persists_user_and_assistant_messages(chat_client: AsyncClient) -> None:
    response = await chat_client.post("/api/v1/chat", json={"message": "what is IS 15111?"})
    cookies = response.cookies

    events = _parse_sse_events(response.text)
    conversation_event = next(data for event, data in events if event == "conversation")
    conversation_id = conversation_event.split('"')[3]

    chat_client.cookies.update(cookies)
    history_response = await chat_client.get(f"/api/v1/conversations/{conversation_id}/messages")

    assert history_response.status_code == 200
    messages = history_response.json()
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "what is IS 15111?"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Hello world [1]."
    assert messages[1]["model_backend"] == "fake:test-model"


@pytest.mark.asyncio
async def test_conversations_list_empty_without_session_cookie(chat_client: AsyncClient) -> None:
    response = await chat_client.get("/api/v1/conversations")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_messages_endpoint_404s_without_session_cookie(chat_client: AsyncClient) -> None:
    response = await chat_client.get(f"/api/v1/conversations/{uuid.uuid4()}/messages")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_messages_endpoint_404s_for_another_sessions_conversation(
    chat_client: AsyncClient,
) -> None:
    first = await chat_client.post("/api/v1/chat", json={"message": "hello"})
    conversation_id = _parse_sse_events(first.text)[0][1].split('"')[3]

    # A different (invalid/unsigned) cookie is treated the same as no
    # cookie at all — no access to the first session's conversation.
    chat_client.cookies.update({"ms_session": "not-a-valid-signed-cookie"})
    other_response = await chat_client.get(f"/api/v1/conversations/{conversation_id}/messages")
    assert other_response.status_code == 404


@pytest.mark.asyncio
async def test_conversations_list_scoped_to_session_cookie(chat_client: AsyncClient) -> None:
    response = await chat_client.post("/api/v1/chat", json={"message": "hello"})
    cookies = response.cookies

    chat_client.cookies.update(cookies)
    list_response = await chat_client.get("/api/v1/conversations")
    assert list_response.status_code == 200
    conversations = list_response.json()
    assert len(conversations) == 1
    assert conversations[0]["audience"] == "consumer"


@pytest.mark.asyncio
async def test_submit_feedback_updates_message(chat_client: AsyncClient) -> None:
    response = await chat_client.post("/api/v1/chat", json={"message": "hello"})
    events = _parse_sse_events(response.text)
    conversation_id = events[0][1].split('"')[3]
    final_data = events[-1][1]
    message_id = final_data.split('"message_id": "')[1].split('"')[0]

    chat_client.cookies.update(response.cookies)
    feedback_response = await chat_client.patch(
        f"/api/v1/conversations/{conversation_id}/messages/{message_id}/feedback",
        json={"rating": 1, "comment": "Helpful!"},
    )
    assert feedback_response.status_code == 200

    messages = await chat_client.get(f"/api/v1/conversations/{conversation_id}/messages")
    assistant_message = next(m for m in messages.json() if m["role"] == "assistant")
    assert assistant_message["id"] == message_id


@pytest.mark.asyncio
async def test_submit_feedback_404s_without_session_cookie(chat_client: AsyncClient) -> None:
    response = await chat_client.patch(
        f"/api/v1/conversations/{uuid.uuid4()}/messages/{uuid.uuid4()}/feedback",
        json={"rating": 1},
    )
    assert response.status_code == 404
