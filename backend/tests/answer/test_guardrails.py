"""enforce_guardrails redacts long verbatim reproductions of a retrieved
chunk (the "never redistribute full standard text" legal constraint) but
leaves short quotes and paraphrase alone; requires_forced_refusal signals
when there's nothing retrieved to ground an answer in at all."""

from __future__ import annotations

import uuid

from app.answer.guardrails import (
    MAX_VERBATIM_WORDS,
    enforce_guardrails,
    requires_forced_refusal,
)
from app.retrieval.models import RetrievedChunk


def _chunk(text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        text_content=text,
        is_number="IS 15111",
        section_path=None,
        clause_number="4.2.1",
        page_number=None,
        context_header=None,
    )


def test_requires_forced_refusal_true_when_no_chunks() -> None:
    assert requires_forced_refusal([]) is True


def test_requires_forced_refusal_false_when_chunks_present() -> None:
    assert requires_forced_refusal([_chunk("some text")]) is False


def test_short_quote_is_not_redacted() -> None:
    chunk_text = "the luminaire shall withstand a temperature endurance test"
    answer = f"According to the standard, {chunk_text} as required."
    report = enforce_guardrails(answer, [_chunk(chunk_text)])

    assert report.verbatim_redactions == 0
    assert report.redacted_text == answer
    assert report.violations == []


def test_long_verbatim_reproduction_is_redacted() -> None:
    long_run = " ".join(f"word{i}" for i in range(MAX_VERBATIM_WORDS + 10))
    chunk_text = f"prefix text here {long_run} suffix text here"
    answer = f"The requirement states: {long_run} [1]"

    report = enforce_guardrails(answer, [_chunk(chunk_text)])

    assert report.verbatim_redactions == 1
    assert "omitted" in report.redacted_text.lower()
    assert long_run not in report.redacted_text
    assert len(report.violations) == 1


def test_no_chunks_means_no_redaction_possible() -> None:
    answer = "Some answer with no grounding at all."
    report = enforce_guardrails(answer, [])
    assert report.redacted_text == answer
    assert report.verbatim_redactions == 0
