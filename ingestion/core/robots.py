"""robots.txt compliance, cached per host for the lifetime of a crawl run.

Uses the standard library's `urllib.robotparser` for the actual parsing
(it's the same logic every polite crawler uses) but fetches the robots.txt
body ourselves via the shared async HTTP client so the fetch is subject to
the same rate limiting, timeout and retry behaviour as every other request
this package makes — a robots.txt fetch that hangs forever souring the rest
of a run is a real failure mode worth avoiding.
"""

from __future__ import annotations

import urllib.robotparser
from urllib.parse import urlparse

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)


class RobotsCache:
    def __init__(self, user_agent: str) -> None:
        self._user_agent = user_agent
        self._parsers: dict[str, urllib.robotparser.RobotFileParser] = {}

    async def is_allowed(self, url: str, client: httpx.AsyncClient) -> bool:
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"

        if host not in self._parsers:
            self._parsers[host] = await self._fetch_robots(host, client)

        return self._parsers[host].can_fetch(self._user_agent, url)

    async def _fetch_robots(
        self, host: str, client: httpx.AsyncClient
    ) -> urllib.robotparser.RobotFileParser:
        parser = urllib.robotparser.RobotFileParser()
        robots_url = f"{host}/robots.txt"
        try:
            response = await client.get(robots_url, timeout=10.0)
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
            else:
                # No robots.txt (or it errored) is treated as "everything
                # allowed" per convention, matching every major crawler.
                parser.parse([])
        except httpx.HTTPError:
            logger.warning("robots_fetch_failed", host=host)
            parser.parse([])

        return parser
