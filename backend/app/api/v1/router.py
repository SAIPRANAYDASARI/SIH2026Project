"""Aggregates all v1 routers under a single prefix.

`/health` (Step 1) and `/chat` + `/conversations/*` (Step 6) are wired up.
Every other path in the API surface (`/standards/*`, `/certification/*`,
`/verify/*`, `/analysis/*`, `/analytics/*`) is added incrementally in Steps
8, 9 and 11, each as its own module here — never inline in this file —
with route handlers calling service classes rather than holding business
logic themselves.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import analysis, analytics, certification, chat, health, verify

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(certification.router)
api_router.include_router(verify.router)
api_router.include_router(analysis.router)
api_router.include_router(analytics.router)
