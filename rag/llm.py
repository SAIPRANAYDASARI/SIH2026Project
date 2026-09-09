"""Chat client for the hosted LLM.

Kept deliberately small and dependency-free (urllib only). Two things it has
to handle that a naive client gets wrong against this provider:

  * Reasoning models (gpt-oss-20b) return their chain of thought in
    `reasoning` and leave `content` null when the token budget runs out
    mid-thought. Treating that as a valid empty answer would silently produce
    a blank response, so it is raised as an error instead.
  * Some other reasoning models put that same chain-of-thought directly in
    `content` instead, with no empty-message signal at all — observed from
    nvidia/nemotron-3-super-120b-a12b returning "We need to answer... Let's
    scan each source..." as if it were the final answer. Caught by
    `_looks_like_leaked_reasoning` so it is retried/refused rather than shown.
  * Individual models return 503 "temporarily overloaded", 500 "internal
    server error", or 404 "not found for account" unpredictably, so the
    caller can supply fallbacks.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from rag import budget, config


class LLMError(RuntimeError):
    pass


class TokenBudgetTooSmall(LLMError):
    """The model used its whole token budget on hidden reasoning and never
    reached a visible answer (finish_reason=length).

    Distinct from other failures because it is *deterministic*: retrying with
    the same budget fails identically every time. The caller must raise the
    budget rather than simply try again.
    """


@dataclass
class LLMResponse:
    text: str
    model: str


# Only openai/gpt-oss-20b is listed. Every alternative tried on this account
# failed, and not just with "unavailable" errors that are safe to skip:
#   mistralai/mistral-large-2-instruct       404 not found for account
#   nvidia/llama-3.1-nemotron-51b-instruct   404 not found for account
#   nvidia/nemotron-3-super-120b-a12b        503 overloaded (initial test),
#                                             then HTTP 500 internal-server-error,
#                                             then — worst of all — returned its
#                                             raw chain-of-thought ("We need to
#                                             answer... Let's scan each
#                                             source...") as the answer content
#                                             itself with citation markers
#                                             embedded in it, which passed
#                                             citation validation and nearly
#                                             reached a user as a real answer.
#
# A second model is only worth having if its failures are limited to "can't
# answer" — a model that sometimes answers with garbage is worse than no
# fallback, because a plausible-looking broken answer is exactly what this
# system exists to prevent. If NVIDIA's catalog offers a confirmed-clean
# second option later, add it back here.
FALLBACK_MODELS = [
    "openai/gpt-oss-20b",
]


def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.0,
) -> LLMResponse:
    """Answer one question, sending at most
    `config.LLM_MAX_ATTEMPTS_PER_QUESTION` requests in total.

    The attempt budget spans retries *and* model fallbacks together. Counting
    them separately is how a provider outage turns one question into a dozen
    billable requests, so there is a single shared counter.
    """
    # Fail before the socket is opened, not after. Surfaced as LLMError so
    # callers have a single exception type to handle.
    try:
        budget.check_allowed()
    except budget.BudgetExceeded as exc:
        raise LLMError(str(exc)) from exc

    key = config.llm_api_key()
    if not key:
        raise LLMError(
            "No LLM API key. Set BIS_LLM_API_KEY, or HOSTED_LLM_API_KEY in the project .env"
        )

    candidates = [model or config.LLM_MODEL]
    for fb in FALLBACK_MODELS:
        if fb not in candidates:
            candidates.append(fb)

    attempts_left = max(1, config.LLM_MAX_ATTEMPTS_PER_QUESTION)
    last: Exception | None = None
    tokens = max_tokens or config.LLM_MAX_TOKENS
    started = time.monotonic()

    def out_of_time() -> bool:
        return time.monotonic() - started >= config.LLM_TOTAL_DEADLINE

    for candidate in candidates:
        while attempts_left > 0:
            if out_of_time():
                raise LLMError(
                    f"Gave up after {config.LLM_TOTAL_DEADLINE}s so the user is not "
                    f"left waiting. Last error: {last}"
                )
            attempts_left -= 1
            try:
                budget.check_allowed()
            except budget.BudgetExceeded as exc:
                raise LLMError(str(exc)) from exc
            try:
                return _call(candidate, messages, key, tokens, temperature)
            except TokenBudgetTooSmall as exc:
                last = exc
                # Deterministic failure: the same budget would exhaust itself
                # the same way. Only a bigger one can succeed, so escalate
                # instead of burning identical retries.
                if attempts_left and tokens < config.LLM_MAX_TOKENS_CEILING:
                    tokens = min(tokens * 2, config.LLM_MAX_TOKENS_CEILING)
                    continue
                break
            except LLMError as exc:
                last = exc
                text = str(exc)
                # 404 means the model is not enabled for this account; more
                # attempts on it can only waste budget.
                if "404" in text:
                    break
                if attempts_left and "503" in text:
                    time.sleep(1.5)
                    continue
                break
        if attempts_left <= 0:
            break

    raise LLMError(
        f"Gave up after {config.LLM_MAX_ATTEMPTS_PER_QUESTION} attempt(s). Last error: {last}"
    )


def _call(model, messages, key, max_tokens, temperature) -> LLMResponse:
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens or config.LLM_MAX_TOKENS,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        config.LLM_BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=config.LLM_REQUEST_TIMEOUT) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        # A rejected request still left the machine, so it is counted.
        budget.record()
        body = ""
        try:
            body = exc.read().decode()[:300]
        except Exception:
            pass
        raise LLMError(f"HTTP {exc.code} from {model}: {body}") from exc
    except Exception as exc:
        raise LLMError(f"{type(exc).__name__} calling {model}: {exc}") from exc

    usage = data.get("usage") or {}
    budget.record(
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
    )

    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text = (message.get("content") or "").strip()
    if not text:
        # Reasoning model that spent its whole budget thinking.
        if message.get("reasoning") or choice.get("finish_reason") == "length":
            raise TokenBudgetTooSmall(
                f"{model} used all {max_tokens or config.LLM_MAX_TOKENS} tokens on "
                f"reasoning without reaching an answer "
                f"(finish_reason={choice.get('finish_reason')})"
            )
        raise LLMError(f"{model} returned an empty message")

    if _looks_like_leaked_reasoning(text):
        # Observed from nvidia/nemotron-3-super-120b-a12b: some "thinking"
        # models put their chain-of-thought directly in `content` instead of
        # a separate `reasoning` field, so the emptiness check above cannot
        # catch it. Left unfiltered, this reaches the user as the answer —
        # scratchpad narration like "We need to answer... Let's scan each
        # source..." with citation markers scattered through it, which looks
        # enough like a real answer to pass citation validation. Treated as a
        # failure so the caller retries or falls back, rather than shown.
        raise LLMError(f"{model} returned unfiltered chain-of-thought instead of an answer")

    return LLMResponse(text=text, model=model)


# Phrases a narrated reasoning process opens with, that a direct answer never
# does. Checked only against the first ~200 characters — a legitimate answer
# can still discuss "the source" mid-paragraph without tripping this.
_REASONING_LEAK_PATTERNS = re.compile(
    r"^\s*(?:we need to|let'?s (?:check|scan|look|see|go through)|"
    r"i need to (?:check|find|look)|first,? (?:i|let|we)|"
    r"the user (?:wants|is asking|asked)|okay,? (?:so|let|i|we)|"
    r"looking at (?:each|the) source)",
    re.IGNORECASE,
)


def _looks_like_leaked_reasoning(text: str) -> bool:
    return bool(_REASONING_LEAK_PATTERNS.match(text[:200]))
