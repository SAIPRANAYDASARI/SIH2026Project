"""Per-host rate limiting.

One request per two seconds per host, per the brief. A single process-wide
limiter is enough for a hackathon-scale crawl (one worker process at a
time); if ingestion is ever parallelized across multiple worker processes,
this needs to move to a Redis-backed token bucket instead of an in-memory
lock — noted here rather than built now since nothing in Step 2 needs it.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict


class HostRateLimiter:
    """Ensures at least `min_interval_seconds` elapses between requests to
    the same host, across concurrent callers within one process."""

    def __init__(self, min_interval_seconds: float = 2.0) -> None:
        self._min_interval = min_interval_seconds
        self._last_request_at: dict[str, float] = defaultdict(lambda: 0.0)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait_for_turn(self, host: str) -> None:
        async with self._locks[host]:
            elapsed = time.monotonic() - self._last_request_at[host]
            remaining = self._min_interval - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_request_at[host] = time.monotonic()
