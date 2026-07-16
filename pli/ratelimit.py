"""In-memory sliding-window rate limiter.

Keys are opaque (IP strings, handle hex) and live only in process memory —
never persisted, never logged. Single process, tiny cohort: a dict is the
right tool. If you reach for Redis, the design has drifted.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and hits[0] <= now - window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True
