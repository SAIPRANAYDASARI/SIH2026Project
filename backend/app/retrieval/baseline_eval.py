"""Baseline retrieval-quality metrics — recall@k and MRR — computed against
a small labeled golden set, using only the retrieval pipeline (no LLM
involved at all), per the brief's Step-4 instruction to establish baseline
recall numbers before the answer engine exists.

`eval/golden_set_sample.jsonl` ships a small (~10 question) starter set
covering the identifier/product-lookup/scheme-eligibility shapes the brief
describes. It is explicitly NOT the 150+-question golden set Step 12
builds — see that file's header comment and docs/EVALUATION.md.

Recall is computed against the *fused* (pre-rerank) candidate ordering by
default, since that is the meaningful "how good is retrieval on its own"
number; `--use-rerank` in the CLI additionally reports post-rerank numbers
for comparison, since reranking should only ever improve or hold recall
(it reorders a subset of the same candidates), and a regression there is a
useful signal.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.ml.embedding_client import EmbeddingClient
from app.ml.reranker_client import RerankerClient
from app.retrieval.dense import DenseRetriever
from app.retrieval.exact_match import ExactMatchRetriever
from app.retrieval.hybrid import load_candidate_chunks, rerank_candidates, select_candidates
from app.retrieval.sparse import SparseRetriever


@dataclass(frozen=True)
class GoldenQuestion:
    query: str
    expected_is_numbers: list[str]


@dataclass(frozen=True)
class BaselineMetrics:
    recall_at_k: dict[int, float]
    mrr: float
    question_count: int


def load_golden_set(path: Path) -> list[GoldenQuestion]:
    questions = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            questions.append(
                GoldenQuestion(
                    query=record["query"], expected_is_numbers=record["expected_is_numbers"]
                )
            )
    return questions


def recall_at_k(ranked_is_numbers: list[str | None], expected: list[str], k: int) -> float:
    """1.0 if any of the top-k retrieved chunks' IS numbers matches an
    expected IS number, else 0.0 — this is per-question recall; average
    across questions for the usual recall@k metric."""
    top_k = set(filter(None, ranked_is_numbers[:k]))
    return 1.0 if top_k & set(expected) else 0.0


def reciprocal_rank(ranked_is_numbers: list[str | None], expected: list[str]) -> float:
    expected_set = set(expected)
    for rank, is_number in enumerate(ranked_is_numbers, start=1):
        if is_number is not None and is_number in expected_set:
            return 1.0 / rank
    return 0.0


def summarize(
    per_question_rankings: list[list[str | None]],
    per_question_expected: list[list[str]],
    k_values: tuple[int, ...] = (1, 5, 10),
) -> BaselineMetrics:
    recalls = {
        k: sum(
            recall_at_k(ranking, expected, k)
            for ranking, expected in zip(per_question_rankings, per_question_expected, strict=True)
        )
        / len(per_question_rankings)
        for k in k_values
    }
    mrr = sum(
        reciprocal_rank(ranking, expected)
        for ranking, expected in zip(per_question_rankings, per_question_expected, strict=True)
    ) / len(per_question_rankings)

    return BaselineMetrics(recall_at_k=recalls, mrr=mrr, question_count=len(per_question_rankings))


async def run_baseline(
    session: AsyncSession,
    golden_set: list[GoldenQuestion],
    *,
    settings: Settings,
    sparse_retriever: SparseRetriever,
    dense_retriever: DenseRetriever,
    exact_match_retriever: ExactMatchRetriever,
    embedding_client: EmbeddingClient,
    reranker_client: RerankerClient | None = None,
    k_values: tuple[int, ...] = (1, 5, 10),
) -> tuple[BaselineMetrics, BaselineMetrics | None]:
    """Returns (fused_metrics, reranked_metrics). `reranked_metrics` is
    None unless `reranker_client` is provided."""
    fused_rankings: list[list[str | None]] = []
    reranked_rankings: list[list[str | None]] = []
    expected_lists: list[list[str]] = []

    for question in golden_set:
        _, candidate_ids, scores = await select_candidates(
            question.query,
            session,
            sparse_retriever=sparse_retriever,
            dense_retriever=dense_retriever,
            exact_match_retriever=exact_match_retriever,
            embedding_client=embedding_client,
            settings=settings,
        )
        candidates = await load_candidate_chunks(session, candidate_ids, scores)
        fused_rankings.append([c.is_number for c in candidates])
        expected_lists.append(question.expected_is_numbers)

        if reranker_client is not None:
            ranked = await rerank_candidates(
                question.query,
                list(candidates),
                reranker_client=reranker_client,
                top_k=max(k_values),
            )
            reranked_rankings.append([c.is_number for c in ranked])

    fused_metrics = summarize(fused_rankings, expected_lists, k_values)
    reranked_metrics = (
        summarize(reranked_rankings, expected_lists, k_values) if reranker_client else None
    )
    return fused_metrics, reranked_metrics
