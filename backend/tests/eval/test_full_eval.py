"""app.eval.full_eval against fake hybrid_search_fn/LLMClient — same
dependency-injection pattern as tests/answer/test_engine.py, so this
exercises the harness's metric computation with no live Postgres/LLM."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

from app.core.config import Settings
from app.eval.full_eval import run_full_eval
from app.eval.golden_set import GoldenQuestion
from app.llm.client import LLMClient, LLMMessage
from app.models.conversation import Audience
from app.retrieval.models import RetrievedChunk
from app.retrieval.query_understanding import Intent, QueryAnalysis


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        text_content="chunk text",
        is_number="IS 15111",
        section_path=None,
        clause_number="4.2.1",
        page_number=None,
        context_header=None,
        document_title="IS 15111 LED Luminaires",
    )


class ScriptedLLMClient(LLMClient):
    """Yields a different canned answer per call, in call order."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = list(answers)

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        yield self._answers.pop(0)


async def _hybrid_search_with_chunk(session, query, *, settings=None):  # noqa: ANN001, ARG001
    return QueryAnalysis(intent=Intent.STANDARD_LOOKUP, identifiers=[]), [_chunk()]


async def _hybrid_search_empty(session, query, *, settings=None):  # noqa: ANN001, ARG001
    return QueryAnalysis(intent=Intent.OUT_OF_SCOPE, identifiers=[]), []


@pytest.mark.asyncio
async def test_empty_golden_set_returns_zeroed_metrics() -> None:
    metrics = await run_full_eval(object(), [], settings=Settings())  # type: ignore[arg-type]
    assert metrics.question_count == 0
    assert metrics.citation_precision == 0.0


@pytest.mark.asyncio
async def test_correct_citation_and_intent_scores_perfectly() -> None:
    question = GoldenQuestion(
        query="What is IS 15111 about?",
        audience=Audience.CONSUMER,
        expected_intent=Intent.STANDARD_LOOKUP,
        expects_citation=True,
    )
    llm = ScriptedLLMClient(["It covers LED luminaires [1]."])

    metrics = await run_full_eval(
        object(),  # type: ignore[arg-type]
        [question],
        settings=Settings(),
        llm_client=llm,
        hybrid_search_fn=_hybrid_search_with_chunk,
    )

    assert metrics.question_count == 1
    assert metrics.intent_accuracy == 1.0
    assert metrics.citation_precision == 1.0
    assert metrics.average_latency_ms >= 0


@pytest.mark.asyncio
async def test_hallucinated_citation_lowers_precision() -> None:
    question = GoldenQuestion(
        query="What is IS 15111 about?",
        audience=Audience.CONSUMER,
        expected_intent=Intent.STANDARD_LOOKUP,
        expects_citation=True,
    )
    llm = ScriptedLLMClient(["It covers LED luminaires [7]."])  # [7] doesn't exist

    metrics = await run_full_eval(
        object(),  # type: ignore[arg-type]
        [question],
        settings=Settings(),
        llm_client=llm,
        hybrid_search_fn=_hybrid_search_with_chunk,
    )

    assert metrics.citation_precision == 0.0
    assert metrics.per_question[0].citation_ok is False


@pytest.mark.asyncio
async def test_expected_refusal_scores_correctly() -> None:
    question = GoldenQuestion(
        query="What's the weather like?",
        audience=Audience.CONSUMER,
        expected_intent=Intent.OUT_OF_SCOPE,
        expects_citation=False,
        expects_refusal=True,
    )
    llm = ScriptedLLMClient(["should never be called"])

    metrics = await run_full_eval(
        object(),  # type: ignore[arg-type]
        [question],
        settings=Settings(),
        llm_client=llm,
        hybrid_search_fn=_hybrid_search_empty,
    )

    assert metrics.forced_refusal_accuracy == 1.0
    assert metrics.false_refusal_rate == 0.0


@pytest.mark.asyncio
async def test_false_refusal_is_flagged() -> None:
    """An answerable question that gets refused should count against
    false_refusal_rate, not forced_refusal_accuracy (which only measures
    questions where refusal was the *correct* behavior)."""
    question = GoldenQuestion(
        query="What is IS 15111 about?",
        audience=Audience.CONSUMER,
        expected_intent=Intent.STANDARD_LOOKUP,
        expects_citation=True,
        expects_refusal=False,
    )
    llm = ScriptedLLMClient(["should never be called"])

    metrics = await run_full_eval(
        object(),  # type: ignore[arg-type]
        [question],
        settings=Settings(),
        llm_client=llm,
        hybrid_search_fn=_hybrid_search_empty,  # retrieval finds nothing -> forced refusal
    )

    assert metrics.false_refusal_rate == 1.0
    assert metrics.per_question[0].refusal_correct is False
