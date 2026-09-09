"""Re-exports `app.ml.embedding_client`.

The real implementation moved there in Step 4 so `app.retrieval` (query-time
embedding) and this ingestion package (index-time embedding) share one
client and can never drift onto different models/request shapes. This shim
exists so `ingestion.pipeline`, `ingestion.cli` and existing tests that
import from `ingestion.embeddings.client` keep working unchanged.
"""

from __future__ import annotations

from app.ml.embedding_client import (
    MAX_CONCURRENT_REQUESTS,
    EmbeddingClient,
    OllamaEmbeddingClient,
    get_embedding_client,
)

__all__ = [
    "MAX_CONCURRENT_REQUESTS",
    "EmbeddingClient",
    "OllamaEmbeddingClient",
    "get_embedding_client",
]
