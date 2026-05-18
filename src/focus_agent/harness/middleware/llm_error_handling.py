from __future__ import annotations

import asyncio
import functools
import inspect
import random
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from .base import BaseAgentMiddleware, MiddlewareHandler
from .errors import CircuitBreakerOpenError, MiddlewareError

try:  # pragma: no cover - exercised when langgraph is installed.
    from langgraph.errors import GraphBubbleUp as _GraphBubbleUp
except Exception:  # pragma: no cover - keeps static import safe in minimal envs.
    _GraphBubbleUp = None


CircuitState = Literal["closed", "open", "half_open"]


@dataclass(frozen=True, slots=True)
class CircuitBreakerSnapshot:
    state: CircuitState
    consecutive_failures: int
    opened_at: float | None


@dataclass(slots=True)
class CircuitBreaker:
    """Small thread-safe circuit breaker for repeated LLM failures."""

    failure_threshold: int = 5
    recovery_timeout_s: float = 30.0
    clock: Callable[[], float] = time.monotonic
    _consecutive_failures: int = field(default=0, init=False)
    _opened_at: float | None = field(default=None, init=False)
    _half_open_trial: bool = field(default=False, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def before_call(self) -> None:
        if self.failure_threshold <= 0:
            return
        with self._lock:
            if self._opened_at is None:
                return
            now = self.clock()
            if now - self._opened_at < self.recovery_timeout_s:
                raise CircuitBreakerOpenError("LLM circuit breaker is open.")
            if self._half_open_trial:
                raise CircuitBreakerOpenError("LLM circuit breaker half-open trial is in flight.")
            self._half_open_trial = True

    def record_success(self) -> None:
        if self.failure_threshold <= 0:
            return
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None
            self._half_open_trial = False

    def record_failure(self) -> None:
        if self.failure_threshold <= 0:
            return
        with self._lock:
            self._consecutive_failures += 1
            self._half_open_trial = False
            if self._opened_at is not None or self._consecutive_failures >= self.failure_threshold:
                self._opened_at = self.clock()

    def snapshot(self) -> CircuitBreakerSnapshot:
        with self._lock:
            state: CircuitState = "closed"
            if self._opened_at is not None:
                if self.clock() - self._opened_at >= self.recovery_timeout_s:
                    state = "half_open"
                else:
                    state = "open"
            return CircuitBreakerSnapshot(
                state=state,
                consecutive_failures=self._consecutive_failures,
                opened_at=self._opened_at,
            )


@dataclass(slots=True)
class LLMErrorHandlingMiddleware(BaseAgentMiddleware):
    """Retry transient LLM failures with backoff and circuit breaking."""

    retry: Any | None = None
    max_retries: int = 2
    initial_backoff_s: float = 0.25
    max_backoff_s: float = 4.0
    backoff_multiplier: float = 2.0
    jitter_s: float = 0.0
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,)
    retry_predicate: Callable[[BaseException], bool] | None = None
    circuit_breaker: CircuitBreaker | None = field(default_factory=CircuitBreaker)
    sleep: Callable[[float], None] = time.sleep
    async_sleep: Callable[[float], Awaitable[Any] | None] | None = None

    def __post_init__(self) -> None:
        if self.retry is not None:
            self._apply_retry_config(self.retry)
        if self.circuit_breaker is not None and not isinstance(self.circuit_breaker, CircuitBreaker):
            self.circuit_breaker = self._circuit_breaker_from_config(self.circuit_breaker)
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0.")
        if self.initial_backoff_s < 0:
            raise ValueError("initial_backoff_s must be >= 0.")
        if self.max_backoff_s < 0:
            raise ValueError("max_backoff_s must be >= 0.")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be >= 1.")
        if self.jitter_s < 0:
            raise ValueError("jitter_s must be >= 0.")

    def _apply_retry_config(self, retry: Any) -> None:
        max_attempts = _config_value(retry, "max_attempts", None)
        if max_attempts is not None:
            self.max_retries = max(0, int(max_attempts) - 1)

        base_delay_ms = _config_value(retry, "base_delay_ms", None)
        if base_delay_ms is not None:
            self.initial_backoff_s = float(base_delay_ms) / 1000.0

        max_delay_ms = _config_value(retry, "max_delay_ms", None)
        if max_delay_ms is not None:
            self.max_backoff_s = float(max_delay_ms) / 1000.0

    @staticmethod
    def _circuit_breaker_from_config(config: Any) -> CircuitBreaker:
        return CircuitBreaker(
            failure_threshold=int(_config_value(config, "failure_threshold", 5)),
            recovery_timeout_s=float(
                _config_value(
                    config,
                    "recovery_timeout_s",
                    _config_value(config, "recovery_timeout_seconds", 30.0),
                )
            ),
        )

    def wrap(self, handler: MiddlewareHandler) -> MiddlewareHandler:
        if inspect.iscoroutinefunction(handler):

            @functools.wraps(handler)
            async def async_wrapped(*args: Any, **kwargs: Any) -> Any:
                return await self._invoke_async(handler, *args, **kwargs)

            return async_wrapped

        @functools.wraps(handler)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            return self._invoke_sync(handler, *args, **kwargs)

        return wrapped

    def _invoke_sync(self, handler: MiddlewareHandler, *args: Any, **kwargs: Any) -> Any:
        if self.circuit_breaker is not None:
            self.circuit_breaker.before_call()

        attempt = 0
        while True:
            try:
                result = handler(*args, **kwargs)
            except BaseException as exc:
                if self._must_bubble(exc):
                    raise
                if not self._should_retry(exc) or attempt >= self.max_retries:
                    self._record_failure()
                    raise
                self.sleep(self._backoff_delay(attempt))
                attempt += 1
                continue
            self._record_success()
            return result

    async def _invoke_async(
        self,
        handler: MiddlewareHandler,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if self.circuit_breaker is not None:
            self.circuit_breaker.before_call()

        attempt = 0
        while True:
            try:
                result = await handler(*args, **kwargs)
            except BaseException as exc:
                if self._must_bubble(exc):
                    raise
                if not self._should_retry(exc) or attempt >= self.max_retries:
                    self._record_failure()
                    raise
                await self._sleep_async(self._backoff_delay(attempt))
                attempt += 1
                continue
            self._record_success()
            return result

    def _record_success(self) -> None:
        if self.circuit_breaker is not None:
            self.circuit_breaker.record_success()

    def _record_failure(self) -> None:
        if self.circuit_breaker is not None:
            self.circuit_breaker.record_failure()

    def _should_retry(self, exc: BaseException) -> bool:
        if not isinstance(exc, self.retry_exceptions):
            return False
        if self.retry_predicate is None:
            return True
        return bool(self.retry_predicate(exc))

    def _backoff_delay(self, attempt: int) -> float:
        delay = self.initial_backoff_s * (self.backoff_multiplier**attempt)
        delay = min(delay, self.max_backoff_s)
        if self.jitter_s:
            delay += random.uniform(0, self.jitter_s)
        return delay

    async def _sleep_async(self, delay: float) -> None:
        if self.async_sleep is None:
            await asyncio.sleep(delay)
            return
        maybe_awaitable = self.async_sleep(delay)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable

    @staticmethod
    def _must_bubble(exc: BaseException) -> bool:
        if isinstance(
            exc,
            (KeyboardInterrupt, SystemExit, GeneratorExit, asyncio.CancelledError, MiddlewareError),
        ):
            return True
        if _GraphBubbleUp is not None and isinstance(exc, _GraphBubbleUp):
            return True
        return exc.__class__.__name__ == "GraphBubbleUp"


def _config_value(config: Any, key: str, default: Any) -> Any:
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerSnapshot",
    "CircuitState",
    "LLMErrorHandlingMiddleware",
]
