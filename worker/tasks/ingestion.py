"""Celery tasks wrapping the ingestion crawlers.

Thin wrappers only — all real logic lives in `ingestion.cli.run_crawler` so
the scheduled-refresh path (this task) and the manual-interrogation path
(`python -m ingestion.cli crawl <source>`) are guaranteed to behave
identically, per `ingestion/cli.py`'s docstring.
"""

from __future__ import annotations

import asyncio

from celery_app import celery_app

from ingestion.cli import CRAWLERS, run_crawler, run_pipeline


@celery_app.task(name="tasks.ingestion.crawl_source")
def crawl_source(source_name: str) -> dict[str, int]:
    if source_name not in CRAWLERS:
        raise ValueError(f"Unknown ingestion source: {source_name!r}")
    return asyncio.run(run_crawler(source_name))


@celery_app.task(name="tasks.ingestion.crawl_all")
def crawl_all() -> dict[str, dict[str, int]]:
    return {name: crawl_source(name) for name in CRAWLERS}


@celery_app.task(name="tasks.ingestion.process_documents")
def process_documents(source_name: str | None = None) -> dict[str, int]:
    """Parse/chunk/embed crawled documents. Run after crawl_source/crawl_all
    (or scheduled independently, since it's idempotent — see
    ingestion/pipeline.py)."""
    return asyncio.run(run_pipeline(source_name))
