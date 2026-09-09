"""Health endpoint returns 200 with a real (if degraded) status body."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_ok_status(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"  # SELECT 1 succeeds against the sqlite fixture
    assert "app_env" in body
    assert "llm_backend" in body


@pytest.mark.asyncio
async def test_health_reports_unreachable_redis_gracefully(client: AsyncClient) -> None:
    # No Redis is running in the unit-test environment, so this exercises the
    # "dependency is down but the endpoint still answers" path relied on by
    # the RUNBOOK's demo-day triage steps.
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["redis"] in {"ok", "unreachable"}
