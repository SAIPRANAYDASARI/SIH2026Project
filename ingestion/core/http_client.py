"""Polite async HTTP fetching: robots.txt check, per-host rate limiting,
and retry with exponential backoff, all composed into one `fetch()` call so
every crawler gets the same politeness guarantees without repeating the
composition logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.logging import get_logger
from ingestion.core.rate_limiter import HostRateLimiter
from ingestion.core.robots import RobotsCache

logger = get_logger(__name__)

USER_AGENT = "ManakSahayakBot/0.1 (+https://github.com/manak-sahayak; SIH26107 hackathon project)"


class RobotsDisallowedError(Exception):
    """Raised when robots.txt disallows fetching a URL. Callers should treat
    this as a skip, not a crawl failure — it is not retried."""


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    content: bytes
    fetched_at: str  # ISO 8601, UTC


class PoliteFetcher:
    """One instance per crawl run. Shares a single httpx.AsyncClient, rate
    limiter and robots cache across every request the run makes."""

    def __init__(
        self,
        *,
        min_interval_seconds: float = 2.0,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # `transport` is only ever overridden in tests (httpx.MockTransport),
        # so unit tests never make a real network call.
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
        )
        self._rate_limiter = HostRateLimiter(min_interval_seconds)
        self._robots = RobotsCache(USER_AGENT)

    async def __aenter__(self) -> PoliteFetcher:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._client.aclose()

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _get(self, url: str) -> httpx.Response:
        response = await self._client.get(url)
        return response

    async def fetch(self, url: str) -> FetchResult:
        if not await self._robots.is_allowed(url, self._client):
            logger.info("robots_disallowed", url=url)
            raise RobotsDisallowedError(url)

        host = urlparse(url).netloc
        await self._rate_limiter.wait_for_turn(host)

        response = await self._get(url)
        return FetchResult(
            url=url,
            status_code=response.status_code,
            content=response.content,
            fetched_at=datetime.now(UTC).isoformat(),
        )
