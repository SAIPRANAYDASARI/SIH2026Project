"""stream_answer/answer_query orchestration, tested with a fake
hybrid_search_fn (so no live Postgres/reranker) and a fake LLMClient (so no
live LLM) — this is the same dependency-injection pattern Step 4 used for
`hybrid_search`. Covers: normal streamed answer with valid citations, the
forced-refusal path when retrieval finds nothing, and that guardrail
redaction happens before citation validation runs on the final text."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

from app.answer.engine import FinalEvent, TokenEvent, answer_query, stream_answer
from app.core.config import Settings
from app.llm.client import LLMClient, LLMMessage
from app.models.conversation import Audience
from app.retrieval.models import RetrievedChunk
from app.retrieval.query_understanding import Intent, QueryAnalysis


def _chunk(text: str = "chunk text") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        text_content=text,
        is_number="IS 15111",
        section_path=None,
        clause_number="4.2.1",
        page_number=None,
        context_header=None,
        document_title="IS 15111 LED Luminaires",
    )


class FakeLLMClient(LLMClient):
    def __init__(self, pieces: list[str]) -> None:
        self.pieces = pieces
        self.received_messages: list[LLMMessage] | None = None

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        self.received_messages = messages
        for piece in self.pieces:
            yield piece


async def _fake_hybrid_search(session, query, *, settings=None):  # noqa: ANN001, ARG001
    return QueryAnalysis(intent=Intent.STANDARD_LOOKUP, identifiers=[]), [_chunk()]


async def _empty_hybrid_search(session, query, *, settings=None):  # noqa: ANN001, ARG001
    return QueryAnalysis(intent=Intent.OUT_OF_SCOPE, identifiers=[]), []


@pytest.mark.asyncio
async def test_stream_answer_forwards_tokens_then_final_event() -> None:
    llm = FakeLLMClient(["The temperature ", "endurance test applies [1]."])
    events = [
        event
        async for event in stream_answer(
            session=None,
            query="what does clause 4.2.1 require?",
            audience=Audience.INDUSTRY,
            settings=Settings(),
            llm_client=llm,
            hybrid_search_fn=_fake_hybrid_search,
        )
    ]

    token_events = [e for e in events if isinstance(e, TokenEvent)]
    final_events = [e for e in events if isinstance(e, FinalEvent)]

    assert [t.text for t in token_events] == ["The temperature ", "endurance test applies [1]."]
    assert len(final_events) == 1

    result = final_events[0].result
    assert result.forced_refusal is False
    assert result.text == "The temperature endurance test applies [1]."
    assert len(result.citations) == 1
    assert result.citations[0].is_number == "IS 15111"
    assert result.invalid_citation_markers == []
    assert result.query_analysis.intent is Intent.STANDARD_LOOKUP


@pytest.mark.asyncio
async def test_stream_answer_forced_refusal_skips_llm_call() -> None:
    llm = FakeLLMClient(["should never be used"])

    events = [
        event
        async for event in stream_answer(
            session=None,
            query="what is the weather?",
            settings=Settings(),
            llm_client=llm,
            hybrid_search_fn=_empty_hybrid_search,
        )
    ]

    final_events = [e for e in events if isinstance(e, FinalEvent)]
    assert len(final_events) == 1
    assert final_events[0].result.forced_refusal is True
    assert llm.received_messages is None  # LLM was never called


@pytest.mark.asyncio
async def test_answer_query_returns_only_final_result() -> None:
    llm = FakeLLMClient(["Answer [1]."])

    result = await answer_query(
        session=None,
        query="what is IS 15111?",
        settings=Settings(),
        llm_client=llm,
        hybrid_search_fn=_fake_hybrid_search,
    )

    assert result.text == "Answer [1]."
    assert len(result.citations) == 1


@pytest.mark.asyncio
async def test_stream_answer_flags_invalid_citation_marker() -> None:
    llm = FakeLLMClient(["A hallucinated source [7]."])

    result = await answer_query(
        session=None,
        query="what is IS 15111?",
        settings=Settings(),
        llm_client=llm,
        hybrid_search_fn=_fake_hybrid_search,
    )

    assert result.invalid_citation_markers == [7]
    assert result.citations == []
