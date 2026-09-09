"""PoliteFetcher composes robots.txt compliance and retry-with-backoff
correctly, using a mocked transport so no real network call is made."""

from __future__ import annotations

import httpx
import pytest

from ingestion.core.http_client import PoliteFetcher, RobotsDisallowedError

ALLOW_ALL_ROBOTS = "User-agent: *\nAllow: /\n"
DISALLOW_PRIVATE_ROBOTS = "User-agent: *\nDisallow: /private/\n"


@pytest.mark.asyncio
async def test_fetch_returns_content_when_allowed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ALLOW_ALL_ROBOTS)
        return httpx.Response(200, content=b"<html><title>OK</title></html>")

    async with PoliteFetcher(
        min_interval_seconds=0, transport=httpx.MockTransport(handler)
    ) as fetcher:
        result = await fetcher.fetch("https://example.com/page")

    assert result.status_code == 200
    assert b"OK" in result.content
    assert result.fetched_at  # non-empty ISO timestamp


@pytest.mark.asyncio
async def test_fetch_raises_when_robots_disallows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=DISALLOW_PRIVATE_ROBOTS)
        return httpx.Response(200, content=b"should not be reached")

    async with PoliteFetcher(
        min_interval_seconds=0, transport=httpx.MockTransport(handler)
    ) as fetcher:
        with pytest.raises(RobotsDisallowedError):
            await fetcher.fetch("https://example.com/private/page")


@pytest.mark.asyncio
async def test_fetch_retries_transient_transport_errors() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ALLOW_ALL_ROBOTS)
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise httpx.ConnectError("transient failure", request=request)
        return httpx.Response(200, content=b"succeeded after retries")

    async with PoliteFetcher(
        min_interval_seconds=0, timeout_seconds=5, transport=httpx.MockTransport(handler)
    ) as fetcher:
        result = await fetcher.fetch("https://example.com/flaky")

    assert attempts["count"] == 3
    assert result.content == b"succeeded after retries"


@pytest.mark.asyncio
async def test_fetch_gives_up_after_max_attempts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ALLOW_ALL_ROBOTS)
        raise httpx.ConnectError("permanent failure", request=request)

    async with PoliteFetcher(
        min_interval_seconds=0, timeout_seconds=5, transport=httpx.MockTransport(handler)
    ) as fetcher:
        with pytest.raises(httpx.ConnectError):
            await fetcher.fetch("https://example.com/always-down")
