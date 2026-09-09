"""Hard spending guard for the hosted LLM.

The only component of this system that could ever cost money is the chat
completion call. Everything else — extraction, indexing, embeddings, all
three search modes — runs locally and is free by construction.

So the network path is fenced in three ways:

  1. It can be switched off entirely (`BIS_LLM_ENABLED=false`), after which no
     code path can reach the network.
  2. Every call is counted against a persisted daily cap. When the cap is
     reached the call is refused locally — before any request is sent.
  3. Token usage per call is bounded, so a single call cannot be large.

The counter lives next to the index as plain JSON, survives restarts, and
resets on date change. It is deliberately fail-closed: if the counter file
cannot be read or written, calls are refused rather than allowed through
uncounted.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from rag import config


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Usage:
    date: str
    calls: int
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _path() -> Path:
    return config.INDEX_DIR / "llm_usage.json"


def read_usage() -> Usage:
    today = _today()
    path = _path()
    if not path.exists():
        return Usage(today, 0, 0, 0)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Unreadable counter: treat as exhausted rather than silently
        # un-metered. Delete the file to reset deliberately.
        raise BudgetExceeded(
            f"Usage counter at {path} is unreadable, so LLM calls are blocked. "
            "Delete the file to reset it."
        ) from None
    if raw.get("date") != today:
        return Usage(today, 0, 0, 0)
    return Usage(
        today,
        int(raw.get("calls", 0)),
        int(raw.get("prompt_tokens", 0)),
        int(raw.get("completion_tokens", 0)),
    )


def _write(usage: Usage) -> None:
    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    _path().write_text(
        json.dumps(
            {
                "date": usage.date,
                "calls": usage.calls,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "daily_call_limit": config.LLM_DAILY_CALL_LIMIT,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def check_allowed() -> Usage:
    """Raise before any network request if the LLM is off or the cap is hit."""
    if not config.LLM_ENABLED:
        raise BudgetExceeded(
            "The hosted LLM is disabled (BIS_LLM_ENABLED=false). Retrieval and "
            "offline answering still work and make no network calls."
        )
    usage = read_usage()
    if usage.calls >= config.LLM_DAILY_CALL_LIMIT:
        raise BudgetExceeded(
            f"Daily LLM call limit reached ({usage.calls}/"
            f"{config.LLM_DAILY_CALL_LIMIT} on {usage.date}). No request was "
            "sent. Raise BIS_LLM_DAILY_CALL_LIMIT to allow more, or use "
            "offline mode, which never calls the network."
        )
    return usage


def record(prompt_tokens: int = 0, completion_tokens: int = 0) -> Usage:
    usage = read_usage()
    usage.calls += 1
    usage.prompt_tokens += max(prompt_tokens, 0)
    usage.completion_tokens += max(completion_tokens, 0)
    _write(usage)
    return usage


def remaining() -> int:
    try:
        return max(0, config.LLM_DAILY_CALL_LIMIT - read_usage().calls)
    except BudgetExceeded:
        return 0
