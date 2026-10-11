"""Single-process, per-principal sliding-window request limiter."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    def __init__(self, *, limit: int, window_seconds: int) -> None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("rate limit configuration must be positive")
        self._limit = limit
        self._window = float(window_seconds)
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, principal: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            events = self._events[principal]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self._limit:
                return False
            events.append(now)
            return True
