"""Pluggable LLM adapter (decision #3 in docs/DECISIONS.md): one interface,
switchable backends, so the system can run fully offline (local Ollama) or
against a hosted API, chosen by `LLM_BACKEND` and switchable per-request.

All backends stream: `LLMClient.stream()` is an async generator of text
deltas, because the answer engine (`app.answer.engine`) needs to start
forwarding tokens to the client before the full answer exists (the brief's
Step-5 "streaming" requirement), and because citation validation and
guardrail enforcement (both need the *complete* answer text) only run once
generation finishes — see `app.answer.engine` for how the two halves meet.

Three concrete clients:

- `OllamaLLMClient` — local Ollama `/api/chat`, newline-delimited JSON
  streaming. This is the offline/on-premise path (decision #3): no network
  egress, no API key.
- `OpenAICompatibleLLMClient` — the OpenAI chat/completions wire format
  (`POST {base_url}/chat/completions`, SSE `data: {...}` streaming). This
  is deliberately generic rather than "the OpenAI client": NVIDIA NIM's
  free-tier API, Groq, Together, Azure OpenAI, and OpenAI itself all speak
  this same format, so one implementation plus a configurable
  `hosted_llm_base_url` covers all of them.
- `AnthropicLLMClient` — Anthropic's native Messages API (SSE
  `content_block_delta` events), for when `HOSTED_LLM_PROVIDER=anthropic`.

Every client accepts an injectable `httpx.AsyncBaseTransport` so tests can
drive them against a fake in-process transport instead of a live server —
same pattern as `app.ml.embedding_client` / `app.ml.reranker_client`.
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

import httpx

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


class LLMClient(ABC):
    @abstractmethod
    def stream(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """Yields text deltas as they arrive. Concatenating every yielded
        piece reconstructs the full answer text."""


class OllamaLLMClient(LLMClient):
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        settings = self._settings
        payload = {
            "model": settings.ollama_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "options": {
                "temperature": temperature if temperature is not None else settings.llm_temperature,
                "num_predict": max_tokens if max_tokens is not None else settings.llm_max_tokens,
            },
        }
        async with (
            httpx.AsyncClient(
                base_url=settings.ollama_base_url, transport=self._transport, timeout=120.0
            ) as client,
            client.stream("POST", "/api/chat", json=payload) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                delta = chunk.get("message", {}).get("content", "")
                if delta:
                    yield delta
                if chunk.get("done"):
                    break


def _sse_data_lines(raw_lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """Shared SSE framing for the two hosted clients: `data: <payload>`
    lines, ignoring blank lines, comments, and the `[DONE]` sentinel."""

    async def _generator() -> AsyncIterator[str]:
        async for line in raw_lines:
            if not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if payload == "[DONE]":
                return
            yield payload

    return _generator()


class OpenAICompatibleLLMClient(LLMClient):
    """Covers any provider speaking the OpenAI chat/completions format —
    OpenAI itself, NVIDIA NIM, Azure OpenAI, Groq, Together, etc. — chosen
    via `hosted_llm_base_url` / `hosted_llm_model` rather than a dedicated
    per-provider class."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport

    # Hosted free-tier APIs occasionally fail a request on an
    # otherwise-healthy connection. Measured against NVIDIA NIM's endpoint,
    # roughly one request in six comes back 404/502/503 and then succeeds
    # immediately on a retry with an identical payload.
    #
    # 404 is in this set deliberately, even though it normally means "no
    # such route": NVIDIA's serverless layer returns
    # `404 Function '<id>': Not found for account` when the model instance
    # isn't currently scheduled, which is a capacity condition, not a bad
    # model id. A genuinely wrong model id fails the same way on every
    # attempt and so still surfaces after the retries are exhausted.
    #
    # Retrying is safe only *before* the first token has reached the caller
    # — once streaming has started a retry would duplicate output, so
    # `_MAX_CONNECT_ATTEMPTS` covers only the connect-and-check-status
    # phase below, never a mid-stream failure.
    _MAX_CONNECT_ATTEMPTS = 4
    _RETRYABLE_STATUS_CODES = {404, 429, 502, 503, 504}

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        settings = self._settings
        payload = {
            "model": settings.hosted_llm_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "max_tokens": max_tokens if max_tokens is not None else settings.llm_max_tokens,
            "temperature": temperature if temperature is not None else settings.llm_temperature,
        }
        headers = {"Authorization": f"Bearer {settings.hosted_llm_api_key}"}

        for attempt in range(1, self._MAX_CONNECT_ATTEMPTS + 1):
            client = httpx.AsyncClient(
                base_url=settings.hosted_llm_base_url, transport=self._transport, timeout=120.0
            )
            try:
                async with client.stream(
                    "POST", "/chat/completions", json=payload, headers=headers
                ) as response:
                    if (
                        response.status_code in self._RETRYABLE_STATUS_CODES
                        and attempt < self._MAX_CONNECT_ATTEMPTS
                    ):
                        await asyncio.sleep(0.5 * attempt)
                        continue
                    response.raise_for_status()

                    async for payload_line in _sse_data_lines(response.aiter_lines()):
                        event = json.loads(payload_line)
                        choices = event.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta
                    return
            finally:
                await client.aclose()


class AnthropicLLMClient(LLMClient):
    """Anthropic's native Messages API — used when
    `HOSTED_LLM_PROVIDER=anthropic`. Kept as a separate implementation
    rather than shoe-horned into the OpenAI-compatible client because its
    request shape (top-level `system`, `content_block_delta` SSE events)
    and auth headers genuinely differ."""

    _API_BASE_URL = "https://api.anthropic.com"
    _API_VERSION = "2023-06-01"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport

    async def stream(
        self,
        messages: list[LLMMessage],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        settings = self._settings
        system_messages = [m.content for m in messages if m.role == "system"]
        conversation = [
            {"role": m.role, "content": m.content} for m in messages if m.role != "system"
        ]
        payload = {
            "model": settings.hosted_llm_model,
            "system": "\n\n".join(system_messages),
            "messages": conversation,
            "stream": True,
            "max_tokens": max_tokens if max_tokens is not None else settings.llm_max_tokens,
            "temperature": temperature if temperature is not None else settings.llm_temperature,
        }
        headers = {
            "x-api-key": settings.hosted_llm_api_key,
            "anthropic-version": self._API_VERSION,
        }
        async with (
            httpx.AsyncClient(
                base_url=self._API_BASE_URL, transport=self._transport, timeout=120.0
            ) as client,
            client.stream("POST", "/v1/messages", json=payload, headers=headers) as response,
        ):
            response.raise_for_status()
            async for payload_line in _sse_data_lines(response.aiter_lines()):
                event = json.loads(payload_line)
                if event.get("type") != "content_block_delta":
                    continue
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        yield text


def get_llm_client(settings: Settings | None = None) -> LLMClient:
    settings = settings or get_settings()
    if settings.llm_backend == "ollama":
        return OllamaLLMClient(settings)
    if settings.hosted_llm_provider == "anthropic":
        return AnthropicLLMClient(settings)
    return OpenAICompatibleLLMClient(settings)
