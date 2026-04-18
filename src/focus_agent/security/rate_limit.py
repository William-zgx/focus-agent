from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque


@dataclass(slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_seconds: float


class SlidingWindowRateLimiter:
    """In-memory sliding window rate limiter keyed by an arbitrary identity.

    Suitable for single-process deployments. For multi-worker or distributed
    deployments, swap with a Redis-backed implementation.
    """

    def __init__(self, *, window_seconds: float = 60.0) -> None:
        self._window_seconds = float(window_seconds)
        self._events: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, *, key: str, limit: int) -> RateLimitResult:
        if limit <= 0:
            return RateLimitResult(allowed=True, remaining=0, retry_after_seconds=0.0)
        now = time.monotonic()
        horizon = now - self._window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= horizon:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(0.0, events[0] + self._window_seconds - now)
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    retry_after_seconds=retry_after,
                )
            events.append(now)
            return RateLimitResult(
                allowed=True,
                remaining=max(0, limit - len(events)),
                retry_after_seconds=0.0,
            )


__all__ = ["RateLimitResult", "SlidingWindowRateLimiter"]
