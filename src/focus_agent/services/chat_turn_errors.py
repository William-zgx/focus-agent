from __future__ import annotations


class ConcurrentTurnError(RuntimeError):
    """Raised when a thread already has an in-flight turn."""


__all__ = ["ConcurrentTurnError"]
