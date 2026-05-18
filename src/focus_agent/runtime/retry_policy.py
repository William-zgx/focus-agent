from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: float = 0.2
    retriable_exceptions: tuple[type[BaseException], ...] = (Exception,)

    async def run_async(self, fn: Callable[[], Awaitable[T]]) -> T:
        last_exc: BaseException | None = None
        for attempt in range(max(1, self.max_attempts)):
            try:
                return await fn()
            except self.retriable_exceptions as exc:
                last_exc = exc
                if attempt >= self.max_attempts - 1:
                    raise
                await asyncio.sleep(self._delay(attempt))
        assert last_exc is not None
        raise last_exc

    def run(self, fn: Callable[[], T]) -> T:
        last_exc: BaseException | None = None
        for attempt in range(max(1, self.max_attempts)):
            try:
                return fn()
            except self.retriable_exceptions as exc:
                last_exc = exc
                if attempt >= self.max_attempts - 1:
                    raise
                time.sleep(self._delay(attempt))
        assert last_exc is not None
        raise last_exc

    def _delay(self, attempt: int) -> float:
        delay = min(max(self.base_delay, 0.0) * (2**attempt), max(self.max_delay, 0.0))
        if self.jitter > 0 and delay > 0:
            delay += random.uniform(0, self.jitter * delay)
        return delay


class CircuitBreakerOpenError(RuntimeError):
    pass


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_seconds: float = 30.0):
        self.failure_threshold = max(1, int(failure_threshold))
        self.recovery_seconds = max(0.0, float(recovery_seconds))
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_in_flight = False

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._can_probe():
            return "half_open"
        return "open"

    def before_call(self) -> None:
        if self._opened_at is None:
            return
        if not self._can_probe():
            raise CircuitBreakerOpenError("circuit breaker is open")
        if self._half_open_in_flight:
            raise CircuitBreakerOpenError("circuit breaker half-open probe is in flight")
        self._half_open_in_flight = True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._half_open_in_flight = False

    def record_failure(self) -> None:
        self._half_open_in_flight = False
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = time.monotonic()

    async def run_async(self, fn: Callable[[], Awaitable[T]]) -> T:
        self.before_call()
        try:
            result = await fn()
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result

    def _can_probe(self) -> bool:
        return self._opened_at is not None and (
            time.monotonic() - self._opened_at >= self.recovery_seconds
        )


__all__ = ["CircuitBreaker", "CircuitBreakerOpenError", "RetryPolicy"]
