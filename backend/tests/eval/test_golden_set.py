from __future__ import annotations

from pathlib import Path

from app.eval.golden_set import load_golden_set
from app.retrieval.query_understanding import Intent

REPO_GOLDEN_SET = Path(__file__).resolve().parents[3] / "eval" / "golden_set_full.jsonl"


def test_shipped_golden_set_parses_and_covers_every_intent() -> None:
    questions = load_golden_set(REPO_GOLDEN_SET)
    assert len(questions) >= 20
    intents = {q.expected_intent for q in questions}
    assert intents == set(Intent)


def test_refusal_questions_have_expects_refusal_true() -> None:
    questions = load_golden_set(REPO_GOLDEN_SET)
    out_of_scope = [q for q in questions if q.expected_intent == Intent.OUT_OF_SCOPE]
    assert out_of_scope
    assert all(q.expects_refusal for q in out_of_scope)
