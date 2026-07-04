"""Pending-message queues for steering and follow-up injection.

Implements the dual-queue model inspired by pi's ``steeringQueue`` and
``followUpQueue``:

* **Steer messages** are injected into the *current* turn (drained
  before the next LLM call within the turn).
* **Follow-up messages** are queued for processing *after* the current
  turn completes.

The :class:`PendingMessageQueue` provides a small async-safe primitive
with lock-guarded enqueue/drain semantics and a configurable drain
mode (``"all"`` or ``"one_at_a_time"``).
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Literal

DrainMode = Literal["all", "one_at_a_time"]


class PendingMessageQueue:
    """Async-safe FIFO queue for pending user messages.

    Args:
        drain_mode: Controls :meth:`drain` behavior:
            * ``"all"`` (default) -- drain every pending message in one
              call and return them as a list.
            * ``"one_at_a_time"`` -- pop and return at most a single
              message per :meth:`drain` call.
    """

    __slots__ = ("_queue", "_lock", "_drain_mode")

    def __init__(self, drain_mode: DrainMode = "all") -> None:
        if drain_mode not in {"all", "one_at_a_time"}:
            raise ValueError(
                f"drain_mode must be 'all' or 'one_at_a_time', got {drain_mode!r}"
            )
        self._queue: deque[str] = deque()
        self._lock: asyncio.Lock = asyncio.Lock()
        self._drain_mode: DrainMode = drain_mode

    @property
    def depth(self) -> int:
        """Number of messages currently waiting in the queue."""
        return len(self._queue)

    @property
    def drain_mode(self) -> DrainMode:
        return self._drain_mode

    async def enqueue(self, message: str) -> None:
        """Append ``message`` to the queue (thread-safe via lock)."""
        if not isinstance(message, str):
            raise TypeError(f"message must be str, got {type(message).__name__}")
        async with self._lock:
            self._queue.append(message)

    async def drain(self) -> list[str]:
        """Atomically pop and return pending messages.

        In ``"all"`` mode, returns every queued message (possibly an
        empty list) and clears the queue.  In ``"one_at_a_time"`` mode,
        returns a single-element list (or ``[]`` if empty).
        """
        async with self._lock:
            if not self._queue:
                return []
            if self._drain_mode == "one_at_a_time":
                return [self._queue.popleft()]
            drained = list(self._queue)
            self._queue.clear()
            return drained

    def peek(self) -> str | None:
        """Return the next message without removing it, or ``None``."""
        return self._queue[0] if self._queue else None

    def clear(self) -> None:
        """Discard all pending messages."""
        self._queue.clear()

    def __len__(self) -> int:
        return len(self._queue)

    def __bool__(self) -> bool:
        return bool(self._queue)


__all__ = ["DrainMode", "PendingMessageQueue"]
