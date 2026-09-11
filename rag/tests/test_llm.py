"""Chain-of-thought leak detection.

Some "thinking" models put their reasoning directly in `content` instead of a
separate `reasoning` field, so a normal empty-message check cannot catch it.
Observed for real from nvidia/nemotron-3-super-120b-a12b, which returned
"We need to answer... Let's scan each source..." — with [S#] markers scattered
through the narration — as if it were the final answer. That passed citation
validation and nearly reached a user as a genuine grounded response, so this
check exists as a second line of defense independent of the prompt.
"""

from __future__ import annotations

import pytest

from rag.llm import _looks_like_leaked_reasoning

LEAKED = [
    'We need to answer: "On what grounds can BIS cancel a licence?" Use only sources.',
    "Let's scan each source. [S1] says the DDGR may cancel the licence.",
    "Let's check the sources for grounds of cancellation before answering.",
    "I need to check S1 and S2 for the relevant clause about fees.",
    "First, I will look at what S1 says about hallmarking fees.",
    "The user wants to know the hallmarking fee, so let's find it in S1.",
    "Okay, so the question is about licence cancellation grounds.",
    "Looking at each source, S1 mentions the fee schedule in Schedule IV.",
]

REAL_ANSWERS = [
    "The hallmarking fee is specified in Schedule IV of the Regulations. [S1]",
    "BIS may cancel a licence if the manufacturer misuses it. [S4]",
    "A CRS registration is valid for two years from the date of grant. [S2]",
    "The first source discusses fee schedules, while the second covers penalties. [S1][S2]",
    "We, the Bureau, hereby notify the following amendment. [S3]",  # legit legal text with "We"
]


@pytest.mark.parametrize("text", LEAKED)
def test_detects_real_leaked_reasoning_openers(text):
    assert _looks_like_leaked_reasoning(text) is True


@pytest.mark.parametrize("text", REAL_ANSWERS)
def test_does_not_flag_genuine_answers(text):
    assert _looks_like_leaked_reasoning(text) is False


def test_only_checks_the_opening_not_the_whole_answer():
    # A legitimate answer that later quotes source text containing "let's
    # scan" (hypothetically) must not be flagged just because that phrase
    # appears deep in the body.
    text = "The fee is Rs. 500. [S1] " + "x" * 250 + " let's scan this again"
    assert _looks_like_leaked_reasoning(text) is False


def test_case_insensitive():
    assert _looks_like_leaked_reasoning("WE NEED TO ANSWER this question.") is True


def test_empty_text_is_not_flagged():
    assert _looks_like_leaked_reasoning("") is False


# ── Token-budget escalation ──────────────────────────────────────────────
#
# A reasoning model spends part of its token budget on hidden thought before
# writing anything visible. When the budget runs out mid-thought it returns
# finish_reason=length with empty content — a *deterministic* failure, since
# an identical retry exhausts the identical budget the same way. Observed on
# a real question ("explain the complete certification process"), where all
# three allowed attempts failed identically and achieved nothing.


@pytest.fixture
def budgeted(monkeypatch, tmp_path):
    from rag import budget, config

    monkeypatch.setattr(config, "INDEX_DIR", tmp_path)
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(config, "LLM_DAILY_CALL_LIMIT", 99)
    monkeypatch.setattr(config, "LLM_MAX_ATTEMPTS_PER_QUESTION", 3)
    monkeypatch.setattr(config, "LLM_MAX_TOKENS", 1000)
    monkeypatch.setattr(config, "LLM_MAX_TOKENS_CEILING", 4000)
    monkeypatch.setattr(config, "llm_api_key", lambda: "test-key")
    return budget


def test_budget_exhaustion_escalates_tokens_instead_of_repeating(budgeted, monkeypatch):
    from rag import llm

    seen: list[int] = []

    def exhaust(provider, messages, max_tokens, temperature):
        seen.append(max_tokens)
        raise llm.TokenBudgetTooSmall(f"{provider.model} used all {max_tokens} tokens")

    monkeypatch.setattr(llm, "_call", exhaust)
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "long question"}])

    # Each retry must ask for more room than the last, never the same again.
    assert seen == [1000, 2000, 4000], seen


def test_escalation_stops_at_the_ceiling(budgeted, monkeypatch):
    from rag import config, llm

    monkeypatch.setattr(config, "LLM_MAX_TOKENS_CEILING", 1500)
    seen: list[int] = []

    def exhaust(provider, messages, max_tokens, temperature):
        seen.append(max_tokens)
        raise llm.TokenBudgetTooSmall("exhausted")

    monkeypatch.setattr(llm, "_call", exhaust)
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "q"}])

    assert max(seen) <= 1500


def test_escalated_retry_can_succeed(budgeted, monkeypatch):
    from rag import llm

    def exhaust_then_answer(provider, messages, max_tokens, temperature):
        if max_tokens < 2000:
            raise llm.TokenBudgetTooSmall("too small")
        return llm.LLMResponse(text="The fee is in Schedule IV. [S1]", model=provider.model)

    monkeypatch.setattr(llm, "_call", exhaust_then_answer)
    assert "Schedule IV" in llm.chat([{"role": "user", "content": "q"}]).text


def test_non_deterministic_failures_do_not_escalate(budgeted, monkeypatch):
    """A 503 is transient — retry the same request, don't inflate the budget."""
    from rag import llm

    seen: list[int] = []

    def overloaded(provider, messages, max_tokens, temperature):
        seen.append(max_tokens)
        raise llm.LLMError("HTTP 503 overloaded")

    monkeypatch.setattr(llm, "_call", overloaded)
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "q"}])

    assert set(seen) == {1000}, seen
