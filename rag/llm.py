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
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from rag import budget, config

# Rate limiting and upstream faults; everything else is treated as permanent.
_TRANSIENT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class LLMError(RuntimeError):
    pass


class TokenBudgetTooSmall(LLMError):
    """The model used its whole token budget on hidden reasoning and never
    reached a visible answer (finish_reason=length).

    Distinct from other failures because it is *deterministic*: retrying with
    the same budget fails identically every time. The caller must raise the
    budget rather than simply try again.
    """


class TransientLLMError(LLMError):
    """A failure that says nothing about the request and everything about the
    moment it was sent: a read timeout, a dropped connection, a 429, or a 5xx.

    Worth distinguishing because the opposite assumption was a real bug. A
    grounded answer here measures ~60s against a 100s per-request timeout, so
    ordinary queue variance on NVIDIA's shared free tier pushes a perfectly
    answerable question over the limit. That timeout used to fall through to
    the generic `break` below and abandon the question after ONE attempt —
    with three attempts and ~130s of deadline still unspent — which is what
    made identical questions answer fine one minute and degrade to raw quoted
    passages the next.
    """


class RateLimited(TransientLLMError):
    """Provider quota, not provider health.

    Groq's free tier allows 8k tokens/minute and one grounded question costs
    ~3.6k, so the third question inside a minute is refused. It answers with a
    `Retry-After`, and honouring that is usually the fastest route to a real
    answer: waiting ~28s and then getting a 1.5s reply beats failing over to a
    provider that takes 60-200s. `retry_after` is None when the provider did
    not say, in which case the caller moves straight on to the fallback.
    """

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


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


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    model: str
    key: str

    def __str__(self) -> str:  # what shows up in error messages
        return f"{self.model} via {self.name}"


def providers(model: str | None = None) -> list[Provider]:
    """Providers to try, in order, skipping any without a key.

    Groq first for speed; NVIDIA second so that exhausting Groq's per-minute
    free-tier cap degrades to a slow answer rather than no answer.
    """
    found: list[Provider] = []
    groq_key = config.groq_api_key()
    if groq_key:
        found.append(Provider("groq", config.GROQ_BASE_URL, model or config.GROQ_MODEL, groq_key))
    nvidia_key = config.llm_api_key()
    if nvidia_key:
        found.append(Provider("nvidia", config.LLM_BASE_URL, model or config.LLM_MODEL, nvidia_key))
    return found


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

    candidates = providers(model)
    if not candidates:
        raise LLMError(
            "No LLM API key. Set GROQ_API_KEY (preferred) or HOSTED_LLM_API_KEY "
            "in the project .env"
        )

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
                return _call(candidate, messages, tokens, temperature)
            except RateLimited as exc:
                last = exc
                # Wait the cap out when the provider says how long and the
                # deadline can absorb it: this provider answers in ~1.5s, so
                # waiting is usually still faster than failing over. `+ 5`
                # keeps a margin for the call that follows the wait.
                spent = time.monotonic() - started
                wait = exc.retry_after
                if (
                    attempts_left
                    and wait is not None
                    and spent + wait + 5 < config.LLM_TOTAL_DEADLINE
                ):
                    time.sleep(wait)
                    continue
                # No hint, or no room left — the fallback provider is the
                # better use of what remains.
                break
            except TokenBudgetTooSmall as exc:
                last = exc
                # Deterministic failure: the same budget would exhaust itself
                # the same way. Only a bigger one can succeed, so escalate
                # instead of burning identical retries.
                if attempts_left and tokens < config.LLM_MAX_TOKENS_CEILING:
                    tokens = min(tokens * 2, config.LLM_MAX_TOKENS_CEILING)
                    continue
                break
            except TransientLLMError as exc:
                last = exc
                # Nothing about the request was wrong, so the same request can
                # succeed on the next try. Retry while attempts and deadline
                # remain; `out_of_time` at the top of the loop is what stops
                # this becoming an unbounded wait.
                if attempts_left:
                    time.sleep(1.5)
                    continue
                break
            except LLMError as exc:
                last = exc
                text = str(exc)
                # 404 means the model is not enabled for this account; more
                # attempts on it can only waste budget.
                if "404" in text:
                    break
                break
        if attempts_left <= 0:
            break

    raise LLMError(
        f"Gave up after {config.LLM_MAX_ATTEMPTS_PER_QUESTION} attempt(s). Last error: {last}"
    )


def _call(provider, messages, max_tokens, temperature) -> LLMResponse:
    model = provider.model
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens or config.LLM_MAX_TOKENS,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        provider.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {provider.key}",
            "Content-Type": "application/json",
            # Groq sits behind Cloudflare, which rejects urllib's default
            # agent outright with a 403 (error 1010) before the request ever
            # reaches the API — an auth-looking failure that has nothing to do
            # with the key.
            "User-Agent": "manak-sahayak/1.0",
        },
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
        msg = f"HTTP {exc.code} from {provider}: {body}"
        if exc.code == 429:
            raw = exc.headers.get("retry-after") if exc.headers else None
            try:
                wait = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                wait = None
            raise RateLimited(msg, retry_after=wait) from exc
        # Server-side faults are about capacity at this instant, not about the
        # request, so they are worth another attempt.
        if exc.code in _TRANSIENT_STATUS:
            raise TransientLLMError(msg) from exc
        raise LLMError(msg) from exc
    except Exception as exc:
        msg = f"{type(exc).__name__} calling {model}: {exc}"
        # A read timeout or dropped connection. Measured latency here ranges
        # from 9s to 80s for near-identical prompts, so the slow tail of that
        # spread crosses LLM_REQUEST_TIMEOUT on questions that would otherwise
        # have answered fine — retryable, not fatal.
        if isinstance(exc, (TimeoutError, socket.timeout, urllib.error.URLError)):
            raise TransientLLMError(msg) from exc
        raise LLMError(msg) from exc

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

    # Name the provider, not just the model: both providers serve the same
    # model id, so without this an answer gives no way to tell whether it came
    # back in 2s from Groq or 60s from the NVIDIA fallback.
    return LLMResponse(text=text, model=f"{model} ({provider.name})")


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
