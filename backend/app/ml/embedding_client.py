"""BGE-M3 embeddings via a local Ollama server.

Lives under `app.ml` (not `ingestion`) because both ingestion (embedding
chunks at index time) and `app.retrieval` (embedding the query at search
time) need the *exact same* model and request shape — if they drifted,
query vectors and stored chunk vectors would live in subtly different
spaces and cosine similarity would quietly degrade. `ingestion.embeddings`
re-exports this module for backward compatibility (see that module).

Ollama's `/api/embeddings` endpoint takes one prompt per call rather than a
batch, so `embed_batch` fans out with bounded concurrency rather than
issuing one request per text sequentially.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings, get_settings

MAX_CONCURRENT_REQUESTS = 4


class EmbeddingClient(ABC):
    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_one(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]


class OllamaEmbeddingClient(EmbeddingClient):
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # `transport` is only ever overridden in tests (httpx.MockTransport).
        self._settings = settings or get_settings()
        self._transport = transport

    async def _embed_one_http(self, client: httpx.AsyncClient, text: str) -> list[float]:
        response = await client.post(
            "/api/embeddings",
            json={"model": self._settings.ollama_embedding_model, "prompt": text},
            timeout=60.0,
        )
        response.raise_for_status()
        embedding = response.json()["embedding"]
        return list(embedding)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

        async def _bounded(client: httpx.AsyncClient, text: str) -> list[float]:
            async with semaphore:
                return await self._embed_one_http(client, text)

        async with httpx.AsyncClient(
            base_url=self._settings.ollama_base_url, transport=self._transport
        ) as client:
            return list(await asyncio.gather(*(_bounded(client, text) for text in texts)))


def get_embedding_client() -> EmbeddingClient:
    return OllamaEmbeddingClient()
