"""Reciprocal rank fusion: correct arithmetic, items unique to one list
still score, and fuse_and_rank orders by descending fused score."""

from __future__ import annotations

from app.retrieval.fusion import fuse_and_rank, reciprocal_rank_fusion


def test_item_ranked_first_in_both_lists_scores_highest() -> None:
    scores = reciprocal_rank_fusion([["a", "b", "c"], ["a", "c", "b"]], k=60)

    assert scores["a"] == 1 / 61 + 1 / 61
    assert scores["a"] > scores["b"]
    assert scores["a"] > scores["c"]


def test_item_in_only_one_list_still_gets_a_score() -> None:
    scores = reciprocal_rank_fusion([["a", "b"], ["c"]], k=60)

    assert set(scores.keys()) == {"a", "b", "c"}
    assert scores["c"] == 1 / 61


def test_fuse_and_rank_orders_by_descending_fused_score() -> None:
    ranked = fuse_and_rank([["a", "b", "c"], ["b", "a", "c"]], k=60)

    assert ranked[0] in {"a", "b"}  # a and b tie for first (rank 1+2 vs 2+1)
    assert ranked[-1] == "c"  # c is last in both lists


def test_empty_lists_produce_empty_fusion() -> None:
    assert reciprocal_rank_fusion([]) == {}
    assert fuse_and_rank([[], []]) == []


def test_k_parameter_changes_relative_weighting() -> None:
    # A smaller k makes rank-1 dominate more heavily relative to lower ranks.
    small_k = reciprocal_rank_fusion([["a", "b"]], k=1)
    large_k = reciprocal_rank_fusion([["a", "b"]], k=1000)

    small_k_ratio = small_k["a"] / small_k["b"]
    large_k_ratio = large_k["a"] / large_k["b"]
    assert small_k_ratio > large_k_ratio
