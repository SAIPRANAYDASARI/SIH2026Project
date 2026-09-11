"""Cost containment.

The hosted chat completion is the only billable thing this system can do, so
these tests assert the guards that stand in front of it — including the one
that matters most: that offline mode cannot open a socket at all.
"""

from __future__ import annotations

import pytest

from rag import answer as answer_mod
from rag import budget, config, llm
from rag.answer import answer_question
from rag.search import Hit, Mode


@pytest.fixture(autouse=True)
def isolated_counter(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path)
    monkeypatch.setattr(config, "LLM_ENABLED", True)
    monkeypatch.setattr(config, "LLM_DAILY_CALL_LIMIT", 5)


@pytest.fixture
def no_network(monkeypatch):
    """Turn any real outbound request into a loud failure."""
    def boom(*a, **k):
        raise AssertionError("network call attempted")
    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)


def make_hit(text="The hallmarking fee shall be as specified in Schedule IV."):
    return Hit(
        chunk_id=1, text=text, relpath="07_HALLMARKING/x.pdf", page_number=12,
        title="Hallmarking Regulations", category="07_HALLMARKING",
        source_url=None, score=0.05,
    )


def test_usage_starts_empty():
    u = budget.read_usage()
    assert u.calls == 0 and u.total_tokens == 0


def test_calls_are_counted():
    budget.record(prompt_tokens=100, completion_tokens=20)
    budget.record(prompt_tokens=50, completion_tokens=10)
    u = budget.read_usage()
    assert u.calls == 2
    assert u.prompt_tokens == 150 and u.completion_tokens == 30
    assert u.total_tokens == 180


def test_usage_persists_across_reads():
    budget.record(prompt_tokens=7)
    assert budget.read_usage().calls == 1
    assert budget.read_usage().calls == 1  # not double counted by reading


def test_check_allowed_blocks_at_the_cap():
    for _ in range(config.LLM_DAILY_CALL_LIMIT):
        budget.record()
    with pytest.raises(budget.BudgetExceeded, match="Daily LLM call limit"):
        budget.check_allowed()


def test_remaining_counts_down_and_floors_at_zero():
    assert budget.remaining() == 5
    for _ in range(7):
        budget.record()
    assert budget.remaining() == 0


def test_disabling_the_llm_blocks_before_any_request(monkeypatch):
    monkeypatch.setattr(config, "LLM_ENABLED", False)
    with pytest.raises(budget.BudgetExceeded, match="disabled"):
        budget.check_allowed()


def test_corrupt_counter_fails_closed(tmp_path):
    (tmp_path / "llm_usage.json").write_text("{not json", encoding="utf-8")
    # An unreadable counter must block calls, never silently allow un-metered ones.
    with pytest.raises(budget.BudgetExceeded, match="unreadable"):
        budget.read_usage()


def test_chat_refuses_over_budget_without_touching_the_network(no_network):
    for _ in range(config.LLM_DAILY_CALL_LIMIT):
        budget.record()
    with pytest.raises(llm.LLMError, match="Daily LLM call limit"):
        llm.chat([{"role": "user", "content": "hi"}])


def test_chat_refuses_when_disabled_without_touching_the_network(monkeypatch, no_network):
    monkeypatch.setattr(config, "LLM_ENABLED", False)
    with pytest.raises(llm.LLMError, match="disabled"):
        llm.chat([{"role": "user", "content": "hi"}])


def test_one_question_cannot_exceed_the_attempt_budget(monkeypatch):
    """A provider outage must not turn one question into a storm of requests."""
    monkeypatch.setattr(config, "LLM_MAX_ATTEMPTS_PER_QUESTION", 3)
    monkeypatch.setattr(config, "LLM_DAILY_CALL_LIMIT", 999)
    monkeypatch.setattr(config, "llm_api_key", lambda: "test-key")

    calls = []
    def always_503(model, *a, **k):
        calls.append(model)
        # What `_call` raises for a 5xx: retryable, but still capped.
        raise llm.TransientLLMError(f"HTTP 503 from {model}: overloaded")
    monkeypatch.setattr(llm, "_call", always_503)
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)

    with pytest.raises(llm.LLMError, match="Gave up after 3"):
        llm.chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 3


def test_read_timeout_is_retried_not_abandoned(monkeypatch):
    """A slow response must not cost the user their answer.

    Measured latency against this provider swings from ~9s to ~80s for
    near-identical prompts, so the slow tail crosses LLM_REQUEST_TIMEOUT on
    questions that would otherwise answer fine. This used to abandon the
    question after ONE attempt and degrade it to raw quoted passages, with
    attempts and deadline still unspent.
    """
    monkeypatch.setattr(config, "LLM_MAX_ATTEMPTS_PER_QUESTION", 3)
    monkeypatch.setattr(config, "LLM_DAILY_CALL_LIMIT", 999)
    monkeypatch.setattr(config, "llm_api_key", lambda: "test-key")
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)

    calls = []
    def timeout_then_answer(model, *a, **k):
        calls.append(model)
        if len(calls) == 1:
            raise llm.TransientLLMError("TimeoutError calling x: timed out")
        return llm.LLMResponse(text="The fee is Rs 45 per article [S1]", model=model)
    monkeypatch.setattr(llm, "_call", timeout_then_answer)

    result = llm.chat([{"role": "user", "content": "hallmarking fee"}])
    assert len(calls) == 2, "the timeout should have been retried"
    assert "[S1]" in result.text


def test_permanent_failure_is_not_retried_on_the_same_provider(monkeypatch):
    """A 404 means the model is not enabled for that account; retrying the
    same provider can only burn budget with no chance of succeeding.

    Pinned to one provider so this measures retry behaviour, not the
    separate (and wanted) fall-through to the next provider.
    """
    monkeypatch.setattr(config, "LLM_MAX_ATTEMPTS_PER_QUESTION", 3)
    monkeypatch.setattr(config, "LLM_DAILY_CALL_LIMIT", 999)
    monkeypatch.setattr(
        llm, "providers",
        lambda model=None: [llm.Provider("solo", "https://example.invalid/v1", "m", "k")],
    )

    calls = []
    def always_404(provider, *a, **k):
        calls.append(provider)
        raise llm.LLMError(f"HTTP 404 from {provider}: not found for account")
    monkeypatch.setattr(llm, "_call", always_404)

    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 1


def test_rate_limit_waits_out_a_short_retry_after(monkeypatch):
    """Groq answers in ~1.5s, so waiting out a 28s cap beats failing over to a
    provider that takes 60-200s. The wait must be the one the provider asked
    for, not a guess."""
    monkeypatch.setattr(config, "LLM_MAX_ATTEMPTS_PER_QUESTION", 4)
    monkeypatch.setattr(config, "LLM_DAILY_CALL_LIMIT", 999)
    monkeypatch.setattr(config, "LLM_TOTAL_DEADLINE", 190)
    slept: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(
        llm, "providers",
        lambda model=None: [
            llm.Provider("groq", "https://api.groq.com/openai/v1", "m", "k"),
            llm.Provider("nvidia", "https://integrate.api.nvidia.com/v1", "m", "k"),
        ],
    )

    seen = []
    def capped_once(provider, *a, **k):
        seen.append(provider.name)
        if len(seen) == 1:
            raise llm.RateLimited("HTTP 429", retry_after=28)
        return llm.LLMResponse(text="Fee is Rs 45 [S1]", model=provider.model)
    monkeypatch.setattr(llm, "_call", capped_once)

    result = llm.chat([{"role": "user", "content": "hi"}])
    assert slept == [28], f"should wait exactly what the provider asked: {slept}"
    assert seen == ["groq", "groq"], f"should retry the fast provider: {seen}"
    assert "[S1]" in result.text


def test_rate_limit_without_a_hint_uses_the_fallback(monkeypatch):
    """No Retry-After means no idea how long to wait, so the question goes to
    the fallback provider rather than stalling on a guess."""
    monkeypatch.setattr(config, "LLM_MAX_ATTEMPTS_PER_QUESTION", 4)
    monkeypatch.setattr(config, "LLM_DAILY_CALL_LIMIT", 999)
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        llm, "providers",
        lambda model=None: [
            llm.Provider("groq", "https://api.groq.com/openai/v1", "m", "k"),
            llm.Provider("nvidia", "https://integrate.api.nvidia.com/v1", "m", "k"),
        ],
    )

    seen = []
    def groq_capped(provider, *a, **k):
        seen.append(provider.name)
        if provider.name == "groq":
            raise llm.RateLimited("HTTP 429", retry_after=None)
        return llm.LLMResponse(text="answer [S1]", model=provider.model)
    monkeypatch.setattr(llm, "_call", groq_capped)

    llm.chat([{"role": "user", "content": "hi"}])
    assert seen == ["groq", "nvidia"], seen


def test_rate_limit_skips_a_wait_that_would_blow_the_deadline(monkeypatch):
    """A cap longer than the time left must not be waited out — the user would
    be left staring at a spinner past the deadline that exists to prevent it."""
    monkeypatch.setattr(config, "LLM_MAX_ATTEMPTS_PER_QUESTION", 4)
    monkeypatch.setattr(config, "LLM_DAILY_CALL_LIMIT", 999)
    monkeypatch.setattr(config, "LLM_TOTAL_DEADLINE", 30)
    slept: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(
        llm, "providers",
        lambda model=None: [
            llm.Provider("groq", "https://api.groq.com/openai/v1", "m", "k"),
            llm.Provider("nvidia", "https://integrate.api.nvidia.com/v1", "m", "k"),
        ],
    )

    seen = []
    def groq_capped(provider, *a, **k):
        seen.append(provider.name)
        if provider.name == "groq":
            raise llm.RateLimited("HTTP 429", retry_after=600)
        return llm.LLMResponse(text="answer [S1]", model=provider.model)
    monkeypatch.setattr(llm, "_call", groq_capped)

    llm.chat([{"role": "user", "content": "hi"}])
    assert slept == [], "a 600s wait must never be taken"
    assert seen == ["groq", "nvidia"], seen


def test_groq_rate_limit_falls_through_to_the_fallback_provider(monkeypatch):
    """Groq's free tier caps tokens per minute. That cap cannot clear in the
    seconds a retry would wait, so the question must reach the fallback
    provider instead of spending every attempt being rate-limited.
    """
    monkeypatch.setattr(config, "LLM_MAX_ATTEMPTS_PER_QUESTION", 4)
    monkeypatch.setattr(config, "LLM_DAILY_CALL_LIMIT", 999)
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        llm, "providers",
        lambda model=None: [
            llm.Provider("groq", "https://api.groq.com/openai/v1", "m", "k"),
            llm.Provider("nvidia", "https://integrate.api.nvidia.com/v1", "m", "k"),
        ],
    )

    seen = []
    def groq_capped(provider, *a, **k):
        seen.append(provider.name)
        if provider.name == "groq":
            raise llm.RateLimited("HTTP 429 from groq: rate_limit_exceeded")
        return llm.LLMResponse(text="Fee is Rs 45 [S1]", model=provider.model)
    monkeypatch.setattr(llm, "_call", groq_capped)

    result = llm.chat([{"role": "user", "content": "hi"}])
    assert seen == ["groq", "nvidia"], seen
    assert "[S1]" in result.text


def test_offline_answer_makes_no_network_call(monkeypatch, no_network):
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [make_hit()])
    def boom(*a, **k):
        raise AssertionError("llm.chat called in offline mode")
    monkeypatch.setattr(answer_mod.llm, "chat", boom)

    result = answer_question("what is the hallmarking fee", offline=True)
    assert result.grounded and not result.refused
    assert "no network call" in result.model
    assert "Schedule IV" in result.text  # quoted verbatim from the source


def test_offline_answer_quotes_rather_than_generates(monkeypatch, no_network):
    source = "The licence shall remain valid for a period of two years."
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [make_hit(source)])
    result = answer_question("how long is the licence valid", offline=True)
    # Every sentence in the body must exist verbatim in the source document.
    assert source in result.text


def test_disabled_llm_falls_back_to_offline_not_an_error(monkeypatch, no_network):
    monkeypatch.setattr(config, "LLM_ENABLED", False)
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [make_hit()])
    def boom(*a, **k):
        raise AssertionError("llm.chat called while disabled")
    monkeypatch.setattr(answer_mod.llm, "chat", boom)

    result = answer_question("hallmarking fee", mode=Mode.HYBRID)
    assert "no network call" in result.model


def test_exhausted_budget_falls_back_to_offline(monkeypatch, no_network):
    for _ in range(config.LLM_DAILY_CALL_LIMIT):
        budget.record()
    monkeypatch.setattr(answer_mod, "search", lambda *a, **k: [make_hit()])
    def boom(*a, **k):
        raise AssertionError("llm.chat called with no budget left")
    monkeypatch.setattr(answer_mod.llm, "chat", boom)

    result = answer_question("hallmarking fee")
    assert "no network call" in result.model


def test_only_one_endpoint_is_ever_called():
    """Guards against a second billable endpoint being added unnoticed.

    Distinguishes URLs the code *requests* from URLs it merely *shows* the
    user. rag/marks.py links to bis.gov.in so someone can verify a licence
    themselves; nothing fetches those, and they cost nothing.
    """
    import pathlib
    import re

    pkg = pathlib.Path(__file__).resolve().parent.parent
    callers: set[str] = set()
    for path in pkg.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        # Only files that can actually open a connection.
        if not re.search(r"urlopen|requests\.|httpx|aiohttp", source):
            continue
        for match in re.findall(r"https?://[^\s\"')]+", source):
            if "localhost" not in match and "127.0.0.1" not in match:
                callers.add(match.rstrip("/"))
    assert callers == {
        "https://api.groq.com/openai/v1",  # primary — fast
        "https://integrate.api.nvidia.com/v1",  # fallback when Groq is capped
    }, callers


def test_reference_links_are_not_fetched_by_code():
    """The BIS portal links in marks.py must stay display-only."""
    import pathlib
    import re

    source = (pathlib.Path(__file__).resolve().parent.parent / "marks.py").read_text(
        encoding="utf-8"
    )
    assert not re.search(r"urlopen|requests\.|httpx|aiohttp", source)
