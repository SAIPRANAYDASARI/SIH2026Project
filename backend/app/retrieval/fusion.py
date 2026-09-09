"""Reciprocal rank fusion.

score(d) = sum over each ranked list L containing d of 1 / (k + rank_L(d)),
with 1-indexed ranks and k defaulting to `settings.rrf_k` (60, per the
brief). Chosen over a raw-score-normalization fusion approach because BM25
and cosine-similarity scores live on incomparable scales — RRF sidesteps
that entirely by fusing on rank position instead of score magnitude.
"""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from typing import TypeVar

T = TypeVar("T", bound=Hashable)


def reciprocal_rank_fusion(ranked_lists: Sequence[Sequence[T]], *, k: int = 60) -> dict[T, float]:
    """`ranked_lists` is one or more lists of ids in descending relevance
    order (best first). Returns a fused score per id that appeared in at
    least one list; ids absent from a given list simply don't contribute a
    term for that list, per the standard RRF definition."""
    scores: dict[T, float] = {}

    for ranked_list in ranked_lists:
        for rank, item in enumerate(ranked_list, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)

    return scores


def fuse_and_rank(ranked_lists: Sequence[Sequence[T]], *, k: int = 60) -> list[T]:
    """Convenience wrapper returning ids sorted by fused score, descending.
    Ties broken by first-list rank order (stable sort over the first list's
    order preserves a sensible tiebreak instead of an arbitrary one)."""
    scores = reciprocal_rank_fusion(ranked_lists, k=k)
    return sorted(scores.keys(), key=lambda item: scores[item], reverse=True)
