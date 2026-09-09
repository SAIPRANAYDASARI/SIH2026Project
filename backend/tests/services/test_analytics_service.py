"""app.services.analytics_service against a real in-memory SQLite
Conversation/Message schema."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.conversation import Audience, Conversation, Message, MessageRole
from app.services.analytics_service import compute_summary


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
async def test_empty_dataset_returns_zeroes(db_session: AsyncSession) -> None:
    summary = await compute_summary(db_session)
    assert summary.total_conversations == 0
    assert summary.total_assistant_messages == 0
    assert summary.forced_refusal_rate == 0.0
    assert summary.average_latency_ms is None


@pytest.mark.asyncio
async def test_aggregates_intent_guardrails_refusals_feedback(
    db_session: AsyncSession,
) -> None:
    conv = Conversation(session_id="s1", audience=Audience.CONSUMER)
    db_session.add(conv)
    await db_session.flush()

    db_session.add_all(
        [
            Message(
                conversation_id=conv.id,
                role=MessageRole.ASSISTANT,
                content="a",
                intent="standard_lookup",
                retrieval_debug={"guardrail_violations": [], "forced_refusal": False},
                latency_ms=100,
                feedback_rating=1,
            ),
            Message(
                conversation_id=conv.id,
                role=MessageRole.ASSISTANT,
                content="b",
                intent="standard_lookup",
                retrieval_debug={
                    "guardrail_violations": ["verbatim_redaction"],
                    "forced_refusal": False,
                },
                latency_ms=200,
                feedback_rating=-1,
            ),
            Message(
                conversation_id=conv.id,
                role=MessageRole.ASSISTANT,
                content="c",
                intent="out_of_scope",
                retrieval_debug={"guardrail_violations": [], "forced_refusal": True},
                latency_ms=None,
            ),
        ]
    )
    await db_session.flush()

    summary = await compute_summary(db_session)
    assert summary.total_conversations == 1
    assert summary.total_assistant_messages == 3
    assert summary.guardrail_violation_count == 1
    assert summary.forced_refusal_count == 1
    assert summary.forced_refusal_rate == pytest.approx(1 / 3)
    assert summary.average_latency_ms == 150.0
    assert summary.feedback_thumbs_up == 1
    assert summary.feedback_thumbs_down == 1
    assert summary.feedback_response_rate == pytest.approx(2 / 3)
    intents = {ic.intent: ic.count for ic in summary.intent_distribution}
    assert intents["standard_lookup"] == 2
    assert intents["out_of_scope"] == 1
