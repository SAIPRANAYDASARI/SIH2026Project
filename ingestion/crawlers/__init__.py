"""One crawler module per source in docs/DATA_SOURCES.md. Each subclasses
`ingestion.crawlers.base.Crawler`, supplying its seed URLs and a
source-specific `parse()`. All politeness, retry, blob storage and
provenance behaviour is shared via `ingestion.core` and `Crawler.run()`.
"""
