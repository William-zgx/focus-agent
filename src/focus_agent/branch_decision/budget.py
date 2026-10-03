"""One deadline shared by recommendation attempts and their caller."""

from __future__ import annotations

from contextvars import ContextVar
from time import monotonic
from typing import Any

_deadline: ContextVar[float | None] = ContextVar("branch_recommendation_deadline", default=None)


def recommendation_deadline(settings: Any) -> float:
    existing = _deadline.get()
    if existing is not None:
        return existing
    timeout = float(getattr(settings, "agent_branch_recommendation_timeout_seconds", 15.0))
    return monotonic() + (min(timeout, 60.0) if timeout > 0 else 5.0)


def recommendation_expired(deadline: float | None = None) -> bool:
    value = deadline if deadline is not None else _deadline.get()
    return value is not None and monotonic() >= value


def run_with_recommendation_deadline(func: Any, *, deadline: float, **kwargs: Any) -> Any:
    # The daemon-thread helper does not propagate contextvars from the event loop.
    token = _deadline.set(deadline)
    try:
        return func(**kwargs)
    finally:
        _deadline.reset(token)
