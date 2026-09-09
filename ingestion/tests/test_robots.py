"""RobotsCache correctly allows/disallows based on a fetched robots.txt, and
fails open (allows) when robots.txt is missing or unreachable."""

from __future__ import annotations

import httpx
import pytest

from ingestion.core.robots import RobotsCache

ROBOTS_TXT = "User-agent: *\nDisallow: /private/\n"


def _client_for(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


@pytest.mark.asyncio
async def test_disallowed_path_is_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=ROBOTS_TXT)

    cache = RobotsCache(user_agent="TestBot/1.0")
    async with _client_for(httpx.MockTransport(handler)) as client:
        assert await cache.is_allowed("https://example.com/private/page", client) is False


@pytest.mark.asyncio
async def test_allowed_path_is_permitted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=ROBOTS_TXT)

    cache = RobotsCache(user_agent="TestBot/1.0")
    async with _client_for(httpx.MockTransport(handler)) as client:
        assert await cache.is_allowed("https://example.com/public/page", client) is True


@pytest.mark.asyncio
async def test_missing_robots_txt_fails_open() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    cache = RobotsCache(user_agent="TestBot/1.0")
    async with _client_for(httpx.MockTransport(handler)) as client:
        assert await cache.is_allowed("https://example.com/anything", client) is True


@pytest.mark.asyncio
async def test_robots_fetch_error_fails_open() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    cache = RobotsCache(user_agent="TestBot/1.0")
    async with _client_for(httpx.MockTransport(handler)) as client:
        assert await cache.is_allowed("https://example.com/anything", client) is True


@pytest.mark.asyncio
async def test_result_is_cached_per_host() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, text=ROBOTS_TXT)

    cache = RobotsCache(user_agent="TestBot/1.0")
    async with _client_for(httpx.MockTransport(handler)) as client:
        await cache.is_allowed("https://example.com/a", client)
        await cache.is_allowed("https://example.com/b", client)

    assert call_count == 1
