"""Cross-encoder reranking via a local Infinity server serving
bge-reranker-v2-m3.

Ollama does not serve cross-encoder rerank models (its API is generation
and embeddings only), so the reranker runs in a separate local inference
container — `michaelfeil/infinity`, a small, actively-maintained,
Cohere-rerank-API-compatible server that supports BAAI/bge-reranker-v2-m3
directly — added as the `reranker` service in `infra/docker-compose.yml`.
This keeps the "fully offline, single laptop" requirement intact (decision
#3 in docs/DECISIONS.md) without inventing a bespoke rerank protocol.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class RerankResult:
    index: int  # index into the original `documents` list passed in
    score: float


class RerankerClient(ABC):
    @abstractmethod
    async def rerank(self, query: str, documents: list[str]) -> list[RerankResult]:
        """Returns one RerankResult per input document, sorted by
        descending score (highest relevance first)."""


class InfinityRerankerClient(RerankerClient):
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport

    async def rerank(self, query: str, documents: list[str]) -> list[RerankResult]:
        if not documents:
            return []

        async with httpx.AsyncClient(
            base_url=self._settings.reranker_base_url, transport=self._transport
        ) as client:
            response = await client.post(
                "/rerank",
                json={
                    "model": self._settings.reranker_model,
                    "query": query,
                    "documents": documents,
                },
                timeout=180.0,
            )
            response.raise_for_status()
            body = response.json()

        results = [
            RerankResult(index=item["index"], score=float(item["relevance_score"]))
            for item in body["results"]
        ]
        return sorted(results, key=lambda r: r.score, reverse=True)


def get_reranker_client() -> RerankerClient:
    return InfinityRerankerClient()
