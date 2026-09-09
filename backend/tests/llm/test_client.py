"""Each LLMClient implementation is tested against a mocked transport
(httpx.MockTransport) driving its real wire format — no live LLM server —
plus `get_llm_client` dispatch on `llm_backend` / `hosted_llm_provider`."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.client import (
    AnthropicLLMClient,
    LLMMessage,
    OllamaLLMClient,
    OpenAICompatibleLLMClient,
    get_llm_client,
)


@pytest.mark.asyncio
async def test_ollama_client_streams_ndjson_deltas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        assert payload["model"] == "llama3.1:8b"
        assert payload["stream"] is True
        body = "\n".join(
            [
                json.dumps({"message": {"content": "Hel"}, "done": False}),
                json.dumps({"message": {"content": "lo"}, "done": False}),
                json.dumps({"message": {"content": ""}, "done": True}),
            ]
        )
        return httpx.Response(200, content=body.encode())

    settings = Settings(ollama_base_url="http://ollama-test", ollama_model="llama3.1:8b")
    client = OllamaLLMClient(settings, transport=httpx.MockTransport(handler))

    deltas = [d async for d in client.stream([LLMMessage(role="user", content="hi")])]

    assert deltas == ["Hel", "lo"]


@pytest.mark.asyncio
async def test_openai_compatible_client_streams_sse_deltas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        assert payload["model"] == "meta/llama-3.1-70b-instruct"
        assert request.headers["authorization"] == "Bearer test-key"
        events = [
            {"choices": [{"delta": {"content": "Hel"}}]},
            {"choices": [{"delta": {"content": "lo"}}]},
        ]
        body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=body.encode())

    settings = Settings(
        hosted_llm_provider="openai",
        hosted_llm_base_url="https://integrate.api.nvidia.com/v1",
        hosted_llm_model="meta/llama-3.1-70b-instruct",
        hosted_llm_api_key="test-key",
    )
    client = OpenAICompatibleLLMClient(settings, transport=httpx.MockTransport(handler))

    deltas = [d async for d in client.stream([LLMMessage(role="user", content="hi")])]

    assert deltas == ["Hel", "lo"]


@pytest.mark.asyncio
async def test_openai_compatible_client_retries_transient_5xx_before_first_token() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(502, content=b"upstream blip")
        events = [{"choices": [{"delta": {"content": "OK"}}]}]
        body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
        return httpx.Response(200, content=body.encode())

    settings = Settings(
        hosted_llm_provider="openai",
        hosted_llm_base_url="https://integrate.api.nvidia.com/v1",
        hosted_llm_model="meta/llama-3.1-70b-instruct",
        hosted_llm_api_key="test-key",
    )
    client = OpenAICompatibleLLMClient(settings, transport=httpx.MockTransport(handler))

    deltas = [d async for d in client.stream([LLMMessage(role="user", content="hi")])]

    assert deltas == ["OK"]
    assert call_count == 2


@pytest.mark.asyncio
async def test_openai_compatible_client_retries_nvcf_404_not_scheduled() -> None:
    """NVIDIA's serverless layer returns 404 when the model instance isn't
    currently scheduled — a capacity condition, not a bad model id — so it
    has to be retried like a 503 rather than surfacing immediately."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                404, json={"status": 404, "detail": "Function 'abc': Not found for account"}
            )
        body = 'data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, content=body.encode())

    settings = Settings(
        hosted_llm_provider="openai",
        hosted_llm_base_url="https://integrate.api.nvidia.com/v1",
        hosted_llm_model="nvidia/nemotron-3-ultra-550b-a55b",
        hosted_llm_api_key="test-key",
    )
    client = OpenAICompatibleLLMClient(settings, transport=httpx.MockTransport(handler))

    deltas = [d async for d in client.stream([LLMMessage(role="user", content="hi")])]

    assert deltas == ["OK"]
    assert call_count == 2


@pytest.mark.asyncio
async def test_openai_compatible_client_gives_up_after_repeated_5xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"still down")

    settings = Settings(
        hosted_llm_provider="openai",
        hosted_llm_base_url="https://integrate.api.nvidia.com/v1",
        hosted_llm_model="meta/llama-3.1-70b-instruct",
        hosted_llm_api_key="test-key",
    )
    client = OpenAICompatibleLLMClient(settings, transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        [d async for d in client.stream([LLMMessage(role="user", content="hi")])]


@pytest.mark.asyncio
async def test_anthropic_client_streams_content_block_deltas() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        assert payload["system"] == "be helpful"
        assert request.headers["x-api-key"] == "test-key"
        events = [
            {"type": "message_start"},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hel"}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "lo"}},
            {"type": "message_stop"},
        ]
        body = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
        return httpx.Response(200, content=body.encode())

    settings = Settings(hosted_llm_provider="anthropic", hosted_llm_api_key="test-key")
    client = AnthropicLLMClient(settings, transport=httpx.MockTransport(handler))

    messages = [
        LLMMessage(role="system", content="be helpful"),
        LLMMessage(role="user", content="hi"),
    ]
    deltas = [d async for d in client.stream(messages)]

    assert deltas == ["Hel", "lo"]


def test_get_llm_client_dispatches_on_backend_and_provider() -> None:
    assert isinstance(get_llm_client(Settings(llm_backend="ollama")), OllamaLLMClient)
    assert isinstance(
        get_llm_client(Settings(llm_backend="hosted", hosted_llm_provider="anthropic")),
        AnthropicLLMClient,
    )
    assert isinstance(
        get_llm_client(Settings(llm_backend="hosted", hosted_llm_provider="openai")),
        OpenAICompatibleLLMClient,
    )
