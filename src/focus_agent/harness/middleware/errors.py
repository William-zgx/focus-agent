from __future__ import annotations


class MiddlewareError(RuntimeError):
    """Base error for harness middleware failures."""


class CircuitBreakerOpenError(MiddlewareError):
    """Raised when the LLM circuit breaker rejects a call."""


class LoopDetectedError(MiddlewareError):
    """Raised when the harness detects a repeated agent loop."""


__all__ = [
    "CircuitBreakerOpenError",
    "LoopDetectedError",
    "MiddlewareError",
]
