# Runbook

## Running the stack (Step 1 scope)

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

First boot will be slow: Ollama pulls `llama3.1:8b` and `bge-m3` (several GB
total) inside its container. Subsequent boots reuse the `ollama_data`
volume and are fast.

Once it's up:

- Backend health: http://localhost:8000/api/v1/health
- API docs (Swagger UI): http://localhost:8000/docs
- Frontend: http://localhost:5173

`docker compose up` runs `alembic upgrade head` automatically as the
backend container's start command, so the schema is always current on boot.

## Windows prerequisites

This stack requires **Docker Desktop for Windows** with the WSL2 backend
(the default on a current install). If it isn't installed yet:

1. Install WSL2: open PowerShell as Administrator and run `wsl --install`,
   then reboot if prompted.
2. Install Docker Desktop from docker.com, and during setup confirm "Use
   WSL 2 based engine" is checked (Settings → General).
3. Start Docker Desktop and wait for it to report "Engine running" before
   running `docker compose up`.
4. Verify from a terminal: `docker --version` and `docker compose version`
   should both print a version, not "command not found".

Everything else (Postgres, Redis, Ollama, the Python/Node toolchains) runs
inside containers — nothing else needs installing on the host for Step 1.

## Troubleshooting (Step 1)

**`docker compose up` fails with a port conflict (5432, 6379, 8000, 5173,
or 11434 already in use).** Something else on the machine is bound to that
port — commonly a locally installed Postgres/Redis, or another project's
stack still running. Stop it, or change the left-hand side of the port
mapping in `infra/docker-compose.yml` (e.g. `"5433:5432"`) and adjust
`POSTGRES_PORT` in `.env` to match.

**Backend container loops restarting on `alembic upgrade head`.** Almost
always means Postgres wasn't ready yet despite the healthcheck, or the
`vector` extension failed to create. Run
`docker compose -f infra/docker-compose.yml exec postgres psql -U manak -d manak_sahayak -c "SELECT * FROM pg_extension;"`
and confirm `vector` and `pg_trgm` are listed; the `pgvector/pgvector:pg16`
image ships the extension binary, so a missing entry means the migration
didn't run — check `docker compose logs backend` for the actual error.

**Ollama pulls hang or fail.** Check outbound network access from the
container (`docker compose exec ollama ollama list` should show the two
models once pulled). On a fully offline machine, pre-pull models on a
connected machine, then copy the `ollama_data` volume across — the full
offline-mode script is built in Step 13.

**Frontend shows "Could not reach the backend" on the health card.** Check
`docker compose logs backend` for a stack trace. If the backend itself is
healthy, check the Vite proxy target
(`VITE_API_PROXY_TARGET`, set to `http://backend:8000` inside Docker) isn't
being overridden by a stale `.env` value meant for host-network development.

**mypy/ruff/eslint fail in CI but pass locally.** Usually a dependency
version drift between your local venv/node_modules and the pinned versions
in `backend/requirements-dev.txt` / `frontend/package.json`. Reinstall from
those files rather than whatever's already on your machine.

The "five failures most likely on demo day" section (Wi-Fi loss, LLM
backend switch live, SSE buffering, cold-start latency, seed-data reset) is
written in Step 13 once there's an actual demo flow to fail.

## Running crawlers (Step 2)

```bash
docker compose -f infra/docker-compose.yml exec worker python -m ingestion.cli crawl bis_connect
docker compose -f infra/docker-compose.yml exec worker python -m ingestion.cli crawl all
docker compose -f infra/docker-compose.yml exec worker python -m ingestion.cli process all
docker compose -f infra/docker-compose.yml exec worker python -m ingestion.cli process --source bis_connect
```

`process` requires Ollama to have pulled the embedding model already
(`docker compose exec ollama ollama list` should show `bge-m3`) — the
`ollama` service's entrypoint pulls it automatically on first boot, but a
slow/offline first boot can leave it missing; re-run
`docker compose exec ollama ollama pull bge-m3` if `process` fails with a
connection or 404 error against `/api/embeddings`.

Each run logs a JSON summary (`fetched`, `created`, `unchanged`, `skipped`,
`failed`) per source. `unchanged` climbing on every run against the same
source is expected and correct — that's the idempotency guarantee, not a
bug. `skipped` means robots.txt disallowed a seed URL; `failed` means an
HTTP error or exhausted retries — check `docker compose logs worker` for
the specific URL and status.

**"No module named 'ingestion'" or "No module named 'app'" running the CLI
locally (outside Docker).** Run it as `python -m ingestion.cli` from the
**repo root**, not from inside `ingestion/` — the module does its own
`sys.path` setup relative to its own file location, but only `-m` invocation
resolves the package name correctly. Also make sure
`backend/requirements-dev.txt` and `ingestion/requirements.txt` are both
installed in whatever venv you're using.

**A crawl reports `failed` for every seed URL.** Almost always the sandbox
or machine you're running from has no outbound network access to
`bis.gov.in` / `services.bis.gov.in` — check with a plain
`curl -I https://www.bis.gov.in/`. This is expected inside network-restricted
CI or sandboxed environments; it is not expected on your own laptop with
normal internet access.

**Blob store fills up disk.** Raw responses accumulate in
`BLOB_STORE_PATH` (`/data/blobs` in containers, the `blob_data` Docker
volume) indefinitely — nothing currently prunes old revisions. Fine for a
hackathon-scale crawl; if it becomes a problem, `docker volume rm
manak-sahayak_blob_data` resets it (you'll need to re-crawl).

## Running the retrieval core (Step 4)

Needs Steps 1-3 done first (stack up, at least one source crawled and
processed), plus the `reranker` service (Infinity) up and warm — it's in
`infra/docker-compose.yml` alongside the rest of the stack, but the first
request after a cold start downloads the `bge-reranker-v2-m3` model, so the
first query can take noticeably longer than later ones.

```bash
docker compose -f infra/docker-compose.yml exec backend python -m app.retrieval.cli query \
    "which standard covers LED drivers?"
docker compose -f infra/docker-compose.yml exec backend python -m app.retrieval.cli query \
    "IS 15111 clause 4.2" --no-rerank
docker compose -f infra/docker-compose.yml exec backend python -m app.retrieval.cli baseline
docker compose -f infra/docker-compose.yml exec backend python -m app.retrieval.cli baseline \
    --golden-set eval/golden_set_sample.jsonl --no-rerank
```

`query` prints the ranked chunks (document title, IS number, clause,
fused/rerank scores) for one question — use `--no-rerank` to see fused
candidates before the cross-encoder pass, e.g. while debugging whether a
bad answer is a retrieval problem or a reranking problem. `baseline` runs
every question in a golden-set JSONL file (`eval/golden_set_sample.jsonl`
ships with 10 sample questions — see `eval/README.md`; this is not the
Step-12 150+ question set) and prints recall@k and MRR, with and without
reranking, so you can see whether the reranker is actually earning its
latency cost on your corpus.

**`baseline`/`query` fail connecting to the reranker.** Check
`docker compose logs reranker` — a cold-start model download can take a
few minutes on first boot. `RERANKER_BASE_URL` in `.env` must point at the
`reranker` service's Docker DNS name (`http://reranker:7997` by default),
not `localhost`, when running from inside the `backend` container.

**Recall numbers look bad or empty.** This almost always means the corpus
is thin — recall@k against a golden set is only meaningful once enough of
the relevant sources have actually been crawled and processed (Steps 2-3).
A golden question whose expected `IS` number was never crawled will always
miss, correctly reflecting a *coverage* gap rather than a retrieval bug.

## Running the answer engine (Step 5)

Needs everything Step 4 needs, plus an LLM backend configured in `.env`:

```bash
# Offline path — no API key, no external network call at all:
LLM_BACKEND=ollama

# Hosted path — e.g. NVIDIA NIM's free-tier API (OpenAI-compatible):
LLM_BACKEND=hosted
HOSTED_LLM_PROVIDER=openai
HOSTED_LLM_BASE_URL=https://integrate.api.nvidia.com/v1
HOSTED_LLM_MODEL=meta/llama-3.1-70b-instruct
HOSTED_LLM_API_KEY=<your NVIDIA NIM API key>
```

Get a free NVIDIA NIM API key at https://build.nvidia.com — sign in, open
any model page, and generate an API key; it starts with `nvapi-`. Restart
the `backend` container after editing `.env` so the new settings load.

```bash
docker compose -f infra/docker-compose.yml exec backend python -m app.answer.cli ask \
    "which standard covers LED drivers?"
docker compose -f infra/docker-compose.yml exec backend python -m app.answer.cli ask \
    "is this HUID AZ4526 genuine?" --audience consumer
```

Output streams token-by-token as the model generates, then prints a
summary: which model/backend answered, the detected intent, resolved
citations (mapped back to real IS numbers/clauses), any invalid citation
markers (the model citing a source number that doesn't exist — a real
failure mode worth watching for on smaller/free-tier models), and any
guardrail actions taken (e.g. a long verbatim quote from a standard was
redacted — see `docs/DECISIONS.md`, Step 5).

**"forced refusal: no retrieval results, LLM was not called."** This is
correct behavior, not a bug — the answer engine never sends an ungrounded
query to the LLM. It means Step 4's hybrid search found nothing for this
query in the current corpus; check with `app.retrieval.cli query` first
to confirm whether that's a coverage gap (nothing crawled on this topic
yet) or a genuinely out-of-scope question.

**401/403 from the hosted API.** Check `HOSTED_LLM_API_KEY` is set and
current — NVIDIA NIM keys can expire or hit free-tier rate limits; the
error body from the provider is printed via the propagated
`httpx.HTTPStatusError`, which usually says which.

## Running the API (Step 6)

With the full stack up (`docker compose -f infra/docker-compose.yml up`),
the chat endpoint streams Server-Sent Events. From another terminal:

```bash
curl -N -X POST http://localhost:8000/api/v1/chat \
    -H "Content-Type: application/json" \
    -c cookies.txt \
    -d '{"message": "which standard covers LED drivers?"}'
```

`-N` disables curl's output buffering (needed to see tokens arrive live)
and `-c cookies.txt` saves the session cookie so a follow-up request can
read history back:

```bash
# grab the conversation_id from the first SSE "conversation" event, then:
curl -b cookies.txt http://localhost:8000/api/v1/conversations
curl -b cookies.txt http://localhost:8000/api/v1/conversations/<id>/messages
```

Interactive API docs (request/response schemas for every endpoint,
try-it-out for the non-streaming ones) are at http://localhost:8000/docs.

**The response hangs with no output.** Almost always retrieval or the LLM
call is slow (cold-start reranker or Ollama model load — see Step 4/5
troubleshooting above), not the API layer itself; `curl -N` with no output
for 10-20s on first request after a cold `docker compose up` is expected.

**Session cookie isn't being sent back by curl/a browser.** `SESSION_COOKIE_SECURE`
defaults to `false` for local HTTP development (`.env.example`); if you set
it to `true` for an HTTPS deployment, the cookie is dropped over plain
HTTP, which will look identical to "no session" (every request gets a
fresh session, `GET /conversations` always returns `[]`).

**`GET /conversations/{id}/messages` returns 404 for a conversation you
just created.** Almost always the session cookie wasn't sent on the second
request (browser/HTTP client not persisting cookies across calls) or
`APP_SECRET_KEY` in `.env` was changed/rotated between the two requests,
which invalidates every outstanding session cookie's signature — this 404
is the same for "conversation doesn't exist" and "belongs to a different
session," by design (see `docs/DECISIONS.md`, Step 6), so it doesn't
distinguish which happened.

## Running the frontend (Step 7)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 — the Vite dev server proxies `/api` to the
backend (`http://localhost:8000` by default; override with
`VITE_API_PROXY_TARGET` if your backend runs elsewhere), so the SPA and API
share an origin and the session cookie works with no CORS configuration
needed. `docker compose -f infra/docker-compose.yml up` also brings up a
`frontend` service if you'd rather run everything in containers.

Ask a question in the chat box; the answer streams in token-by-token, and
citations for the currently active answer appear in the right-hand panel
(desktop only — see `docs/DECISIONS.md`, Step 7, on the mobile layout
gap). Click any `[N]` marker in an answer to jump to that source in the
panel. The audience toggle (top right) switches between the consumer and
industry personas — see `app.answer.prompts` on the backend for what that
actually changes.

**Chat box does nothing / no network request when I click send.** Check
the browser console — `fetch` to `/api/v1/chat` failing usually means the
backend isn't reachable at the dev-proxy target, or (in Docker) the
`backend` service isn't up yet.

**Answer streams in, but the citation panel says "no citable sources" even
though the text has `[1]` in it.** This is the citation validator
correctly reporting an out-of-range/hallucinated marker — check the chat
bubble for the "unverified citation" badge, which means the model cited a
source number that doesn't correspond to any retrieved context (a real
failure mode on smaller/free-tier hosted models — see
`docs/DECISIONS.md`, Step 5).

**Refreshing the page loses the conversation.** Expected for now — Step 7
doesn't restore history from `GET /conversations` on load (see
`docs/DECISIONS.md`). The conversation is still persisted server-side
(Step 6) and reachable via that endpoint; the UI just doesn't fetch it yet.

**`npm run build` or `npx tsc -b` fails after pulling this step.** Run
`npm install` first — this step added `class-variance-authority` and
`lucide-react` as dependencies.

## Running the certification wizard (Step 8)

No new services needed — the rules engine is pure YAML files loaded from
disk, so it works with just the backend running:

```bash
curl http://localhost:8000/api/v1/certification/schemes | jq
curl -X POST http://localhost:8000/api/v1/certification/wizard \
  -H "Content-Type: application/json" -d '{}'
# -> asks for product_description
curl -X POST http://localhost:8000/api/v1/certification/wizard \
  -H "Content-Type: application/json" \
  -d '{"product_description": "gold jewellery"}'
# -> matches HALLMARKING, with fee/timeline/document data and the
#    illustrative-data disclaimer
```

Run just the rules-engine unit tests (fast, no DB): `pytest tests/rules
tests/api/test_certification.py`.

## Running verification and gap analysis (Step 9)

Needs the database migrated (`alembic upgrade head`) and, for a non-empty
result, some seeded licences — either run the Step 13 seed script
(`SEED_DEMO_DATA=true python -m app.db.seed`) or insert your own test rows.

```bash
curl -X POST http://localhost:8000/api/v1/verify \
  -H "Content-Type: application/json" -d '{"licence_number": "CML-DEMO-0001"}'

curl -X POST http://localhost:8000/api/v1/analysis/gap-check \
  -H "Content-Type: application/json" \
  -d '{"product_description": "LED light bulb", "held_licence_numbers": []}'
```

## Enabling translation (Step 10)

Off by default (`TRANSLATION_BACKEND=none` — the chat endpoint never
touches the network for this). To translate answers via Bhashini:

1. Get an API key + user ID from https://bhashini.gov.in (or your org's
   Bhashini access) and a pipeline id for the language pairs you need.
2. Set `TRANSLATION_BACKEND=bhashini`, `BHASHINI_API_KEY`,
   `BHASHINI_USER_ID`, `BHASHINI_PIPELINE_ID` in `.env`.
3. Pass `target_language` (an ISO 639-1 code, e.g. `"hi"`) in the
   `POST /chat` body. The `final` SSE event gains a `translated_text`
   field — see `docs/DECISIONS.md`, Step 10, for why the streamed tokens
   themselves stay English.

## Running the officer dashboard (Step 11)

```bash
curl http://localhost:8000/api/v1/analytics/summary | jq
```

Open http://localhost:5173/dashboard (or click "Officer dashboard" in the
chat UI's header) once some conversations exist — send a few chat messages
first, otherwise every number is zero. No login gate yet (see
`docs/DECISIONS.md`, Step 11) — this route is reachable by anyone who can
reach the frontend.

## Running the full evaluation harness (Step 12)

Needs a fully working stack (Postgres migrated + some ingested content +
the reranker service + a configured LLM backend) — this exercises the real
answer engine end to end, unlike Step 4's retrieval-only baseline:

```bash
docker compose exec backend python -m app.eval.cli run
```

Prints per-question pass/fail flags and the aggregate metrics described in
`docs/EVALUATION.md`. Swap in a different golden set with `--golden-set
/path/to/file.jsonl` (same JSONL shape as `eval/golden_set_full.jsonl`).

## Production deployment and offline/demo mode (Step 13)

```bash
cp .env.example .env
# edit .env — for the fully offline demo mode, leave LLM_BACKEND=ollama
# and TRANSLATION_BACKEND=none (both are the defaults)
docker compose -f infra/docker-compose.prod.yml up --build
```

This builds the backend/frontend from their Dockerfiles' `production`
stage (no hot reload, no bind-mounted source) and puts Nginx in front of
the built frontend, proxying `/api` to the backend with SSE-safe
`proxy_buffering off` on the chat endpoint specifically (see
`infra/nginx/nginx.conf`'s header comment and `docs/DECISIONS.md`, Step
13, for why that particular setting matters here). Open http://localhost/
— there is no separate frontend port in this stack, Nginx serves on 80.

**Seeding demo data.** Set `SEED_DEMO_DATA=true` in `.env` before bringing
the stack up — the one-shot `seed` service runs `python -m app.db.seed`
once and exits, inserting a handful of standards/schemes/licences (all
`Licence` rows flagged `is_seed_data=True`) so `/verify`, `/analysis/
gap-check` and the certification wizard have something to return
immediately, without needing a real crawl/ingest run first. Safe to run
against an already-seeded database — every insert is guarded by a natural-
key existence check, so nothing duplicates.

**Fully offline mode.** With `LLM_BACKEND=ollama` and
`TRANSLATION_BACKEND=none` (both defaults), the backend makes zero
outbound network calls once the stack is up and the Ollama models have
been pulled — everything (retrieval, generation, embeddings, rules engine,
verification, gap analysis) runs against services inside the Docker
network. This is decision #3's "data-sovereign deployment mode" made
concrete; switch `LLM_BACKEND=hosted` (and set `HOSTED_LLM_API_KEY`) if you
want the demo to use a hosted model instead.

**`docker compose -f infra/docker-compose.prod.yml up` fails to build the
frontend / Nginx can't find files.** Make sure you're building from the
`infra/` directory context as shown above (paths in that compose file are
relative to it) and that `../frontend/package-lock.json` exists — the
Dockerfile's production stage needs a clean `npm install` + `npm run
build` to produce `dist/`, which is what gets copied into the Nginx image.
