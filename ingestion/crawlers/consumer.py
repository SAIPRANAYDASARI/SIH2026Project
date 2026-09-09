"""Consumer-facing material: BIS Care content, complaint procedures, what
each certification mark guarantees. Feeds F4's complaint-guide generation
and F5's consumer persona content.
"""

from __future__ import annotations

from ingestion.core.html import extract_title
from ingestion.core.provenance import ParsedPage
from ingestion.crawlers.base import Crawler


class ConsumerCrawler(Crawler):
    source_name = "consumer"
    seed_urls = [
        "https://www.bis.gov.in/index.php/consumer-affairs/",
        "https://www.bis.gov.in/index.php/complaints/",
        "https://bis.gov.in/index.php/bis-care/",
    ]

    def parse(self, content: bytes, url: str) -> ParsedPage:
        return ParsedPage(title=extract_title(content))
