"""system_prompt selects the right audience persona; build_messages numbers
context blocks in the [N] convention the citation validator later parses."""

from __future__ import annotations

import uuid

from app.answer.prompts import build_messages, format_context_blocks, system_prompt
from app.models.conversation import Audience
from app.retrieval.models import RetrievedChunk


def _chunk(text: str, is_number: str | None = "IS 15111") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        text_content=text,
        is_number=is_number,
        section_path="4.2 Requirements",
        clause_number="4.2.1",
        page_number=None,
        context_header=None,
        document_title="IS 15111 LED Luminaires",
    )


def test_system_prompt_differs_by_audience() -> None:
    industry = system_prompt(Audience.INDUSTRY)
    consumer = system_prompt(Audience.CONSUMER)
    assert "industry" in industry.lower()
    assert "consumer" in consumer.lower()
    assert industry != consumer


def test_format_context_blocks_numbers_sequentially() -> None:
    blocks = format_context_blocks([_chunk("first"), _chunk("second")])
    assert "[1]" in blocks
    assert "[2]" in blocks
    assert blocks.index("[1]") < blocks.index("[2]")


def test_format_context_blocks_empty_says_no_context() -> None:
    blocks = format_context_blocks([])
    assert "no matching context" in blocks.lower()


def test_build_messages_includes_system_and_user_turn() -> None:
    messages = build_messages("what is IS 15111?", [_chunk("text")], audience=Audience.CONSUMER)
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert "what is IS 15111?" in messages[1].content
    assert "[1]" in messages[1].content


def test_system_prompt_defaults_to_english() -> None:
    prompt = system_prompt(Audience.CONSUMER)
    assert "simple, plain English" in prompt


def test_system_prompt_hindi_instructs_native_hindi_answer() -> None:
    prompt = system_prompt(Audience.CONSUMER, target_language="hi")
    assert "Hindi" in prompt
    assert "सरल हिंदी" in prompt
    # Citation markers must not be reformatted/translated.
    assert "[1]" in prompt


def test_system_prompt_unknown_language_falls_back_to_english() -> None:
    prompt = system_prompt(Audience.CONSUMER, target_language="fr")
    assert "simple, plain English" in prompt


def test_build_messages_passes_target_language_to_system_prompt() -> None:
    messages = build_messages(
        "what is hallmarking?",
        [_chunk("text")],
        audience=Audience.CONSUMER,
        target_language="hi",
    )
    assert "Hindi" in messages[0].content
