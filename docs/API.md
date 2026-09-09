# API

The full v1 surface, as it stands after all 14 build steps. See the
interactive schema at `GET /docs` (Swagger UI, auto-enabled by FastAPI) for
the live, authoritative contract at any time — this document is a guided
tour, not a generated reference, so treat it as secondary if the two ever
disagree.

Every error response across the API is an RFC 7807 problem-detail body
(`backend/app/core/errors.py`), `Content-Type: application/problem+json`:

```json
{
  "type": "https://manak-sahayak.dev/errors/not-found",
  "title": "Resource not found",
  "status": 404,
  "detail": "No conversation ... for this session.",
  "instance": "/api/v1/conversations/.../messages"
}
```

## Health (Step 1)

### `GET /api/v1/health`

Checks Postgres and Redis connectivity. Returns `HealthStatus`.

```json
{ "status": "ok", "database": "ok", "redis": "ok", "app_env": "development", "llm_backend": "ollama" }
```

## Chat and conversations (Step 6, feedback added Step 11)

### `POST /api/v1/chat`

Streams a grounded, cited answer over Server-Sent Events. Body is
`ChatRequest` (`message`, optional `conversation_id`/`audience`/
`target_language` — the last one added in Step 10). Events, in order:
`conversation` (once, immediately) → zero or more `token` → exactly one
`final` (citations, guardrail flags, intent, model, latency, and — if
`target_language` was set — `translated_text`) — or `error` instead of
`final` if something failed mid-stream. Issues/reads the anonymous
session cookie (`ms_session`).

### `GET /api/v1/conversations` / `GET /api/v1/conversations/{id}/messages`

Read back persisted history, scoped to the caller's session cookie. 404 if
the cookie is missing or belongs to a different session than the
conversation.

### `PATCH /api/v1/conversations/{id}/messages/{message_id}/feedback` (Step 11)

Body: `{"rating": 1 | 0 | -1, "comment": "optional string"}`. Sets
`Message.feedback_rating`/`feedback_comment`, feeding the officer
dashboard's feedback-rate metrics. Session-scoped like the endpoints above.

## Certification (Step 8)

### `GET /api/v1/certification/schemes`

Returns every scheme in the YAML rules engine (`list[SchemeRules]`) — name,
description, fees, timeline, validity, required documents, and the
`source_note` illustrative-data disclaimer. No DB, no LLM.

### `POST /api/v1/certification/wizard`

Stateless multi-step Q&A. Body is `WizardAnswers` (`product_description`,
`manufactured_in_india`) — resend the full answers dict each call. Returns
either `{"done": false, "next_question": {...}}` or `{"done": true,
"results": [...], "disclaimer": "..."}`.

## Verification and gap analysis (Step 9)

### `POST /api/v1/verify`

Body: `{"licence_number": "...", "licence_type": "cml" | "crs_r" | "huid" | null}`.
Looks up the number in the seeded `licences` table (case-insensitive).
Returns `{"found": bool, "result": {...} | null, "message": "..."}` — the
message explicitly notes this is not a live BIS registry query.

### `POST /api/v1/analysis/gap-check`

Body: `{"product_description": "...", "held_licence_numbers": [...]}`.
Matches schemes against the description, checks which are covered by
active held licences, and returns missing mandatory/voluntary schemes plus
a disclaimer.

## Analytics (Step 11)

### `GET /api/v1/analytics/summary`

No auth gate yet (see `docs/DECISIONS.md`, Step 11 — this needs a real
"officer" role before production use). Returns `AnalyticsSummary`: total
conversations/messages, intent distribution, guardrail-violation count,
forced-refusal rate, average latency, feedback thumbs up/down and response
rate. Powers `frontend/src/pages/OfficerDashboard.tsx`.

## Not exposed over HTTP

- The Step 4 retrieval-only baseline (`app.retrieval.cli baseline`) and the
  Step 5 answer-engine CLI (`app.answer.cli ask`) are deliberately CLI-only
  debugging tools, not API routes.
- The Step 12 full-pipeline evaluation harness (`app.eval.cli run`) is a
  CLI tool, not an endpoint — it's a developer/CI tool, not something a
  frontend would call.
- Demo-data seeding (`app.db.seed`) runs as a one-shot script/container
  command (Step 13), not an endpoint — seeding production data over HTTP
  would be a very easy way to corrupt a real deployment by accident.
