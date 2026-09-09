# Architecture

## System diagram (textual)

```
Clients (React/Vite)
    │  REST + SSE streaming
    ▼
FastAPI (auth, rate limiting, audit logging)
    │
    ▼
Orchestration layer
  (query router → intent classifier → answer composer → citation validator → guardrails)
    │
    ├── Retrieval path: BM25 (Postgres FTS) + dense (BGE-M3 via pgvector)
    │                    → reciprocal rank fusion (k=60)
    │                    → cross-encoder rerank (bge-reranker-v2-m3)
    │                    → top 8 chunks
    │
    └── Rules path: deterministic scheme decision tree, fee tables (YAML),
                     checklist templates, licence lookup

Both feed the answer composer.

Storage: PostgreSQL 16 + pgvector (standards, schemes, chunks, conversations,
messages, licences, audit log) + Redis (rate limiting, Celery broker/result,
SSE fanout) + a local content-addressed blob store (raw crawled documents).

Ingestion: Celery workers run PDF parsing, clause-aware chunking, metadata
extraction and scheduled refresh, on the same `app` package as the API so
both share settings, models and DB session handling.
```

## Status (Step 13 of 14)

- **Step 1** — repo scaffold, Docker Compose bringing up every service the
  full system needs (Postgres+pgvector, Redis, backend, worker, frontend,
  Ollama), the initial database schema (via Alembic), the shared type
  contract between backend Pydantic schemas and frontend TypeScript, and CI
  running lint/type-check/test for both backend and frontend plus a Docker
  build smoke test. `/api/v1/health` is the only real business endpoint.
- **Step 2** — polite crawlers (robots.txt, rate limiting, retry/backoff)
  for BIS Connect, schemes, QCOs, hallmarking, and consumer-complaint
  sources, a content-addressed blob store, and full provenance persistence.
- **Step 3** — the ingestion pipeline: clause-aware HTML/PDF parsing,
  block-atomic chunking (never splits a table or clause), BGE-M3 embedding
  via Ollama, and idempotent indexing into `documents`/`chunks`, plus the
  `manak_search` non-stemming full-text-search configuration.
- **Step 4 (this step)** — the retrieval core: BM25 (Postgres FTS) + dense
  (pgvector cosine) search fused with reciprocal rank fusion, cross-encoder
  reranking (bge-reranker-v2-m3 via Infinity), exact-identifier routing
  (IS numbers, clause references) ahead of fuzzy search, a query-understanding
  module (identifier extraction + heuristic intent classification), a CLI to
  interrogate the pipeline directly, and a baseline recall@k/MRR harness —
  all with **no LLM in the loop**, per the brief's explicit step ordering.

- **Step 5 (this step)** — the answer engine: a pluggable LLM adapter
  (`app/llm`) with three real implementations (local Ollama, Anthropic
  native, and a generic OpenAI-compatible client covering NVIDIA NIM/OpenAI/
  Azure/Groq/Together), prompt construction with a numbered `[N]` citation
  convention (`app/answer/prompts.py`), a citation validator that resolves
  those markers back to real chunk metadata and flags hallucinated ones
  (`app/answer/citations.py`), a guardrail layer that actively redacts
  long verbatim reproductions of a standard's text and forces a fixed
  refusal when retrieval finds nothing (`app/answer/guardrails.py`), and
  the orchestration tying it together with token-level streaming
  (`app/answer/engine.py`) plus a CLI.

- **Step 6 (this step)** — the FastAPI surface and persistence: `POST
  /api/v1/chat` streams a grounded answer over Server-Sent Events
  (`conversation`/`token`/`final`/`error` events) while persisting both the
  user's message and the assistant's final answer, `GET /api/v1/conversations`
  and `GET /api/v1/conversations/{id}/messages` read that history back, and
  anonymous session identity is a lightweight HMAC-signed cookie (no login
  yet — `app/core/session.py`).

- **Step 7 (this step)** — the React chat UI: a streaming chat window
  (`ChatWindow`/`ChatMessage`) driven by `useChatStream`'s SSE-consuming
  hook, a citation panel that resolves `[N]` markers in the answer text to
  real source metadata (`CitationPanel`), and the audience toggle
  (`AudienceToggle`, F5 from the brief). Built on hand-implemented
  shadcn/ui-style primitives (`components/ui/*`) rather than the shadcn
  CLI, which needs network access this sandbox doesn't have — see
  `docs/DECISIONS.md`.

- **Step 8 (this step)** — the rules engine and certification wizard:
  5 YAML-backed schemes (`app/rules/data/*.yaml`, typed by `app.rules.
  schemas.SchemeRules`), a keyword-based eligibility matcher
  (`app.rules.eligibility`, explicitly an MVP heuristic), a stateless
  multi-step wizard (`app.rules.wizard`), and `GET /certification/schemes`
  / `POST /certification/wizard`.

- **Step 9 (this step)** — licence verification and gap analysis:
  `POST /verify` looks up a CM/L, CRS R-number or HUID against the seeded
  `Licence` table (`app.services.verification_service`), and
  `POST /analysis/gap-check` (`app.services.gap_analysis_service`)
  compares the rules engine's matched schemes for a product against the
  licences a user says they hold, flagging missing mandatory
  certifications.

- **Step 10 (this step)** — multilingual translation: a pluggable
  `app.translate.client` adapter (`NoOpTranslationClient` default,
  `BhashiniTranslationClient` for India's government multilingual API),
  applied to the final chat answer via an optional `target_language` field
  on `POST /chat`. Voice (ASR/TTS) is not implemented — see
  `docs/DECISIONS.md`.

- **Step 11 (this step)** — the officer dashboard: `GET /analytics/
  summary` (`app.services.analytics_service`) aggregates intent
  distribution, guardrail-violation and forced-refusal rates, latency, and
  feedback counts; a new `PATCH /conversations/{id}/messages/{id}/
  feedback` endpoint lets the chat UI actually record feedback; and
  `frontend/src/pages/OfficerDashboard.tsx` (Recharts bar chart + stat
  cards, `react-router-dom` at `/dashboard`) renders it.

- **Step 12 (this step)** — the full-pipeline evaluation harness:
  `app.eval.full_eval.run_full_eval` runs `eval/golden_set_full.jsonl`
  through the complete answer engine (not just retrieval) and reports
  intent accuracy, citation precision, forced/false-refusal rates, and
  average latency — see `docs/EVALUATION.md`.

- **Step 13 (this step)** — deployment and demo-proofing:
  `infra/docker-compose.prod.yml` (production Dockerfile stages, Nginx
  serving the built frontend), `infra/nginx/nginx.conf` (SSE-safe
  proxying — `proxy_buffering off` on the chat endpoint), and
  `app.db.seed` (idempotent demo-data seeding gated by
  `SEED_DEMO_DATA=true`).

Nothing is left unbuilt except Step 14's final documentation consolidation
pass. See `docs/RUNBOOK.md` for how to run the CLIs, the API, and the
frontend dev server (including the production compose file), and
`docs/DECISIONS.md` for what's genuinely tested here versus what needs a
live Postgres/Ollama/Infinity/hosted-API stack to verify.

## Component boundaries

- `backend/app/api` — route handlers only. No business logic (see decision
  in `DECISIONS.md`); every handler beyond Step 1's health check must call
  into `backend/app/services`.
- `backend/app/models` — SQLAlchemy 2.0 async ORM models, one module per
  bounded concept (standards, certification, documents/chunks, conversation,
  verification, audit). All imported from `app/models/__init__.py` so
  Alembic autogenerate sees the full metadata.
- `backend/app/schemas` — Pydantic v2 request/response contracts.
- `backend/app/core` — settings, logging, RFC 7807 error handling. The only
  place that reads environment variables.
- `worker/` — Celery app + tasks, importing `backend/app` directly rather
  than duplicating settings/model code.
- `ingestion/` — crawlers and parsers (Step 2+).
- `backend/app/ml` — embedding and reranker clients (Step 4+), shared by
  both ingestion (index-time embedding) and retrieval (query-time embedding)
  so the two can never drift onto different model configs.
- `backend/app/retrieval` — query understanding, sparse/dense/exact-match
  retrievers, RRF fusion, reranking orchestration, the CLI, and the baseline
  evaluation harness (Step 4+).
- `backend/app/llm` — the pluggable LLM adapter (Step 5+): one `LLMClient`
  interface, three implementations (Ollama, Anthropic, OpenAI-compatible),
  chosen by `LLM_BACKEND`/`HOSTED_LLM_PROVIDER`.
- `backend/app/answer` — the answer engine (Step 5+): prompt construction,
  citation validation, guardrail enforcement, and the streaming
  orchestration (`engine.py`) that ties retrieval + the LLM adapter
  together, plus its own CLI.
- `backend/app/api/v1/chat.py` — the chat SSE endpoint and conversation
  history endpoints (Step 6+). Route handlers only — persistence logic
  lives in `backend/app/services/conversation_service.py`.
- `backend/app/core/session.py` — the anonymous signed-cookie session
  identity (Step 6+), used by `app/api/v1/chat.py` to scope conversation
  history per browser with no login.
- `frontend/src/hooks/useChatStream.ts` — the SSE-consuming state machine
  driving the chat UI (Step 7+); `frontend/src/lib/sse.ts` does the raw SSE
  framing over `fetch`'s body stream (not `EventSource` — see
  `docs/DECISIONS.md`).
- `frontend/src/components/chat/` — `ChatWindow`, `ChatMessage`,
  `CitationPanel`, `AudienceToggle`, `ChatInput` (Step 7+).
- `frontend/src/components/ui/` — hand-implemented shadcn/ui-style
  primitives (`Button`, `Textarea`, `Badge`, `Card`, Step 7+), following
  shadcn/ui's own API so a real CLI-generated version can replace them
  later with no call-site changes.
- `backend/app/rules/` — the YAML-backed rules engine (Step 8+):
  `schemas.py` (typed shape), `loader.py` (cached YAML loading),
  `eligibility.py` (keyword-based scheme matching), `wizard.py` (the
  stateless certification wizard state machine), `data/*.yaml` (the 5
  scheme files themselves).
- `backend/app/services/verification_service.py` /
  `gap_analysis_service.py` — licence lookup and mandatory-scheme gap
  checking (Step 9+), called by `app/api/v1/verify.py` and
  `app/api/v1/analysis.py`.
- `backend/app/translate/` — the pluggable translation adapter (Step 10+),
  same interface/factory pattern as `app.llm.client`.
- `backend/app/services/analytics_service.py` — officer-dashboard
  aggregation queries (Step 11+), called by `app/api/v1/analytics.py`;
  `frontend/src/pages/OfficerDashboard.tsx` renders it.
- `backend/app/eval/` — the Step 12 full-pipeline evaluation harness
  (`golden_set.py`, `full_eval.py`, `cli.py`), distinct from
  `app.retrieval.baseline_eval` (Step 4, retrieval-only, no LLM).
- `backend/app/db/seed.py` — idempotent demo-data seeding (Step 13),
  gated by `SEED_DEMO_DATA`.
- `infra/nginx/nginx.conf` + `infra/docker-compose.prod.yml` — the
  production stack (Step 13): built frontend served by Nginx, SSE-safe
  proxying to the backend.
- `eval/` — evaluation harness data: `golden_set_sample.jsonl` (Step 4,
  retrieval-only baseline) and `golden_set_full.jsonl` (Step 12,
  full-pipeline harness — see `docs/EVALUATION.md` for why this is ~25
  questions rather than the brief's 150+).
- `frontend/` — React 18 + Vite + TypeScript strict + Tailwind + TanStack
  Query + `react-router-dom` (Step 11+, `/` and `/dashboard`).
  `src/types/api.ts` mirrors the backend schemas.

## Three architectural decisions (see DECISIONS.md for the full rationale)

1. Hybrid retrieval (BM25 + dense, fused, then reranked) — not pure vector
   search — because exact identifiers (IS numbers, clause references, CM/L
   numbers) need exact-match behaviour that dense embeddings alone blur.
2. A deterministic YAML rules engine sits beside the LLM for fees,
   timelines, validity periods and eligibility. The model may quote these
   values; it may never author them.
3. A pluggable model adapter with two backends — hosted API and local
   Ollama — switchable by environment variable and per-request, to
   demonstrate a fully offline, data-sovereign deployment mode.
