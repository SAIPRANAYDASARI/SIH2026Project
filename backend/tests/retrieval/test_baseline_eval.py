"""recall_at_k / reciprocal_rank / summarize — pure metric functions, tested
against synthetic rankings so correctness doesn't depend on a live corpus."""

from __future__ import annotations

from pathlib import Path

from app.retrieval.baseline_eval import (
    load_golden_set,
    recall_at_k,
    reciprocal_rank,
    summarize,
)


def test_recall_at_k_hit_within_k() -> None:
    ranking = ["IS 999", "IS 15111", "IS 111"]
    assert recall_at_k(ranking, ["IS 15111"], k=2) == 1.0
    assert recall_at_k(ranking, ["IS 15111"], k=1) == 0.0


def test_recall_at_k_handles_none_entries() -> None:
    ranking = [None, "IS 15111", None]
    assert recall_at_k(ranking, ["IS 15111"], k=3) == 1.0


def test_recall_at_k_no_match() -> None:
    ranking = ["IS 1", "IS 2"]
    assert recall_at_k(ranking, ["IS 999"], k=2) == 0.0


def test_reciprocal_rank_of_first_correct_hit() -> None:
    ranking = ["IS 1", "IS 15111", "IS 2"]
    assert reciprocal_rank(ranking, ["IS 15111"]) == 1 / 2


def test_reciprocal_rank_no_hit_is_zero() -> None:
    assert reciprocal_rank(["IS 1", "IS 2"], ["IS 999"]) == 0.0


def test_summarize_averages_across_questions() -> None:
    rankings = [["IS 1"], ["IS 999"]]  # first question hits, second misses
    expected = [["IS 1"], ["IS 2"]]

    metrics = summarize(rankings, expected, k_values=(1,))

    assert metrics.recall_at_k[1] == 0.5
    assert metrics.mrr == 0.5
    assert metrics.question_count == 2


def test_load_golden_set_parses_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "golden.jsonl"
    path.write_text(
        '{"query": "What is IS 15111?", "expected_is_numbers": ["IS 15111"]}\n'
        "\n"  # blank lines are skipped
        '{"query": "What is IS 302?", "expected_is_numbers": ["IS 302"]}\n'
    )

    questions = load_golden_set(path)

    assert len(questions) == 2
    assert questions[0].query == "What is IS 15111?"
    assert questions[0].expected_is_numbers == ["IS 15111"]


def test_sample_golden_set_file_parses() -> None:
    # Guards against the shipped eval/golden_set_sample.jsonl bit-rotting
    # into invalid JSON without a test noticing.
    sample_path = Path(__file__).resolve().parents[3] / "eval" / "golden_set_sample.jsonl"
    questions = load_golden_set(sample_path)
    assert len(questions) >= 5
    assert all(q.expected_is_numbers for q in questions)
