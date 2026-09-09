"""Run the Step 12 full-pipeline evaluation harness against a live stack.

    docker compose exec backend python -m app.eval.cli run
    docker compose exec backend python -m app.eval.cli run \\
        --golden-set /path/to/other_set.jsonl

Needs the same prerequisites as `app.answer.cli ask`: crawled/processed
content, the reranker service up, and an LLM backend configured.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.eval.full_eval import run_full_eval
from app.eval.golden_set import load_golden_set

DEFAULT_GOLDEN_SET = Path(__file__).resolve().parents[3] / "eval" / "golden_set_full.jsonl"


async def run_eval_cli(golden_set_path: Path) -> None:
    settings = get_settings()
    golden_set = load_golden_set(golden_set_path)

    async with AsyncSessionLocal() as session:
        metrics = await run_full_eval(session, golden_set, settings=settings)

    print(f"Questions evaluated: {metrics.question_count}")
    print(f"Intent accuracy:          {metrics.intent_accuracy:.1%}")
    print(f"Citation precision:       {metrics.citation_precision:.1%}")
    print(f"Forced-refusal accuracy:  {metrics.forced_refusal_accuracy:.1%}")
    print(f"False-refusal rate:       {metrics.false_refusal_rate:.1%}")
    print(f"Average latency:          {metrics.average_latency_ms:.0f}ms")
    print()
    for pq in metrics.per_question:
        flags = []
        if not pq.intent_correct:
            flags.append("intent-mismatch")
        if not pq.citation_ok:
            flags.append("citation-issue")
        if not pq.refusal_correct:
            flags.append("refusal-mismatch")
        status = "OK" if not flags else f"FLAGS: {', '.join(flags)}"
        print(f"[{status}] {pq.question.query}")


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Manak Sahayak full-pipeline evaluation harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the golden set through the answer engine")
    run_parser.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN_SET)

    args = parser.parse_args()
    if args.command == "run":
        asyncio.run(run_eval_cli(args.golden_set))


if __name__ == "__main__":
    main()
