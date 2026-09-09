"""Interrogate the answer engine directly — retrieval plus a real LLM call,
no API server, no persistence. Mirrors `app.retrieval.cli`'s pattern from
Step 4 for the same reason: something runnable and demoable before the API
surface (Step 6) exists.

Run from inside the backend container:

    docker compose exec backend python -m app.answer.cli ask \\
        "which standard covers LED drivers?"
    docker compose exec backend python -m app.answer.cli ask \\
        "is this HUID AZ4526 genuine?" --audience consumer

Needs `LLM_BACKEND` configured in `.env` (`ollama` for the offline path, or
`hosted` with `HOSTED_LLM_API_KEY` set) in addition to Step 4's retrieval
prerequisites (crawled + processed content, the `reranker` service up).
"""

from __future__ import annotations

import argparse
import asyncio

from app.answer.engine import FinalEvent, TokenEvent, stream_answer
from app.core.logging import configure_logging, get_logger
from app.db.session import AsyncSessionLocal
from app.models.conversation import Audience

logger = get_logger(__name__)


async def run_ask(query_text: str, audience: Audience) -> None:
    async with AsyncSessionLocal() as session:
        async for event in stream_answer(session, query_text, audience=audience):
            if isinstance(event, TokenEvent):
                print(event.text, end="", flush=True)
            elif isinstance(event, FinalEvent):
                result = event.result
                print("\n\n---")
                print(f"model: {result.model_backend}  latency: {result.latency_ms}ms")
                print(f"intent: {result.query_analysis.intent.value}")
                if result.forced_refusal:
                    print("forced refusal: no retrieval results, LLM was not called")
                if result.citations:
                    print("citations:")
                    for citation in result.citations:
                        print(
                            f"  [{citation.marker}] {citation.is_number or '(no IS number)'} "
                            f"clause {citation.clause_number or '-'} — {citation.document_title}"
                        )
                if result.invalid_citation_markers:
                    markers = result.invalid_citation_markers
                    print(f"invalid citation markers (hallucinated sources): {markers}")
                if result.guardrail_violations:
                    print("guardrail actions taken:")
                    for violation in result.guardrail_violations:
                        print(f"  - {violation}")


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Manak Sahayak answer engine CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask_parser = subparsers.add_parser("ask", help="Ask one question end-to-end")
    ask_parser.add_argument("text")
    ask_parser.add_argument("--audience", choices=["industry", "consumer"], default="consumer")

    args = parser.parse_args()

    if args.command == "ask":
        asyncio.run(run_ask(args.text, Audience(args.audience)))


if __name__ == "__main__":
    main()
