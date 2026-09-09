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
        raise llm.LLMError(f"HTTP 503 from {model}: overloaded")
    monkeypatch.setattr(llm, "_call", always_503)
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)

    with pytest.raises(llm.LLMError, match="Gave up after 3"):
        llm.chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 3


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
    assert callers == {"https://integrate.api.nvidia.com/v1"}, callers


def test_reference_links_are_not_fetched_by_code():
    """The BIS portal links in marks.py must stay display-only."""
    import pathlib
    import re

    source = (pathlib.Path(__file__).resolve().parent.parent / "marks.py").read_text(
        encoding="utf-8"
    )
    assert not re.search(r"urlopen|requests\.|httpx|aiohttp", source)
