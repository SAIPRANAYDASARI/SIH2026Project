"""Small talk.

A greeting carries no domain vocabulary, so the scope gate treated "hi" as
off-topic and replied "that question is outside what I handle" — hostile, and
the first thing many people type. Greetings, thanks and "who are you" are now
answered directly: no retrieval, no model call, no cost.
"""

from __future__ import annotations

import pytest

from rag import answer as answer_mod
from rag.answer import answer_question
from rag.scope import Intent, classify_intent, small_talk_text


@pytest.mark.parametrize(
    "text",
    ["hi", "Hi!", "hello", "Hello there", "hey", "namaste", "नमस्ते", "नमस्कार",
     "good morning", "hola", "yo"],
)
def test_greetings_are_recognised(text):
    assert classify_intent(text) == Intent.GREETING


@pytest.mark.parametrize("text", ["thanks", "Thank you", "ok", "bye", "धन्यवाद"])
def test_courtesies_are_recognised(text):
    assert classify_intent(text) == Intent.COURTESY


@pytest.mark.parametrize(
    "text",
    ["who are you", "What are you?", "what can you do", "what do you do",
     "how can you help", "help", "आप कौन हैं"],
)
def test_self_description_is_recognised(text):
    assert classify_intent(text) == Intent.ABOUT


@pytest.mark.parametrize(
    "text",
    ["What is hallmark?", "Who is Virat Kohli?",
     "On what grounds can BIS cancel a licence?",
     "How long is a CRS registration valid?"],
)
def test_real_questions_are_not_small_talk(text):
    assert classify_intent(text) == Intent.QUESTION


def test_greeting_reply_says_what_it_can_do():
    for lang, marker in (("English", "Indian Standards"), ("Hindi (हिन्दी)", "भारतीय मानक")):
        text = small_talk_text(Intent.GREETING, lang)
        assert marker in text
        assert len(text) > 80          # it introduces itself, not a bare "hello"


def test_about_reply_states_the_boundary():
    text = small_talk_text(Intent.ABOUT, "English").lower()
    assert "do not answer questions outside" in text


def test_greeting_costs_nothing(monkeypatch):
    """No retrieval, no model call — a greeting must be free and instant."""
    def no_search(*a, **k):
        raise AssertionError("retrieval ran on a greeting")

    def no_llm(*a, **k):
        raise AssertionError("LLM called on a greeting")

    monkeypatch.setattr(answer_mod, "search", no_search)
    monkeypatch.setattr(answer_mod.llm, "chat", no_llm)

    result = answer_question("hi")
    assert not result.refused
    assert "no model call" in result.model
    assert "Manak Sahayak" in result.text


def test_greeting_is_not_dressed_up_as_evidence():
    """It is friendly, not grounded — it must not claim document backing."""
    from rag.search import Mode

    r = answer_question.__wrapped__ if hasattr(answer_question, "__wrapped__") else None
    text = small_talk_text(Intent.GREETING, "English")
    assert "[S" not in text
    assert Mode.HYBRID  # sanity: import kept meaningful


def test_greeting_follows_the_interface_language(monkeypatch):
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [])
    result = answer_question("hi", language="hi")
    assert "मानक सहायक" in result.text


def test_off_domain_question_is_still_refused_after_small_talk_added(monkeypatch):
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [])
    result = answer_question("Who is Virat Kohli?")
    assert result.refused
    assert "cricket" not in result.text.lower()


# ── Language follows the question, then the interface ────────────────────
#
# Reported from the running app: "तुम कौन है?" was answered in English, and
# was not recognised as a "who are you" question at all — it fell through to
# document retrieval and came back "could not answer".

@pytest.mark.parametrize(
    "text",
    ["तुम कौन है?", "तुम कौन हो", "आप कौन हैं", "आप कौन है",
     "आप क्या कर सकते हैं", "अपने बारे में बताओ", "तुम्हारा नाम क्या है"],
)
def test_hindi_self_description_is_recognised(text):
    """Copula agreement varies in how people actually type; requiring an
    exact हो/हैं missed the commonest phrasing."""
    assert classify_intent(text) == Intent.ABOUT


@pytest.mark.parametrize(
    "question,ui,expected",
    [
        # Devanagari in the question settles it, whatever the interface says.
        ("तुम कौन है?", "en", "Hindi"),
        ("हॉलमार्किंग शुल्क क्या है?", "en", "Hindi"),
        ("हॉलमार्किंग?", None, "Hindi"),
        # English text is not a reliable signal, so the interface decides.
        ("What is the fee?", "hi", "Hindi"),
        ("What is the fee?", "en", "English"),
        ("What is the fee?", None, "English"),
    ],
)
def test_reply_language(question, ui, expected):
    from rag.answer import resolve_language
    assert resolve_language(question, ui).startswith(expected)


def test_hindi_question_gets_hindi_small_talk(monkeypatch):
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [])
    result = answer_question("तुम कौन है?", language="en")   # English interface
    assert "मानक सहायक" in result.text
    assert not result.refused
