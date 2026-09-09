"""Interrogate the retrieval core directly — no answer engine, no API, just
the hybrid search pipeline. Per the brief's Step-4 instruction: "Retrieval
core with a CLI I can interrogate, plus baseline recall numbers before any
LLM is involved."

Run from inside the backend container (it needs `app.db.session`, a live
Postgres with crawled+chunked+embedded content, and — for `--rerank` /
`baseline` — the `reranker` service running):

    docker compose exec backend python -m app.retrieval.cli query \\
        "which standard covers LED drivers?"
    docker compose exec backend python -m app.retrieval.cli query \\
        "IS 15111 clause 4.2" --no-rerank
    docker compose exec backend python -m app.retrieval.cli baseline
    docker compose exec backend python -m app.retrieval.cli baseline \\
        --golden-set eval/golden_set_sample.jsonl --no-rerank
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import AsyncSessionLocal
from app.ml.embedding_client import get_embedding_client
from app.ml.reranker_client import get_reranker_client
from app.retrieval.baseline_eval import load_golden_set, run_baseline
from app.retrieval.dense import PgVectorRetriever
from app.retrieval.exact_match import ChunkExactMatchRetriever
from app.retrieval.hybrid import hybrid_search, load_candidate_chunks, select_candidates
from app.retrieval.models import RetrievedChunk
from app.retrieval.sparse import PostgresFTSRetriever

logger = get_logger(__name__)


def _print_result(rank: int, chunk: RetrievedChunk) -> None:
    sources = ",".join(sorted(s.value for s in chunk.sources))
    print(f"\n[{rank}] {chunk.is_number or '(no IS number)'} — {chunk.document_title}")
    print(f"    section: {chunk.section_path or '-'}  clause: {chunk.clause_number or '-'}")
    print(
        "    scores: sparse="
        f"{_fmt(chunk.sparse_score)} dense={_fmt(chunk.dense_score)} "
        f"fused={_fmt(chunk.fused_score)} rerank={_fmt(chunk.rerank_score)}  sources=[{sources}]"
    )
    print(f"    {chunk.text_content[:220].replace(chr(10), ' ')}...")


def _fmt(value: float | None) -> str:
    return f"{value:.4f}" if value is not None else "-"


async def run_query(query_text: str, use_rerank: bool) -> None:
    async with AsyncSessionLocal() as session:
        if use_rerank:
            analysis, results = await hybrid_search(session, query_text)
        else:
            settings = get_settings()
            analysis, candidate_ids, scores = await select_candidates(
                query_text,
                session,
                sparse_retriever=PostgresFTSRetriever(),
                dense_retriever=PgVectorRetriever(),
                exact_match_retriever=ChunkExactMatchRetriever(),
                embedding_client=get_embedding_client(),
                settings=settings,
            )
            candidates = await load_candidate_chunks(
                session, candidate_ids[: settings.rerank_top_k], scores
            )
            results = candidates

    print(f"intent: {analysis.intent.value}")
    print(f"identifiers: {[(i.type.value, i.value) for i in analysis.identifiers]}")
    for rank, chunk in enumerate(results, start=1):
        _print_result(rank, chunk)


async def run_baseline_cli(golden_set_path: Path, use_rerank: bool) -> None:
    settings = get_settings()
    golden_set = load_golden_set(golden_set_path)

    async with AsyncSessionLocal() as session:
        fused_metrics, reranked_metrics = await run_baseline(
            session,
            golden_set,
            settings=settings,
            sparse_retriever=PostgresFTSRetriever(),
            dense_retriever=PgVectorRetriever(),
            exact_match_retriever=ChunkExactMatchRetriever(),
            embedding_client=get_embedding_client(),
            reranker_client=get_reranker_client() if use_rerank else None,
        )

    print(f"Baseline over {fused_metrics.question_count} questions from {golden_set_path}\n")
    print("Fused (pre-rerank):")
    for k, recall in sorted(fused_metrics.recall_at_k.items()):
        print(f"  recall@{k}: {recall:.3f}")
    print(f"  MRR: {fused_metrics.mrr:.3f}")

    if reranked_metrics:
        print("\nReranked:")
        for k, recall in sorted(reranked_metrics.recall_at_k.items()):
            print(f"  recall@{k}: {recall:.3f}")
        print(f"  MRR: {reranked_metrics.mrr:.3f}")


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Manak Sahayak retrieval core CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    query_parser = subparsers.add_parser("query", help="Run one query through hybrid search")
    query_parser.add_argument("text")
    query_parser.add_argument(
        "--no-rerank", action="store_true", help="Skip the cross-encoder rerank stage"
    )

    baseline_parser = subparsers.add_parser(
        "baseline", help="Compute recall@k/MRR against a golden set"
    )
    baseline_parser.add_argument(
        "--golden-set",
        type=Path,
        default=Path("/eval/golden_set_sample.jsonl"),
        help="Defaults to the Step-4 starter set mounted at /eval in the backend "
        "container (infra/docker-compose.yml); pass a different path outside Docker.",
    )
    baseline_parser.add_argument(
        "--no-rerank", action="store_true", help="Skip reranked metrics (fused-only)"
    )

    args = parser.parse_args()

    if args.command == "query":
        asyncio.run(run_query(args.text, use_rerank=not args.no_rerank))
    elif args.command == "baseline":
        asyncio.run(run_baseline_cli(args.golden_set, use_rerank=not args.no_rerank))


if __name__ == "__main__":
    main()
