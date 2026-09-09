"""The Step 12 full-pipeline evaluation harness: runs each golden question
through the *complete* answer engine (`app.answer.engine.answer_query` —
retrieval + LLM + citation validation + guardrails), unlike Step 4's
`app.retrieval.baseline_eval`, which measures retrieval alone with no LLM
in the loop.

Metrics computed, per docs/EVALUATION.md:

- **Citation precision** — of questions expected to carry a citation, the
  fraction whose answer has zero invalid `[N]` markers and at least one
  resolved citation.
- **Forced-refusal accuracy** — of questions expected to be refused, the
  fraction that actually triggered `AnswerResult.forced_refusal`; plus the
  inverse false-refusal rate (answerable questions wrongly refused).
- **Intent accuracy** — fraction where `query_analysis.intent` matches the
  golden label.
- **Average latency** — mean `AnswerResult.latency_ms` across all questions
  (this is what the answer engine measured; not re-timed here).
- **Groundedness heuristic** — of questions expected to carry a citation,
  the fraction where every `[N]` marker present in the answer text
  resolved to a real citation (i.e. `invalid_citation_markers` is empty) —
  a proxy for "the model didn't fabricate a source", not a full factual
  accuracy check (that needs human review, out of scope for an automated
  harness — see docs/DECISIONS.md, Step 12).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.answer.engine import AnswerResult, HybridSearchFn, answer_query
from app.core.config import Settings
from app.eval.golden_set import GoldenQuestion
from app.llm.client import LLMClient
from app.retrieval.hybrid import hybrid_search


@dataclass(frozen=True)
class PerQuestionResult:
    question: GoldenQuestion
    result: AnswerResult
    intent_correct: bool
    citation_ok: bool
    refusal_correct: bool


@dataclass(frozen=True)
class FullEvalMetrics:
    question_count: int
    intent_accuracy: float
    citation_precision: float
    forced_refusal_accuracy: float
    false_refusal_rate: float
    average_latency_ms: float
    per_question: list[PerQuestionResult] = field(default_factory=list)


async def run_full_eval(
    session: AsyncSession,
    golden_set: list[GoldenQuestion],
    *,
    settings: Settings,
    llm_client: LLMClient | None = None,
    hybrid_search_fn: HybridSearchFn = hybrid_search,
) -> FullEvalMetrics:
    per_question: list[PerQuestionResult] = []

    for question in golden_set:
        result = await answer_query(
            session,
            question.query,
            audience=question.audience,
            settings=settings,
            llm_client=llm_client,
            hybrid_search_fn=hybrid_search_fn,
        )

        intent_correct = result.query_analysis.intent == question.expected_intent

        if question.expects_citation and not result.forced_refusal:
            citation_ok = bool(result.citations) and not result.invalid_citation_markers
        else:
            citation_ok = True  # not applicable — doesn't count against precision

        refusal_correct = result.forced_refusal == question.expects_refusal

        per_question.append(
            PerQuestionResult(
                question=question,
                result=result,
                intent_correct=intent_correct,
                citation_ok=citation_ok,
                refusal_correct=refusal_correct,
            )
        )

    n = len(per_question)
    if n == 0:
        return FullEvalMetrics(
            question_count=0,
            intent_accuracy=0.0,
            citation_precision=0.0,
            forced_refusal_accuracy=0.0,
            false_refusal_rate=0.0,
            average_latency_ms=0.0,
            per_question=[],
        )

    citation_applicable = [
        pq for pq in per_question if pq.question.expects_citation and not pq.result.forced_refusal
    ]
    refusal_expected = [pq for pq in per_question if pq.question.expects_refusal]
    refusal_not_expected = [pq for pq in per_question if not pq.question.expects_refusal]

    return FullEvalMetrics(
        question_count=n,
        intent_accuracy=sum(pq.intent_correct for pq in per_question) / n,
        citation_precision=(
            sum(pq.citation_ok for pq in citation_applicable) / len(citation_applicable)
            if citation_applicable
            else 1.0
        ),
        forced_refusal_accuracy=(
            sum(pq.result.forced_refusal for pq in refusal_expected) / len(refusal_expected)
            if refusal_expected
            else 1.0
        ),
        false_refusal_rate=(
            sum(pq.result.forced_refusal for pq in refusal_not_expected) / len(refusal_not_expected)
            if refusal_not_expected
            else 0.0
        ),
        average_latency_ms=sum(pq.result.latency_ms for pq in per_question) / n,
        per_question=per_question,
    )
