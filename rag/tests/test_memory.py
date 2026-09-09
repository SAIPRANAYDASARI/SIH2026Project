"""Conversation memory.

Memory makes follow-up questions work ("what about for imports?"), which is
how people actually talk. The risk it introduces is that an earlier answer
starts acting like evidence — a claim made in turn one gets restated in turn
three as though a document backed it. So history is carried for *interpreting*
the question and for *retrieval*, and is labelled in the prompt as context
rather than source. The citation validator still runs on top.
"""

from __future__ import annotations

import pytest

from rag import answer as answer_mod
from rag.answer import (
    HISTORY_CHARS,
    HISTORY_TURNS,
    answer_question,
    expand_query,
    format_history,
    needs_context,
)
from rag.tests.test_answer import make_hit


# ── Detecting a follow-up ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "question",
    [
        "What about for foreign manufacturers?",
        "And for imports?",
        "What about that scheme?",
        "Is it valid for two years?",
        "How much?",
        "Why?",
        "the same for jewellery?",
    ],
)
def test_recognises_questions_that_depend_on_context(question):
    assert needs_context(question) is True


@pytest.mark.parametrize(
    "question",
    [
        "On what grounds can BIS cancel a licence under Regulation 11?",
        "How long is a CRS registration valid before renewal is required?",
        "What documents must a foreign manufacturer submit for FMCS?",
    ],
)
def test_self_contained_questions_are_left_alone(question):
    assert needs_context(question) is False


# ── Query expansion ──────────────────────────────────────────────────────

def test_follow_up_inherits_the_previous_subject():
    """'What about for imports?' has nothing searchable on its own."""
    history = [
        {"role": "user", "content": "How long is a CRS registration valid?"},
        {"role": "assistant", "content": "Two years. [S1]"},
    ]
    expanded = expand_query("What about for imports?", history)
    assert "CRS registration" in expanded
    assert "imports" in expanded


def test_self_contained_question_is_not_polluted_by_earlier_topic():
    history = [
        {"role": "user", "content": "How much is the hallmarking fee?"},
        {"role": "assistant", "content": "See Schedule IV. [S1]"},
    ]
    q = "What documents must a foreign manufacturer submit for FMCS?"
    assert expand_query(q, history) == q


def test_expansion_without_history_is_a_no_op():
    assert expand_query("What about imports?", None) == "What about imports?"
    assert expand_query("What about imports?", []) == "What about imports?"


def test_expansion_ignores_assistant_only_history():
    history = [{"role": "assistant", "content": "Some earlier answer."}]
    assert expand_query("What about it?", history) == "What about it?"


# ── History rendering ────────────────────────────────────────────────────

def test_history_is_labelled_as_context_not_evidence():
    block = format_history([{"role": "user", "content": "hi"}])
    assert "not a source" in block.lower()
    assert "never cite it" in block.lower()


def test_history_is_bounded():
    long_history = [
        {"role": "user", "content": f"question number {i} " + "x" * 900}
        for i in range(20)
    ]
    block = format_history(long_history)
    assert block.count("User:") <= HISTORY_TURNS * 2
    for line in block.splitlines():
        assert len(line) <= HISTORY_CHARS + 40


def test_empty_history_adds_nothing():
    assert format_history(None) == ""
    assert format_history([]) == ""
    assert format_history([{"role": "user", "content": ""}]) == ""


# ── End-to-end wiring ────────────────────────────────────────────────────

def test_history_reaches_the_prompt(monkeypatch):
    seen = {}

    def capture(messages, **k):
        seen["user"] = messages[1]["content"]
        return answer_mod.llm.LLMResponse("The fee is in Schedule IV. [S1]", "m")

    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [make_hit()])
    monkeypatch.setattr(answer_mod.llm, "chat", capture)

    answer_question(
        "What about for imports?",
        history=[{"role": "user", "content": "How long is a CRS registration valid?"}],
    )
    assert "CRS registration" in seen["user"]
    assert "CONVERSATION SO FAR" in seen["user"]
    # Sources must still be present and come after the context.
    assert "SOURCES" in seen["user"]
    assert seen["user"].index("CONVERSATION SO FAR") < seen["user"].index("SOURCES")


def test_retrieval_uses_the_expanded_question(monkeypatch):
    queries = []

    def spy(q, **k):
        queries.append(q)
        return [make_hit()]

    monkeypatch.setattr(answer_mod, "search", spy)
    monkeypatch.setattr(
        answer_mod.llm, "chat",
        lambda *a, **k: answer_mod.llm.LLMResponse("Answer. [S1]", "m"),
    )
    answer_question(
        "And for imports?",
        history=[{"role": "user", "content": "What is the hallmarking fee?"}],
    )
    assert "hallmarking fee" in queries[0]


def test_prompt_forbids_treating_history_as_a_source():
    prompt = answer_mod.SYSTEM_PROMPT.lower()
    assert "not a source of facts" in prompt
    assert "never cite an earlier answer" in prompt


def test_answers_work_unchanged_without_history(monkeypatch):
    """Memory is additive — a first question must behave exactly as before."""
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [make_hit()])
    monkeypatch.setattr(
        answer_mod.llm, "chat",
        lambda *a, **k: answer_mod.llm.LLMResponse("Grounded answer. [S1]", "m"),
    )
    result = answer_question("How long is a CRS registration valid?")
    assert result.grounded and result.cited == [1]
