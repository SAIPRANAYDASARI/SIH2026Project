"""Hallmarking material: gold/silver purity grades, HUID structure, jeweller
registration. Feeds F4 (mark verification) plain-language explanations of
what a HUID means and F5's consumer-facing hallmarking content.
"""

from __future__ import annotations

from ingestion.core.html import extract_title
from ingestion.core.provenance import ParsedPage
from ingestion.crawlers.base import Crawler


class HallmarkingCrawler(Crawler):
    source_name = "hallmarking"
    seed_urls = [
        "https://www.bis.gov.in/index.php/hallmarking/",
        "https://www.bis.gov.in/index.php/hallmarking-2/huid/",
        "https://www.bis.gov.in/index.php/hallmarking-2/jewellers-registration/",
    ]

    def parse(self, content: bytes, url: str) -> ParsedPage:
        return ParsedPage(title=extract_title(content))
