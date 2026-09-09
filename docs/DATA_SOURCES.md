# Data sources

Crawlers (Step 2) and the parse → chunk → embed → index pipeline (Step 3)
are both implemented. The QCO product-to-scheme *normalization into the
`standards` table's columns* (as opposed to chunking QCO documents for
retrieval, which the pipeline below already does) is still open — deferred
to whichever of Steps 6/8 first needs it as structured data rather than
retrievable text. This doc records the legal constraint that governs
everything ingestion does, since it shaped the schema already in place from
Step 1.

## Legal constraint — read before writing any crawler

**Full texts of Indian Standards are copyrighted and sold by BIS. This
project does not index, store, or redistribute IS document text.**

Only the following are ingested:

- IS number, title, scope, technical committee, ICS code, publication year,
  amendment/reaffirmation status (`standards` table)
- Certification scheme guidelines, fee schedules, forms, circulars, FAQs
  (feeds `schemes.rules_yaml_path` and the retrieval corpus)
- The Quality Control Order (QCO) product-to-scheme list, normalized into a
  structured table
- Hallmarking material (purity grades, HUID structure, jeweller registration)
- Consumer material (BIS Care content, complaint procedures)

Where a user needs a standard's full text, the assistant points them to the
correct IS number to purchase from BIS rather than reproducing any of it.
This constraint is also stated in the root `README.md` and will be enforced
in code by the ingestion pipeline (Step 2: crawlers only fetch from the
sources below, never a full-standard-text endpoint) and by the answer
engine's guardrails (Step 5).

## Sources (crawled as of Step 2)

| Source | Content | Crawler module |
|---|---|---|
| services.bis.gov.in ("Know Your Standards" / BIS Connect) | Standards catalogue metadata | `ingestion/crawlers/bis_connect.py` |
| bis.gov.in scheme sections | Certification guidelines, fees, forms, circulars, FAQs | `ingestion/crawlers/bis_schemes.py` |
| QCO product lists | Product-to-scheme mandatory-certification table | `ingestion/crawlers/qco.py` |
| Hallmarking pages | Purity grades, HUID structure, jeweller registration | `ingestion/crawlers/hallmarking.py` |
| Consumer/BIS Care pages | Complaint procedures, mark explanations | `ingestion/crawlers/consumer.py` |

Every crawler: respects `robots.txt` (`ingestion/core/robots.py`), rate-limits
to one request per two seconds per host (`ingestion/core/rate_limiter.py`),
retries transient transport errors with exponential backoff
(`ingestion/core/http_client.py`, via `tenacity`), stores the raw response to
a content-addressed blob store *before* parsing
(`ingestion/core/blob_store.py`), and records full provenance — source URL,
fetch timestamp, HTTP status, content hash, parser version — as a `Document`
row (`ingestion/core/provenance.py`). Re-running a crawl on unchanged
upstream content is a no-op: `persist_document` matches on
`(source_name, content_hash)` and returns the existing row rather than
duplicating it.

Run a crawler: `python -m ingestion.cli crawl bis_connect` (or `all`), from
inside the worker container (`docker compose exec worker ...`) or a local
venv with `backend/requirements-dev.txt` and `ingestion/requirements.txt`
installed. The same code runs as a Celery task
(`worker/tasks/ingestion.py::crawl_source`) for scheduled refreshes.

## Ingestion pipeline (Step 3)

Once a `Document` is crawled, `python -m ingestion.cli process <source>|all`
(or the Celery task `worker/tasks/ingestion.py::process_documents`) parses
it, splits it into clause-aware chunks, embeds each chunk, and writes them
as `Chunk` rows:

- **Parsing** (`ingestion/parsing/`): HTML → headings/paragraphs/tables
  (tables become markdown, never flattened prose) via
  `html_parser.parse_html`; PDF → per-page paragraph text (table extraction
  not yet implemented for PDFs — see the caveat below and
  `docs/DECISIONS.md`) via `pdf_parser.parse_pdf`. Content is dispatched by
  its magic bytes (`%PDF-` vs everything else), not by source name.
- **Chunking** (`ingestion/chunking/chunker.py`): groups blocks into
  400-800 token chunks (`ingestion/chunking/tokens.py`) with ~15% word
  overlap between consecutive chunks, treating every block — including a
  table or a numbered-clause paragraph — as atomic and never splitting it
  across chunks. Each chunk gets a `context_header` like
  `"IS 15111 > 4.2 Requirements > Clause 4.2.1 (p. 12)"`.
- **Embedding** (`ingestion/embeddings/client.py`): BGE-M3 via a local
  Ollama server (`OLLAMA_BASE_URL` / `OLLAMA_EMBEDDING_MODEL`), fanned out
  with bounded concurrency since Ollama's endpoint embeds one prompt per
  call.
- **Indexing**: chunks are written with their embedding
  (`chunks.embedding`, pgvector) and full text
  (`chunks.text_content`, indexed via the `manak_search` non-stemming
  full-text configuration added in migration `0002_search_config.py`).
- **Idempotency**: re-running `process` on a document that already has
  chunks tagged with the current `CHUNKING_VERSION`
  (`ingestion/pipeline.py`) is a no-op — no re-parsing, no re-embedding. A
  version bump (when chunking logic changes meaningfully) deletes and
  regenerates that document's chunks.

**Parsing precision caveat:** this sandbox has no live network access to
BIS's site to hand-validate real page markup (confirmed while building this
step — direct HTTP to bis.gov.in is blocked by the sandbox's own egress
allowlist). `ingestion/core/html.py` therefore extracts generically (page
title, and any IS-number-shaped token via regex) rather than using
site-specific CSS selectors. The fetch → robots → rate-limit → retry →
blob-store → provenance pipeline is fully real and unit tested; only
parsing precision needs tightening once run against live pages on a machine
with real network access. See `docs/DECISIONS.md`.
