"""Crawlers and the raw-document ingestion entrypoint (Step 2).

This package fetches from the public BIS sources listed in
`docs/DATA_SOURCES.md`, respects robots.txt and a 1-request-per-2-seconds
rate limit, retries with exponential backoff, writes every raw response to a
content-addressed blob store *before* parsing, and records full provenance
(source URL, fetch timestamp, HTTP status, content hash, parser version) as
a `Document` row via the backend's `app.models.document` table.

It reuses `backend/app`'s settings, DB session and ORM models directly
(same pattern as `worker/`) rather than duplicating them — see
`docs/DECISIONS.md`.

Legal constraint (see docs/DATA_SOURCES.md): only titles, scopes, metadata,
scheme guidance, QCO lists and public circulars are ever stored. No crawler
in this package fetches or stores full Indian Standard text.
"""
