"""Quality Control Order (QCO) product lists — normalized in Step 3 into the
`standards.is_qco_mandatory` / `applicable_schemes` columns. The brief calls
this "the single most valuable artifact in the project": the structured
product-to-scheme table that tells a manufacturer whether their product
needs compulsory certification at all.

QCOs are published as notifications (often PDF) by the Ministry of Consumer
Affairs / DPIIT, referenced from BIS's compulsory-registration pages, so
this crawler's seed list starts at the BIS index rather than a single fixed
document set — Step 3's parser normalizes whatever's found here into the
structured table.
"""

from __future__ import annotations

from ingestion.core.html import extract_title
from ingestion.core.provenance import ParsedPage
from ingestion.crawlers.base import Crawler


class QCOCrawler(Crawler):
    source_name = "qco"
    seed_urls = [
        "https://www.bis.gov.in/index.php/quality-control-orders/",
        "https://www.bis.gov.in/index.php/list-of-products-under-compulsory-certification/",
    ]

    def parse(self, content: bytes, url: str) -> ParsedPage:
        return ParsedPage(title=extract_title(content))
