# Design decisions

Decisions the brief specified exactly, plus decisions made while building
that the brief left open (each flagged at the point they were made, per the
"how to proceed" instructions).

## Specified in the brief (non-negotiable)

1. **Hybrid retrieval, not pure vector search.** Queries are full of exact
   tokens ("IS 15111", "Clause 4.2.1", "CM/L 1234567"). Dense embeddings
   blur those; BM25 (Postgres full-text search) matches them exactly. Fuse
   both with reciprocal rank fusion (k=60), then rerank with a cross-encoder
   (bge-reranker-v2-m3). The Postgres text-search configuration is tuned so
   alphanumeric identifiers survive tokenisation (built in Step 3).
2. **A deterministic rules engine beside the LLM.** Fees, validity periods,
   timelines and scheme eligibility live in YAML lookup tables
   (`app.models.certification.Scheme.rules_yaml_path`) that the model may
   quote verbatim but never author. This is the mechanism that lets the
   system honestly claim it does not hallucinate compliance requirements.
3. **A model adapter with an on-premise mode.** One interface
   (`LLM_BACKEND=ollama|hosted`), two backends, switchable by environment
   variable and per-request. The system must run fully offline: local
   Ollama, local embeddings (BGE-M3 via Ollama), local Postgres.

## Made during Step 1 (not specified — flagged per instructions)

- **Migrations run on the async engine via `run_sync`**, not a second sync
  driver (psycopg2), since asyncpg is already a runtime dependency and this
  avoids installing/maintaining a driver used nowhere else.
- **Shared type contract is hand-maintained, not codegen'd.** Backend
  Pydantic schemas and `frontend/src/types/api.ts` are kept in sync by hand
  for now; FastAPI's generated `/openapi.json` is the source of truth to
  check drift against. Revisit with `openapi-typescript` codegen once the
  API surface stabilizes past Step 6 — hand-maintenance won't scale once
  `/chat`, `/standards/*`, `/certification/*` etc. are all real.
- **Unit-test database is in-memory SQLite**, not a containerized Postgres,
  for the Step 1 health-check tests (fast, no service dependency in CI).
  Any test touching pgvector, Postgres full-text search, or Postgres-only
  types must use a real Postgres test database instead — introduced when
  Step 3 (ingestion) needs it.
- **Worker image shares the backend's `app` package** by copying it into
  the worker image and setting `PYTHONPATH`, rather than packaging `app` as
  an installable library. Simpler for a hackathon timeline; revisit if the
  two services' dependencies diverge enough to cause version conflicts.
- **Dev Docker Compose only** in Step 1 (`infra/docker-compose.yml`); the
  production compose file with Nginx/TLS/SSE-safe proxying is deferred to
  Step 13 as the brief's own step ordering implies.

## Made during Step 2

- **Crawler seed lists point at real, named BIS/services.bis.gov.in URLs**,
  but this sandbox has no live network access to browse those pages and
  hand-validate markup (`curl`/direct HTTP to bis.gov.in is blocked by the
  sandbox's own egress allowlist — confirmed while building this step).
  `ingestion/core/html.py`'s parser is therefore deliberately generic
  (title tag + a regex for IS-number-shaped tokens) rather than site-specific
  CSS selectors, and is tested against representative HTML fixtures, not a
  live fetch. Validate and tighten selectors once this runs on a machine
  with real network access (the crawlers themselves — rate limiting,
  robots.txt, retry, blob storage, provenance — are fully real and unit
  tested; only the parsing precision is a placeholder for real markup).
- **`ingestion/` is not yet in the CI mypy-strict gate** (only `ruff` +
  `pytest`). It imports `app.*` directly and mypy needs `backend/app`
  marked `py.typed` (added) plus per-module handling for Celery's untyped
  task decorator to check cleanly across the package boundary; deferred
  rather than papering over it with blanket `type: ignore`. Revisit when
  Step 3 adds enough ingestion code to justify the CI plumbing.
- **QCO crawler seeds the BIS index pages, not a single fixed PDF list.**
  QCOs are published as ministry notifications referenced from BIS's
  compulsory-registration pages rather than one stable URL; QCO documents
  are chunked for retrieval like any other source as of Step 3, but the
  further step of *normalizing* them into the `standards` table's
  structured columns (`is_qco_mandatory`, `applicable_schemes`) is still
  open, deferred to whichever later step first needs that structured form
  rather than retrievable chunk text.

## Made during Step 3

- **Token counting is a whitespace-word-count approximation**
  (`ingestion/chunking/tokens.py`), not a real BPE tokenizer. `tiktoken`
  normally fetches its vocab file from a CDN on first use, which is a bad
  fit for an offline-capable, network-restricted deployment target
  (confirmed in Step 2 that this sandbox's outbound network is itself
  restricted). The 400-800 *token* target is converted to a word-count
  target using an empirical ~1.3 tokens-per-word ratio for English
  technical prose. Revisit with the actual BGE-M3 tokenizer (transformers'
  `AutoTokenizer`, loaded from a model already being pulled locally anyway)
  if chunk-size precision becomes a problem in evaluation (Step 12).
- **PDF parsing extracts page text only — no table detection.** The HTML
  parser converts tables to markdown properly; PDF table extraction needs
  real layout analysis (e.g. `pdfplumber`), which is a meaningfully bigger
  dependency and failure surface to validate without a real corpus of QCO
  PDFs to test against yet. A PDF's tabular data currently lands as plain
  paragraph text within its page block. Revisit once Step 2's QCO crawler
  has pulled real files to test against.
- **Full-text search uses a custom `manak_search` configuration copied from
  `pg_catalog.simple`** (migration `0002_search_config.py`), not `english`
  — `simple` performs no stemming, which matters more here than English
  normalization does, given how much of the corpus is exact identifiers
  and technical terms. This does not make a compound token like "CM/L
  1234567" survive as one search token (Postgres's parser splits on
  punctuation before any dictionary sees it) — exact identifier matching
  is Step 4's query router's job (a dedicated regex/lookup path), not
  full-text search's.
- **`PortableJSON` type added to `app/db/base.py`**
  (`JSON().with_variant(JSONB, "postgresql")`), replacing raw
  `postgresql.JSONB` on the three JSONB columns (`Chunk.extra_metadata`,
  `Message.citations`/`retrieval_debug`, `AuditLogEntry.extra_metadata`).
  Production behavior on Postgres is unchanged (still JSONB); this is what
  lets `ingestion/tests/test_pipeline.py` build a real `Chunk` table
  against in-memory SQLite instead of requiring a live Postgres for a unit
  test — SQLite's compiler otherwise rejects `JSONB` outright.
- **Chunking treats every parsed block as atomic** (never splits a
  paragraph, even an unusually long one) rather than only guaranteeing
  atomicity for tables and numbered clauses as the brief's minimum
  requirement states. Simpler to implement correctly and matches the
  brief's spirit; the trade-off is a pathologically long single paragraph
  becomes an oversized chunk rather than being split at a sentence
  boundary. Not expected to matter for BIS/QCO source material, which is
  already clause-segmented.

## Made during Step 4

- **Embedding client moved to `app/ml/embedding_client.py`**, shared as the
  single implementation for both index-time embedding (ingestion pipeline,
  Step 3) and query-time embedding (dense retrieval, Step 4).
  `ingestion/embeddings/client.py` is now a thin re-export shim. This was a
  refactor, not new behavior — its purpose is to make it structurally
  impossible for the corpus and a query to ever be embedded by different
  model configs, which would silently degrade dense retrieval with no error.
- **Reranking is served by Infinity (`michaelfeil/infinity`), not Ollama.**
  Ollama serves the embedding model (BGE-M3) but has no first-class
  cross-encoder/rerank serving mode; Infinity exposes a Cohere-compatible
  `/rerank` HTTP endpoint and has a documented, actively maintained
  container for `bge-reranker-v2-m3`. Added as its own `reranker` service in
  `infra/docker-compose.yml` rather than bolting reranking onto the Ollama
  container.
- **Exact-match routing only covers `IS_NUMBER` and `CLAUSE_REFERENCE`
  against the `Chunk` table in Step 4.** `CML_NUMBER`, `CRS_R_NUMBER`, and
  `HUID` are real identifier types extracted by `query_understanding.py`
  (used today to route a query to `Intent.VERIFICATION`), but there is no
  `Licence`-table exact-match retriever yet — that table's real lookup path
  belongs to Step 9 (verification + gap analysis), so a verification-intent
  query in Step 4/5 will fall through to hybrid search over chunk text
  rather than a licence-registry hit. `has_chunk_routable_identifier()`
  documents this split explicitly at the point a caller would otherwise
  assume all five identifier types are chunk-routable.
- **Intent classification is still the Step-3-flagged heuristic** (keyword
  matching, not a trained/LLM classifier) — worth restating here because
  Step 4 is the first place it's load-bearing (routing exact-match vs hybrid
  search), not just descriptive metadata. Two keyword-overlap bugs were
  caught by the test suite while building this step: a bare `"is "`
  substring in the domain-keyword gate matched ordinary English ("what **is
  the** weather"), and `"fake"`/`"genuine"` appearing in both the
  verification and consumer-safety keyword lists made word order in the
  keyword lists (not the query) decide the outcome. Fixed by dropping the
  `"is "` keyword (an actual `IS 1234` mention is already caught by
  identifier extraction, making the keyword redundant and unsafe) and by
  checking consumer-safety keywords before verification keywords when no
  explicit verification identifier (CM/L, R-number, HUID) is present in the
  query. Step 5's prompt-based intent handling should treat this as a first
  pass, not a finished classifier.
- **No real baseline recall numbers can be produced in this sandbox.**
  `app/retrieval/baseline_eval.py` and `app/retrieval/cli.py baseline` are
  real, tested code, but computing actual recall@k/MRR needs a live Postgres
  with crawled+chunked+embedded content plus running Ollama/Infinity
  services — none of which exist in this cloud workspace (no Docker daemon,
  no outbound access to bis.gov.in). What's delivered is the tooling and a
  10-question starter golden set (`eval/golden_set_sample.jsonl`, explicitly
  documented as a sample, not the Step-12 150+ question set) — real numbers
  need to be generated by running `docker compose exec backend python -m
  app.retrieval.cli baseline` on your machine after Step 2's crawlers have
  populated real content.

## Made during Step 5

- **`HOSTED_LLM_PROVIDER=openai` means "speaks the OpenAI chat/completions
  wire format", not literally OpenAI's own API.** The user's hosted-LLM
  choice for this build is NVIDIA NIM's free-tier API
  (`https://integrate.api.nvidia.com/v1`), which is OpenAI-compatible —
  rather than add a one-off `nvidia` provider literal, `OpenAICompatibleLLMClient`
  is written generically against the wire format and pointed at NVIDIA's
  endpoint via `HOSTED_LLM_BASE_URL` + `HOSTED_LLM_MODEL` in `.env`. The same
  class covers OpenAI itself, Azure OpenAI, Groq, and Together with no code
  change, just different env values. `AnthropicLLMClient` (native Messages
  API) is also implemented since `HOSTED_LLM_PROVIDER` already had
  `anthropic` as an option from Step 1's scaffold — both exist, selected by
  one setting.
- **Streaming forwards raw tokens live, but citation validation and
  guardrail enforcement only run once on the complete answer text.** Both
  checks need to see the whole answer (a citation marker or a verbatim
  30-word run can straddle a chunk boundary the LLM API happens to stream
  across), so `stream_answer` yields `TokenEvent`s as they arrive for
  perceived latency, then a single terminal `FinalEvent` carrying the
  guardrail-redacted text and validated citations — not a citation-checked
  version of every partial chunk. The frontend (Step 7) should treat
  streamed tokens as provisional and the final event's text as authoritative
  (they can differ if a guardrail redaction fires).
- **The verbatim-redistribution guardrail actively rewrites the answer**,
  not just logs a warning — replacing any run of more than 25 words shared
  verbatim with a retrieved chunk with a placeholder pointing back at the
  cited clause. This is the one guardrail with teeth rather than an
  advisory flag, because "never redistribute full IS standard text" is the
  brief's explicit hard legal constraint, and a free-tier/smaller hosted
  model is exactly the kind of model likely to just paste a chunk verbatim
  despite the prompt telling it not to. Detection uses `difflib.SequenceMatcher`
  over word lists — an O(n·m) LCS-family diff, fine at chunk/answer scale
  (dozens to low hundreds of words), not chosen for large-document diffing.
- **A query with zero retrieved chunks never reaches the LLM at all** —
  `requires_forced_refusal` short-circuits to a fixed refusal message. This
  is stricter than "let the model say it doesn't know": it removes the
  failure mode entirely rather than trusting prompt instructions to prevent
  an ungrounded, uncitable answer, consistent with the citation-enforcement
  spirit of the brief's Step 5 scope.
- **Uncited claims are flagged, not fabricated a citation for.** The
  citation validator resolves markers the model actually wrote and reports
  invalid ones (a hallucinated source number); it deliberately does not try
  to guess-insert a citation onto an uncited sentence, since a wrong guessed
  citation would be worse than an honestly uncited one. `has_any_citation`
  is exposed for a caller (Step 6's API, Step 12's eval harness) that wants
  to flag or penalize citation-free answers.
- **No conversation history / multi-turn context yet.** `stream_answer`
  takes one query in isolation — `Conversation`/`Message` persistence and
  multi-turn prompt assembly belong to Step 6 (API + persistence), which is
  the step that actually has a `Conversation` to read prior turns from.

## Made during Step 6

- **The `/chat` SSE endpoint opens its own database session inside the
  streaming generator, instead of using `Depends(get_db)`.** This is a real
  FastAPI/Starlette gotcha, not a style preference: a `yield`-based
  dependency is torn down as soon as the endpoint function *returns* the
  `StreamingResponse` object, which happens before the response body has
  actually been streamed to the client — a `Depends(get_db)` session would
  already be closed by the time the generator runs and tries to persist the
  assistant's message. `app/api/v1/chat.py`'s `event_stream()` opens
  `AsyncSessionLocal()` itself and commits/rolls back inside the same
  generator instead. The two read-only endpoints (`GET /conversations`,
  `GET /conversations/{id}/messages`) are ordinary non-streaming responses,
  so they use `Depends(get_db)` normally.
- **Anonymous session identity is a lightweight custom HMAC-signed cookie
  (`app/core/session.py`), not `itsdangerous` or a JWT.** The only thing
  this cookie needs to do is let a browser prove it owns a given
  `session_id` across requests, with no claims beyond that id — a full
  JWT or an added dependency would be solving a bigger problem than the one
  that exists here. `hmac.compare_digest` guards the signature check against
  timing attacks; rotating `APP_SECRET_KEY` invalidates all outstanding
  session cookies, forcing a fresh anonymous session (acceptable: there is
  no login yet, so nothing is actually lost besides local chat history).
- **Conversation persistence has no login yet — history is scoped purely
  to the signed session cookie.** `Conversation.account_id` exists in the
  Step 1 schema for future authenticated use but nothing in Step 6 sets or
  reads it. A cleared cookie or a different browser means no access to
  prior history; this matches the brief's scope for Step 6 (which says
  "persistence," not "accounts") and keeps auth (Step 6+ or later, if
  added) a separable concern layered on top rather than tangled into the
  chat endpoint itself.
- **SSE has four event types, not one.** `conversation` fires immediately
  (before any LLM output) so the frontend (Step 7) can start showing a
  conversation id right away for URL/history purposes; `token` events
  stream provisional text; exactly one `final` event carries the
  guardrail-redacted authoritative text plus persisted-message metadata;
  `error` replaces `final` if anything fails mid-stream, since an HTTP
  error status is no longer available once the 200 response has already
  started streaming. The frontend should render `token` text live but
  replace it with `final`'s text once it arrives (they can differ if a
  guardrail redaction fired).
- **404, not 403, for a conversation id that belongs to someone else's
  session.** `get_or_create_conversation`/`get_conversation_for_session`
  raise the same `NotFoundError` whether the id doesn't exist at all or
  belongs to a different session — distinguishing the two would leak
  whether a given conversation id exists to a caller who doesn't own it.
- **The chat endpoint's own DB-session behavior isn't covered by the same
  in-memory-SQLite trick used elsewhere**, because it bypasses
  `Depends(get_db)` on purpose (see above) — `tests/api/test_chat.py`
  instead monkeypatches the module-level `AsyncSessionLocal` name inside
  `app.api.v1.chat` to a SQLite session maker sharing one connection
  (`StaticPool`-backed, since SQLAlchemy pools a single `:memory:`
  connection per engine), and monkeypatches `stream_answer` itself to a
  fake generator — the streaming/citation/guardrail logic it exercises is
  already covered by Step 5's `tests/answer/test_engine.py`; this layer's
  tests are about the API/persistence wiring around it (cookie issuance,
  SSE event framing and ordering, both turns persisted, session-scoped
  history, session isolation).

## Made during Step 7

- **shadcn/ui components are hand-built, not scaffolded via the shadcn
  CLI.** `npx shadcn@latest init` makes an outbound call to
  `ui.shadcn.com/init` for its registry/telemetry before it writes a single
  file, and that host is blocked by this sandbox's network egress
  (confirmed while building this step — the same class of restriction as
  `bis.gov.in` in Step 2). Rather than block on it,
  `frontend/src/components/ui/*` hand-implements the handful of primitives
  actually needed (`Button`, `Textarea`, `Badge`, `Card`) following
  shadcn/ui's own API and Tailwind/CVA variant conventions
  (`class-variance-authority` + `cn()` via `clsx`/`tailwind-merge`, both
  already shadcn/ui's own choices) without the Radix `Slot` dependency. A
  real `npx shadcn add button` run on a machine with normal network access
  should be able to replace these files with the generated equivalents with
  no call-site changes, since the class names and props match.
- **SSE is consumed via a hand-rolled `parseSSEStream` over `fetch`'s raw
  body stream, not the browser's `EventSource`.** `EventSource` cannot send
  a POST body (the chat message) or read a non-2xx JSON error body, and
  `POST /api/v1/chat` needs both (see `app.api.v1.chat`'s docstring for its
  SSE event contract). `parseSSEStream` (`frontend/src/lib/sse.ts`)
  implements exactly the framing the backend actually writes — blocks
  separated by a blank line, `event:`/`data:` lines — not the full SSE spec
  (no retry/id fields, no reconnection), since this isn't a general-purpose
  client hitting arbitrary SSE servers.
- **A message's client-generated id never changes to the server's
  persisted message id.** The natural instinct is to swap in the real
  `message_id` once the `final` SSE event arrives, but the UI
  (`App.tsx`/`useChatStream`) tracks "the currently active message" for the
  citation panel by that id from the moment the (empty, streaming) bubble
  is created — swapping the id out on `final` would silently break that
  tracking at exactly the moment citations become available. The server id
  is simply not surfaced client-side yet; it becomes relevant once history
  needs to be reconciled against `GET /conversations/{id}/messages` across
  a page reload, which Step 7 doesn't attempt (see below).
- **No page-reload conversation restore yet.** `GET /conversations` and
  `GET /conversations/{id}/messages` exist (Step 6) and are wired into
  `frontend/src/lib/api.ts`, but the chat UI always starts a fresh, empty
  conversation on load rather than restoring the last one from the session
  cookie. Wiring that up is a small addition (a `useQuery` for the most
  recent conversation's messages, hydrating `useChatStream`'s initial
  state) deferred to keep this step's scope to "the chat UI + citation
  panel" as scoped, not full session-persistence UX.
- **The citation panel auto-follows the newest assistant message**, and a
  manual citation-marker click on an older message overrides that only
  until the next question is sent. An explicit "pin" affordance (so a user
  could compare citations across two answers side by side) was considered
  and left out as unnecessary complexity for a first version.
- **Desktop-only citation panel layout below the `md` breakpoint** — on a
  narrow viewport the panel is hidden entirely (`hidden md:block`) rather
  than collapsed into a drawer/sheet, since a drawer component was more UI
  surface than this step's scope justified. Citation markers are still
  clickable and functional on mobile; there's simply nowhere for the result
  to render yet. A follow-up (mobile drawer, or inline expansion under the
  message) is worth doing before this ships to real users on phones.

## Made during Step 8

- **The rules engine is YAML files loaded at process start (cached), not
  database rows.** `app.rules.loader` reads `app/rules/data/*.yaml` into
  `SchemeRules` Pydantic models via an `lru_cache`d loader — decision #2
  ("fees, timelines, validity periods and scheme eligibility live in
  YAML... the model may quote these values but never author them") is
  implemented literally: these files are reviewable in a PR diff, never
  written to by the application, and completely independent of
  Postgres/the LLM, so the loader/eligibility/wizard modules are unit
  tested with zero live dependencies.
- **Only 5 schemes are modeled** (ISI Scheme I, CRS, FMCS, Hallmarking, Eco
  Mark) — enough to cover the brief's example scenarios and demonstrate the
  general/foreign-manufacturer/mandatory-registration/hallmarking shape of
  BIS's actual scheme landscape, not an exhaustive list. Every scheme's
  `source_note` field defaults to an explicit "illustrative placeholder
  values" disclaimer, surfaced in both `GET /certification/schemes` and the
  wizard's final result — real BIS fees/timelines change and must be
  confirmed directly with BIS, and nothing here should read as an
  authoritative quote.
- **Scheme matching is keyword-substring, not a real product
  classification.** `app.rules.eligibility.match_schemes` is explicitly
  documented as an MVP heuristic — a production system needs a real
  classifier (HSN codes / QCO schedule lookup) reviewed by a BIS subject
  matter expert.
- **The certification wizard is stateless.** `app.rules.wizard` takes the
  full answers dict on every call and computes the next question or final
  result as a pure function — no server-side wizard session, no new
  database table. This avoids "wizard session expired/mismatched with a
  different browser tab" bugs entirely, at the cost of the client needing
  to resend all prior answers each step (a small JSON payload, not a
  meaningful cost here).

## Made during Step 9

- **Licence verification queries our own seeded `licences` table, not a
  live BIS registry.** There is no public real-time API for CM/L, CRS
  R-number or HUID lookup this build has access to; `Licence.is_seed_data`
  makes the demo-data provenance explicit in every `/verify` response, and
  the response text explicitly tells the user this isn't a live BIS query.
- **Gap analysis maps `LicenceType` to scheme code with a hardcoded 1:1
  dict**, not a real many-to-many scheme/licence-type mapping table — fine
  for a 5-scheme demo dataset where each scheme happens to correspond to
  exactly one licence type, but called out explicitly as something a
  production system needs to model properly (a product can need more than
  one certification, and a licence type doesn't uniquely determine a
  scheme in general).

## Made during Step 10

- **Translation is a pluggable adapter (`app.translate.client`), same
  shape as the Step 5 LLM adapter** — `NoOpTranslationClient` is the
  default (`TRANSLATION_BACKEND=none`), so nothing about the fully offline
  deployment mode (decision #3) needs to change to support this step;
  Bhashini (India's own government multilingual API) is the one real
  backend, gated behind `BHASHINI_API_KEY`/`BHASHINI_USER_ID` that must be
  requested from the user, never hardcoded.
- **Translation applies only to the final answer text, never to streamed
  token deltas, and never touches retrieval/citations.** Translating a
  growing token prefix live would mean re-translating on every delta (or
  blocking streaming until the full answer exists, which defeats Step 5's
  point); and citation `[N]` markers need to be checked against the
  complete, stable text. The practical effect: with translation on, the
  frontend streams the English answer live and then gets a `translated_
  text` field on the `final` SSE event a beat later. This is a real UX
  rough edge (a brief flash of English before the translation lands) noted
  here rather than hidden — a v2 could translate progressively across
  sentence boundaries instead of once at the end.
- **Voice (ASR/TTS) is not implemented — this step covers text
  translation only.** The brief groups "multilingual/voice" as one step;
  given the time budget, the interface-level piece (translating the
  already-cited, already-guardrailed text) was prioritized because it
  reuses the existing SSE contract with one new optional field, while
  ASR/TTS would need new audio upload/playback plumbing on both ends. This
  is an explicit scope cut, not an oversight.

## Made during Step 11

- **No auth/role gate on `/api/v1/analytics/summary` or the `/dashboard`
  frontend route.** There is no login system anywhere in this build (Step
  6's session cookie is anonymous-only); a production deployment must put
  an authenticated "officer" role in front of this endpoint before
  exposing it publicly. Flagged here so it's not mistaken for an oversight
  discovered later.
- **Analytics aggregation happens in Python over fetched rows, not
  JSON-operator SQL.** `Message.retrieval_debug`/`citations` are JSONB;
  writing SQL that extracts fields from them differs between SQLite (used
  in tests) and Postgres (production), so `app.services.analytics_service`
  fetches assistant messages and aggregates with a `Counter` instead. Fine
  at hackathon-demo scale; a real deployment would replace this with a
  materialized `message_stats` table refreshed by a scheduled Celery task
  so summary reads stay O(1) as the table grows, rather than O(messages).
- **A feedback endpoint (`PATCH /conversations/{id}/messages/{id}/
  feedback`) was added in this step**, not earlier — `Message.
  feedback_rating`/`feedback_comment` columns existed since Step 6's
  schema but had no way to be set until the dashboard needed real feedback
  data to aggregate.

## Made during Step 12

- **The golden set is ~25 hand-curated questions, not the brief's
  150+.** Building a genuinely 150+-question set needs subject-matter-
  expert review of each expected answer against real BIS rules at a scale
  this build's time budget doesn't cover; what ships
  (`eval/golden_set_full.jsonl`) is deliberately chosen to cover every
  `Intent` value across both audiences plus refusal cases instead, and the
  harness (`app.eval.full_eval.run_full_eval`) needs no code changes to
  run against a larger set later — see `docs/EVALUATION.md`.
- **"Groundedness" is measured as "no fabricated `[N]` marker", not
  factual correctness.** A real accuracy check needs a human comparing the
  answer to a primary BIS source; that's out of scope for an automated
  harness and is stated plainly in the docs rather than implied by the
  metric's name.
- **No CI regression gate wired up.** Running the full harness needs a
  live LLM backend, which isn't something CI has credentials/budget for in
  this build. A nightly scheduled run against a fixed model/prompt version
  with an alert on regression is the natural next step, not implemented.

## Made during Step 13

- **`infra/docker-compose.prod.yml` is a separate file from the Step 1 dev
  compose, not a profile/override.** The two stacks differ enough (build
  targets, no bind mounts, Nginx instead of the Vite dev server, a one-shot
  seed service) that a single file with overrides would be harder to read
  than two complete files — consistent with `infra/nginx/README.md`'s
  original plan.
- **`proxy_buffering off` (plus `gzip off` and `chunked_transfer_encoding
  on`) on the SSE chat location specifically** — Nginx buffers upstream
  responses by default regardless of the backend's own
  `X-Accel-Buffering: no` header (set in `app/api/v1/chat.py` since Step
  6); that header only has an effect once Nginx's own buffering is also
  disabled at the proxy config level. Every other `/api/` route keeps
  normal buffered proxying since they return one JSON body, not a stream.
- **Demo seeding (`app.db.seed`) is a stand-in for the Step 2/3 ingestion
  pipeline, not a replacement for it.** It inserts a handful of
  `Standard`/`Scheme`/`Licence` rows directly (gated by
  `SEED_DEMO_DATA=true`, idempotent by natural key) so a fresh deployment
  with no crawl/ingest run yet has something to demo immediately; real
  content still needs the crawlers and ingestion pipeline to run.
  `Licence` rows are flagged `is_seed_data=True`; `Standard`/`Scheme` don't
  carry that column since they're normally populated by ingestion, not
  hand-seeded, in a real deployment.
- **Offline mode is `LLM_BACKEND=ollama` end to end** — the production
  compose file's default. Combined with `TRANSLATION_BACKEND=none` (also
  the default, Step 10) and no calls to any external API from the backend
  in that configuration, this is what "fully offline, data-sovereign
  deployment" (decision #3) actually means operationally: no outbound
  network calls beyond pulling Docker images and Ollama models once at
  first boot.
