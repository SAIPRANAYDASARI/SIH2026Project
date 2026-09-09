"""bis.gov.in certification scheme sections: guidelines, fee schedules,
forms, circulars and FAQs for ISI, CRS, FMCS, Hallmarking and Eco Mark.

This is what feeds `schemes.rules_yaml_path` (Step 8's deterministic rules
engine) and the retrieval corpus's scheme-guidance chunks.
"""

from __future__ import annotations

from ingestion.core.html import extract_title
from ingestion.core.provenance import ParsedPage
from ingestion.crawlers.base import Crawler


class BISSchemesCrawler(Crawler):
    source_name = "bis_schemes"
    seed_urls = [
        "https://www.bis.gov.in/index.php/product-certification/",
        "https://www.bis.gov.in/index.php/compulsory-registration-scheme-crs/",
        "https://www.bis.gov.in/index.php/foreign-manufacturers-certification-scheme-fmcs/",
        "https://www.bis.gov.in/index.php/hallmarking/",
        "https://www.bis.gov.in/index.php/eco-mark-scheme/",
    ]

    def parse(self, content: bytes, url: str) -> ParsedPage:
        return ParsedPage(title=extract_title(content))
