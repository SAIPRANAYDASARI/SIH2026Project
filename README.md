# Manak Sahayak

AI-powered intelligent assistant for Indian Standards and BIS (Bureau of Indian Standards)
services — built for Smart India Hackathon 2026, problem statement **SIH26107**
(Ministry of Consumer Affairs, Food & Public Distribution).

Manak Sahayak helps industry and consumers ask, in plain language, which Indian Standard
governs a product, which BIS certification scheme applies, what a certification mark on a
product actually means, and whether a licence number is genuine — with every substantive
answer traced to a cited source and an IS number/clause reference.

## Legal note on content

Full texts of Indian Standards are copyrighted and sold by BIS; **this project does not
reproduce or redistribute IS document text**. Only titles, scopes, metadata, certification
scheme guidance, Quality Control Order (QCO) product lists and public circulars are indexed.
Where a standard's full text is needed, the assistant points the user to the correct IS
number to purchase from BIS rather than reproducing it. See `docs/DATA_SOURCES.md`.

## Status

All 14 steps of the build brief are complete: repo scaffold/CI, crawlers/provenance, the
ingestion pipeline, the retrieval core, the answer engine, the FastAPI/persistence layer,
the React chat UI, the rules engine + certification wizard, licence verification + gap
analysis, multilingual translation, the officer dashboard, the full-pipeline evaluation
harness, production deployment + demo seeding + offline mode, and this documentation
pass. See `docs/DECISIONS.md` for the full step-by-step rationale and explicit scope
trade-offs (several steps deliberately reduce the brief's scope — e.g. a 5-scheme rules
dataset, a ~25-question golden set, translation without voice — each one flagged in
place, not silently cut).

## Quickstart

**Local development** (hot reload, all 14 steps' functionality):

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

This brings up: Postgres 16 + pgvector, Redis, the FastAPI backend (hot reload), a Celery
worker, the Vite frontend dev server, and a local Ollama container. See
`docs/RUNBOOK.md` for troubleshooting and `docs/ARCHITECTURE.md` for the system design.

Backend health check: http://localhost:8000/api/v1/health
Frontend: http://localhost:5173 · Officer dashboard: http://localhost:5173/dashboard

Once the reranker container has warmed up and you've crawled + processed some content
(Steps 2-3), open http://localhost:5173 for the chat UI, or try the retrieval core CLI,
the answer engine CLI, and the raw API first — see `docs/RUNBOOK.md` for all of it,
including a free NVIDIA NIM API key for the hosted LLM path. Interactive API docs:
http://localhost:8000/docs

**Production / fully offline demo mode** (built frontend behind Nginx, no hot reload):

```bash
cp .env.example .env   # SEED_DEMO_DATA=true for immediate demo data
docker compose -f infra/docker-compose.prod.yml up --build
```

Open http://localhost/ (Nginx serves on port 80 in this stack). See `docs/RUNBOOK.md`,
"Production deployment and offline/demo mode (Step 13)".

## Repo layout

```
/backend     FastAPI service (app/rules, app/translate, app/eval, app/db/seed.py — Steps 8-13)
/worker      Celery tasks
/ingestion   crawlers and parsers (Step 2+)
/eval        golden_set_sample.jsonl (Step 4 baseline) + golden_set_full.jsonl (Step 12)
/frontend    React + Vite (ChatPage + OfficerDashboard, react-router-dom — Step 11)
/infra       docker, nginx (production SSE-safe proxy — Step 13), compose (dev + prod)
/docs        ARCHITECTURE.md, DATA_SOURCES.md, API.md, EVALUATION.md, DECISIONS.md, RUNBOOK.md
```
