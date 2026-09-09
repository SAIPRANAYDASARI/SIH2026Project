"""Liveness/readiness endpoint.

Checks the two hard dependencies (Postgres, Redis) so `docker compose`
health checks and the RUNBOOK's "is anything actually broken" triage both
have one real endpoint to hit, rather than a bare 200 that lies about the
database being reachable.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.common import HealthStatus

router = APIRouter(tags=["health"])


async def _check_database(db: AsyncSession) -> str:
    try:
        await db.execute(text("SELECT 1"))
        return "ok"
    except Exception:  # noqa: BLE001 - health check must not raise
        return "unreachable"


async def _check_redis(settings: Settings) -> str:
    try:
        client: Redis = Redis.from_url(settings.redis_uri)
        await client.ping()
        await client.aclose()
        return "ok"
    except Exception:  # noqa: BLE001 - health check must not raise
        return "unreachable"


@router.get("/health", response_model=HealthStatus)
async def health(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HealthStatus:
    return HealthStatus(
        status="ok",
        database=await _check_database(db),
        redis=await _check_redis(settings),
        app_env=settings.app_env,
        llm_backend=settings.llm_backend,
    )
