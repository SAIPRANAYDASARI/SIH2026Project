"""BGE-M3 embeddings.

BGE-M3 is used because this corpus is bilingual and its answers must not be:
it maps Hindi and English into one shared space, so a question typed in Hindi
retrieves the English legal provision that actually answers it. That property
is what makes "multilingual" real here, given that the Hindi text inside many
of these gazettes is too corrupted to index (see rag/quality.py).

The model runs locally, on GPU when one is available and CPU otherwise —
this only speeds up building/re-embedding the index (encoding ~30k chunks
once); it has no effect on the hosted LLM or on answering a single question,
both of which are fast enough on CPU already. Loading is deferred until
first use so that keyword-only search never pays the several-second model
load.
"""

from __future__ import annotations

import numpy as np

from rag import config

_model = None


def _pick_device() -> str:
    forced = config.EMBEDDING_DEVICE
    if forced:
        return forced
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(config.EMBEDDING_MODEL, device=_pick_device())
    return _model


def embed_texts(texts: list[str], *, batch_size: int | None = None, progress: bool = False) -> np.ndarray:
    """Embed documents. Vectors are L2-normalised so cosine similarity is a
    plain dot product."""
    if not texts:
        return np.zeros((0, config.EMBEDDING_DIM), dtype=np.float32)
    model = get_model()
    vectors = model.encode(
        texts,
        batch_size=batch_size or config.EMBEDDING_BATCH,
        normalize_embeddings=True,
        show_progress_bar=progress,
        convert_to_numpy=True,
    )
    return np.asarray(vectors, dtype=np.float32)


def embed_query(text: str) -> np.ndarray:
    """Embed a single query. BGE-M3 needs no special query prefix, unlike the
    E5 family, so query and document encoding are symmetric."""
    return embed_texts([text])[0]
