"""Wires retrieval (Step 4) to the LLM adapter (`app.llm`) to produce a
grounded, cited answer — the brief's Step 5 scope: "prompts, citation
validator, guardrails, streaming." No API/persistence here (Step 6) and no
rules-engine integration (Step 8) — this module answers one question given
one already-open DB session and returns/streams the result.

Two halves meet here on purpose:

- Token-by-token streaming from the LLM, forwarded live as `TokenEvent`s,
  so a caller (the future SSE endpoint, or this module's CLI) can render
  partial output as it arrives.
- Citation validation and guardrail enforcement, which both need the
  *complete* answer text and so can only run once generation finishes —
  emitted as a single terminal `FinalEvent` carrying the guardrail-redacted
  text, resolved citations, and retrieval debug info to persist
  (`Message.citations` / `Message.retrieval_debug`, Step 6).

If retrieval finds nothing at all, the LLM is never called — see
`app.answer.guardrails.requires_forced_refusal`.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.answer.citations import Citation, CitationValidationResult, validate_citations
from app.answer.guardrails import (
    GuardrailReport,
    enforce_guardrails,
    forced_refusal_text,
    requires_forced_refusal,
)
from app.answer.prompts import build_messages
from app.core.config import Settings, get_settings
from app.llm.client import LLMClient, get_llm_client
from app.models.conversation import Audience
from app.retrieval.hybrid import hybrid_search
from app.retrieval.models import RetrievedChunk
from app.retrieval.query_understanding import QueryAnalysis


@dataclass(frozen=True)
class TokenEvent:
    text: str


@dataclass
class AnswerResult:
    text: str
    citations: list[Citation]
    invalid_citation_markers: list[int]
    guardrail_violations: list[str]
    query_analysis: QueryAnalysis
    chunks: list[RetrievedChunk]
    model_backend: str
    latency_ms: int
    forced_refusal: bool = False


@dataclass(frozen=True)
class FinalEvent:
    result: AnswerResult


AnswerEvent = TokenEvent | FinalEvent

HybridSearchFn = Callable[..., Awaitable[tuple[QueryAnalysis, list[RetrievedChunk]]]]


def _model_backend_label(settings: Settings) -> str:
    if settings.llm_backend == "ollama":
        return f"ollama:{settings.ollama_model}"
    return f"{settings.hosted_llm_provider}:{settings.hosted_llm_model}"


async def stream_answer(
    session: AsyncSession,
    query: str,
    *,
    audience: Audience = Audience.CONSUMER,
    target_language: str = "en",
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
    hybrid_search_fn: HybridSearchFn = hybrid_search,
) -> AsyncIterator[AnswerEvent]:
    settings = settings or get_settings()
    started = time.monotonic()

    query_analysis, chunks = await hybrid_search_fn(session, query, settings=settings)

    if requires_forced_refusal(chunks):
        refusal_text = forced_refusal_text(target_language)
        yield TokenEvent(text=refusal_text)
        yield FinalEvent(
            result=AnswerResult(
                text=refusal_text,
                citations=[],
                invalid_citation_markers=[],
                guardrail_violations=[],
                query_analysis=query_analysis,
                chunks=chunks,
                model_backend=_model_backend_label(settings),
                latency_ms=int((time.monotonic() - started) * 1000),
                forced_refusal=True,
            )
        )
        return

    llm_client = llm_client or get_llm_client(settings)
    messages = build_messages(query, chunks, audience=audience, target_language=target_language)

    pieces: list[str] = []
    async for delta in llm_client.stream(messages):
        pieces.append(delta)
        yield TokenEvent(text=delta)

    raw_text = "".join(pieces)
    guardrail_report: GuardrailReport = enforce_guardrails(raw_text, chunks)
    citation_result: CitationValidationResult = validate_citations(
        guardrail_report.redacted_text, chunks
    )

    yield FinalEvent(
        result=AnswerResult(
            text=guardrail_report.redacted_text,
            citations=citation_result.citations,
            invalid_citation_markers=citation_result.invalid_markers,
            guardrail_violations=guardrail_report.violations,
            query_analysis=query_analysis,
            chunks=chunks,
            model_backend=_model_backend_label(settings),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    )


async def answer_query(
    session: AsyncSession,
    query: str,
    *,
    audience: Audience = Audience.CONSUMER,
    target_language: str = "en",
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
    hybrid_search_fn: HybridSearchFn = hybrid_search,
) -> AnswerResult:
    """Non-streaming convenience wrapper — drains `stream_answer` and
    returns the final result. Used by the CLI (with output printed live via
    the streamed events instead) and will be used by the Step-12 evaluation
    harness, which only needs the final answer, not the token stream."""
    result: AnswerResult | None = None
    async for event in stream_answer(
        session,
        query,
        audience=audience,
        target_language=target_language,
        settings=settings,
        llm_client=llm_client,
        hybrid_search_fn=hybrid_search_fn,
    ):
        if isinstance(event, FinalEvent):
            result = event.result
    assert result is not None  # FinalEvent is always yielded exactly once
    return result
