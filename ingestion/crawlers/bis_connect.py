"""BIS Connect / "Know Your Standards" — the published standards catalogue.

Indexes only metadata (IS number, title) per the legal constraint in
docs/DATA_SOURCES.md. Full standard text is never fetched: this crawler's
seed list points at catalogue/search pages, not any standard-purchase or
full-text endpoint.
"""

from __future__ import annotations

from ingestion.core.html import extract_first_is_number, extract_title
from ingestion.core.provenance import ParsedPage
from ingestion.crawlers.base import Crawler


class BISConnectCrawler(Crawler):
    source_name = "bis_connect"
    seed_urls = [
        "https://www.services.bis.gov.in/php/BIS_2.0/knowyourstandards/",
        "https://www.services.bis.gov.in/php/BIS_2.0/bisconnect/",
    ]

    def parse(self, content: bytes, url: str) -> ParsedPage:
        return ParsedPage(
            title=extract_title(content),
            is_number=extract_first_is_number(content),
        )
