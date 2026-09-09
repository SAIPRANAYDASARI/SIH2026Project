"""Shared crawler infrastructure: rate limiting, robots.txt compliance,
content-addressed blob storage, and provenance persistence. Every crawler in
`ingestion/crawlers` is built on top of these, so the politeness and
auditability guarantees live in one place instead of being re-implemented
(and potentially forgotten) per source.
"""
