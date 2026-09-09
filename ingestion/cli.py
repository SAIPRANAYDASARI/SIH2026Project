"""CLI entrypoint for running crawlers and the ingestion pipeline.

Usage (from the repo root, with the backend's venv active or inside the
worker/backend container where `app` is importable):

    python -m ingestion.cli crawl bis_connect
    python -m ingestion.cli crawl all
    python -m ingestion.cli process all
    python -m ingestion.cli process --source bis_connect

`docs/DATA_SOURCES.md` lists what each source name fetches. This CLI is
also what the Celery tasks in `worker/tasks/ingestion.py` call internally,
so `docker compose` scheduled refreshes and manual interrogation both run
the exact same code path.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running as `python -m ingestion.cli` from the repo root without
# installing anything, by putting the backend's `app` package (and this
# repo root, for `ingestion` itself) on sys.path. Mirrors worker/celery_app.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))
sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.document import Document  # noqa: E402
from ingestion.core.blob_store import BlobStore  # noqa: E402
from ingestion.crawlers.base import Crawler  # noqa: E402
from ingestion.crawlers.bis_connect import BISConnectCrawler  # noqa: E402
from ingestion.crawlers.bis_schemes import BISSchemesCrawler  # noqa: E402
from ingestion.crawlers.consumer import ConsumerCrawler  # noqa: E402
from ingestion.crawlers.hallmarking import HallmarkingCrawler  # noqa: E402
from ingestion.crawlers.qco import QCOCrawler  # noqa: E402
from ingestion.embeddings.client import get_embedding_client  # noqa: E402
from ingestion.pipeline import process_document  # noqa: E402

CRAWLERS: dict[str, type[Crawler]] = {
    "bis_connect": BISConnectCrawler,
    "bis_schemes": BISSchemesCrawler,
    "qco": QCOCrawler,
    "hallmarking": HallmarkingCrawler,
    "consumer": ConsumerCrawler,
}

logger = get_logger(__name__)


async def run_crawler(name: str) -> dict[str, int]:
    settings = get_settings()
    blob_store = BlobStore(Path(settings.blob_store_path))
    crawler = CRAWLERS[name]()

    async with AsyncSessionLocal() as session:
        return await crawler.run(session, blob_store)


async def run_all() -> dict[str, dict[str, int]]:
    results: dict[str, dict[str, int]] = {}
    for name in CRAWLERS:
        results[name] = await run_crawler(name)
    return results


async def run_pipeline(source_name: str | None) -> dict[str, int]:
    """Parses, chunks and embeds every crawled Document (optionally filtered
    to one source) that doesn't already have up-to-date chunks."""
    settings = get_settings()
    blob_store = BlobStore(Path(settings.blob_store_path))
    embedding_client = get_embedding_client()
    stats = {"created": 0, "unchanged": 0, "skipped_empty": 0}

    async with AsyncSessionLocal() as session:
        query = select(Document)
        if source_name:
            query = query.where(Document.source_name == source_name)
        documents = list((await session.execute(query)).scalars())

        for document in documents:
            result = await process_document(session, blob_store, document, embedding_client)
            stats[result.status] += 1

    return stats


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="Manak Sahayak ingestion crawlers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl_parser = subparsers.add_parser("crawl", help="Run one crawler (or 'all')")
    crawl_parser.add_argument("source", choices=[*CRAWLERS.keys(), "all"])

    process_parser = subparsers.add_parser(
        "process", help="Parse/chunk/embed crawled documents (idempotent)"
    )
    process_parser.add_argument(
        "--source", choices=[*CRAWLERS.keys()], default=None, help="Restrict to one source"
    )

    args = parser.parse_args()

    if args.command == "crawl":
        if args.source == "all":
            results = asyncio.run(run_all())
            for source, stats in results.items():
                logger.info("crawler_result", source=source, **stats)
        else:
            stats = asyncio.run(run_crawler(args.source))
            logger.info("crawler_result", source=args.source, **stats)
    elif args.command == "process":
        stats = asyncio.run(run_pipeline(args.source))
        logger.info("pipeline_result", source=args.source or "all", **stats)


if __name__ == "__main__":
    main()
