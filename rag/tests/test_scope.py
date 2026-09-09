"""Domain gate.

Asked "who is Virat Kohli", the assistant produced a full cricket biography
under a BIS banner. A compliance tool that will discuss anything reads as a
generic chatbot wearing a government badge, so off-domain questions are now
refused before retrieval and before any model call.

The gate is asymmetric on purpose. Refusing a real compliance question harms
someone who needs an answer; answering a trivia question is only embarrassing.
So the false-negative tests here matter more than the false-positive ones.
"""

from __future__ import annotations

import pytest

from rag import answer as answer_mod
from rag.answer import answer_question
from rag.scope import check_scope, refusal_text


OFF_DOMAIN = [
    "Who is Virat Kohli?",
    "Tell me about Shah Rukh Khan movies",
    "Who won the 2011 cricket world cup?",
    "How do I cook biryani?",
    "What is the capital of France?",
    "Who is the prime minister?",
    "Write me a poem",
    "How do I apply for a driving licence in India?",
    "How do I get a passport?",
    "What is my horoscope today?",
]

IN_DOMAIN = [
    "On what grounds can BIS cancel a licence?",
    "How long is a CRS registration valid?",
    "What is the hallmarking fee for gold jewellery?",
    "What is IS 17440?",
    "What does IS/IEC 62368-1 cover?",
    "Which standard applies to helmets?",
    "Can I sell water bottles without approval?",
    "Do I need testing before selling toys?",
    "What documents does a foreign manufacturer submit?",
    "Is a driving licence accepted as ID proof for BIS registration?",
]


@pytest.mark.parametrize("question", OFF_DOMAIN)
def test_off_domain_questions_are_refused(question):
    assert check_scope(question).in_scope is False


@pytest.mark.parametrize("question", IN_DOMAIN)
def test_compliance_questions_are_answered(question):
    assert check_scope(question).in_scope is True


def test_bare_verb_is_does_not_count_as_a_standard_reference():
    """Regression: 'is' was in the domain lexicon for the sake of 'IS 17440',
    which made 'Who is Virat Kohli?' look like a standards question."""
    assert check_scope("Who is Virat Kohli?").in_scope is False
    assert check_scope("What is IS 17440?").in_scope is True


def test_strong_bis_signal_overrides_an_off_domain_word():
    """A driving licence used as ID proof for BIS registration is on-topic."""
    v = check_scope("Is a driving licence valid ID for BIS registration?")
    assert v.in_scope and "explicit" in v.reason


def test_hindi_questions_are_not_judged_by_an_english_lexicon():
    v = check_scope("क्या मुझे इसके लिए लाइसेंस चाहिए?")
    assert v.in_scope and "hindi" in v.reason.lower()


def test_empty_input_is_out_of_scope():
    assert check_scope("").in_scope is False
    assert check_scope("  ").in_scope is False


def test_refusal_is_translated():
    assert "outside what I handle" in refusal_text("English")
    assert "कार्यक्षेत्र से बाहर" in refusal_text("Hindi (हिन्दी)")


def test_refusal_says_what_it_does_answer():
    """A refusal should redirect, not just reject."""
    for lang in ("English", "Hindi (हिन्दी)"):
        text = refusal_text(lang)
        assert "BIS" in text or "बीआईएस" in text


# ── End-to-end ───────────────────────────────────────────────────────────

def test_off_domain_question_never_reaches_retrieval_or_the_model(monkeypatch):
    """Refusing costs nothing: no search, no LLM call, no tokens."""
    def no_search(*a, **k):
        raise AssertionError("retrieval ran on an off-domain question")

    def no_llm(*a, **k):
        raise AssertionError("LLM called on an off-domain question")

    monkeypatch.setattr(answer_mod, "search", no_search)
    monkeypatch.setattr(answer_mod.llm, "chat", no_llm)

    result = answer_question("Who is Virat Kohli?")
    assert result.refused and not result.grounded
    assert result.general_knowledge is False
    assert "out of scope" in result.reason


def test_refusal_does_not_leak_the_off_topic_answer(monkeypatch):
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [])
    monkeypatch.setattr(
        answer_mod.llm, "chat",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    text = answer_question("Who is Virat Kohli, the cricketer?").text.lower()
    for leaked in ("kohli", "cricket", "batsman", "1988", "delhi"):
        assert leaked not in text


def test_general_knowledge_prompt_also_enforces_scope():
    """Belt and braces: if the deterministic gate ever lets something
    through, the prompt refuses it too."""
    prompt = answer_mod.GENERAL_KNOWLEDGE_PROMPT.lower()
    assert "scope" in prompt
    assert "do not answer it" in prompt


def test_in_domain_question_still_works_normally(monkeypatch):
    from rag.tests.test_answer import make_hit

    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [make_hit()])
    monkeypatch.setattr(
        answer_mod.llm, "chat",
        lambda *a, **k: answer_mod.llm.LLMResponse("Answer. [S1]", "m"),
    )
    result = answer_question("How long is a CRS registration valid?")
    assert result.grounded and not result.refused
