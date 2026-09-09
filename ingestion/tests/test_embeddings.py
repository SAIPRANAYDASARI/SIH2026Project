"""OllamaEmbeddingClient calls the local Ollama embeddings endpoint per
text and returns vectors in the same order as the input, using a mocked
transport so no real Ollama server is required."""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from ingestion.embeddings.client import OllamaEmbeddingClient


def _client(handler: httpx.MockTransport) -> OllamaEmbeddingClient:
    settings = Settings(ollama_base_url="http://ollama-test", ollama_embedding_model="bge-m3")
    return OllamaEmbeddingClient(settings, transport=handler)


@pytest.mark.asyncio
async def test_embed_batch_returns_one_vector_per_text_in_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        assert payload["model"] == "bge-m3"
        # Deterministic fake vector keyed to prompt length, so the test can
        # verify results come back in the same order as the input texts.
        return httpx.Response(200, json={"embedding": [float(len(payload["prompt"]))] * 4})

    client = _client(httpx.MockTransport(handler))

    vectors = await client.embed_batch(["short", "a longer text string"])

    assert vectors == [[float(len("short"))] * 4, [float(len("a longer text string"))] * 4]


@pytest.mark.asyncio
async def test_embed_batch_empty_input_returns_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not be called for empty input")

    client = _client(httpx.MockTransport(handler))

    assert await client.embed_batch([]) == []


@pytest.mark.asyncio
async def test_embed_batch_propagates_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "model not loaded"})

    client = _client(httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        await client.embed_batch(["text"])
