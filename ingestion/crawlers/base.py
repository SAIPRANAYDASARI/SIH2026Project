"""Base crawler: fetch each seed URL politely, parse it, persist provenance.

Subclasses declare `source_name` and `seed_urls`, and implement `parse()` to
turn raw bytes into a `ParsedPage`. Everything else — robots.txt, rate
limiting, retries, content-addressed storage, idempotent persistence — is
inherited from `run()`.

A production crawl would discover URLs dynamically (sitemap, pagination,
category listings) rather than a fixed seed list; Step 2 ships fixed seed
lists for the pages the brief names explicitly, and `docs/DATA_SOURCES.md`
records where dynamic discovery would extend each crawler.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from ingestion.core.blob_store import BlobStore
from ingestion.core.http_client import PoliteFetcher, RobotsDisallowedError
from ingestion.core.provenance import ParsedPage, persist_document

logger = get_logger(__name__)


class Crawler(ABC):
    source_name: str
    seed_urls: list[str]

    @abstractmethod
    def parse(self, content: bytes, url: str) -> ParsedPage: ...

    async def run(self, session: AsyncSession, blob_store: BlobStore) -> dict[str, int]:
        stats = {"fetched": 0, "created": 0, "unchanged": 0, "skipped": 0, "failed": 0}

        async with PoliteFetcher() as fetcher:
            for url in self.seed_urls:
                try:
                    fetch_result = await fetcher.fetch(url)
                except RobotsDisallowedError:
                    stats["skipped"] += 1
                    continue
                except Exception:  # noqa: BLE001 - one bad URL must not abort the run
                    logger.exception("crawl_fetch_failed", source=self.source_name, url=url)
                    stats["failed"] += 1
                    continue

                stats["fetched"] += 1

                if fetch_result.status_code >= 400:
                    logger.warning(
                        "crawl_http_error",
                        source=self.source_name,
                        url=url,
                        status=fetch_result.status_code,
                    )
                    stats["failed"] += 1
                    continue

                parsed = self.parse(fetch_result.content, url)
                _, created = await persist_document(
                    session,
                    blob_store,
                    source_name=self.source_name,
                    fetch_result=fetch_result,
                    parsed=parsed,
                )
                stats["created" if created else "unchanged"] += 1

        await session.commit()
        logger.info("crawl_complete", source=self.source_name, **stats)
        return stats
