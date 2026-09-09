"""HostRateLimiter enforces the minimum interval, per host, without
blocking unrelated hosts against each other."""

from __future__ import annotations

import time

import pytest

from ingestion.core.rate_limiter import HostRateLimiter


@pytest.mark.asyncio
async def test_second_request_to_same_host_waits() -> None:
    limiter = HostRateLimiter(min_interval_seconds=0.2)

    start = time.monotonic()
    await limiter.wait_for_turn("example.com")
    await limiter.wait_for_turn("example.com")
    elapsed = time.monotonic() - start

    assert elapsed >= 0.2


@pytest.mark.asyncio
async def test_different_hosts_do_not_wait_on_each_other() -> None:
    limiter = HostRateLimiter(min_interval_seconds=1.0)

    start = time.monotonic()
    await limiter.wait_for_turn("a.example.com")
    await limiter.wait_for_turn("b.example.com")
    elapsed = time.monotonic() - start

    assert elapsed < 0.5
