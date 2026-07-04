"""Coalesced wakeup helper.

Inspired by opencode's ``RunCoordinator.pendingWake`` pattern, this helper
lets multiple producers signal "work is available" without piling up
concurrent drain invocations. If a drain is already running when
:meth:`wake` fires, a single flag is set so the drain runs one more time
after the current invocation finishes, guaranteeing no event is lost
while still bounding re-entrancy.

Typical usage::

    helper = CoalescedWakeupHelper()

    async def drain() -> None:
        # pull work off a queue and process it
        ...

    # called by producers whenever new work arrives:
    helper.wake()

    # called by a consumer loop that wants to drain without stacking:
    await helper.execute_with_coalescing(drain)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("focus_agent.harness.runtime.coalesced_wakeup")


class CoalescedWakeupHelper:
    """Serialize drain invocations with coalesced wakeup signals.

    The helper tracks two bits of state:

    * ``_active``: a drain function is currently executing.
    * ``_pending_wake``: at least one producer called :meth:`wake` while
      the previous drain was active, meaning another pass is required.

    The lock guards both flags so the test-then-set pattern is atomic
    across tasks.
    """

    def __init__(self) -> None:
        self._active: bool = False
        self._pending_wake: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def active(self) -> bool:
        """Return ``True`` if a drain is currently executing."""
        return self._active

    @property
    def pending_wake(self) -> bool:
        """Return ``True`` if a coalesced wake is pending."""
        return self._pending_wake

    def wake(self) -> None:
        """Signal that new work is available.

        If a drain is currently active this just sets the ``pending_wake``
        flag (coalescing multiple rapid signals into one follow-up pass).
        Otherwise the flag is set so a subsequent call to
        :meth:`execute_with_coalescing` will enter the drain immediately.

        This method is synchronous and non-blocking; it is safe to call
        from any task (including from inside the drain function itself).
        """
        if self._active:
            self._pending_wake = True
            logger.debug("CoalescedWakeupHelper: wake coalesced (active drain)")
        else:
            # When idle we still set the flag so the next
            # execute_with_coalescing call proceeds; the drain loop is
            # responsible for clearing it when it decides to stop.
            self._pending_wake = True
            logger.debug("CoalescedWakeupHelper: wake recorded (idle)")

    async def execute_with_coalescing(self, drain_fn: Callable[..., Any]) -> None:
        """Run ``drain_fn``, re-running it if extra wakes arrived.

        If a drain is already active this method returns immediately
        (the running drain will pick up the new work via the pending flag).
        Otherwise it enters a loop: run ``drain_fn``, then if
        ``pending_wake`` was set during execution clear the flag and run
        again, repeating until no wake arrived during the last pass.

        ``drain_fn`` may be a regular function, an ``async def`` coroutine
        function, or any awaitable. Exceptions propagate to the caller;
        the ``_active`` flag is always reset on exit.
        """
        async with self._lock:
            if self._active:
                self._pending_wake = True
                logger.debug("CoalescedWakeupHelper: drain already active; marking pending")
                return
            self._active = True
            # If there is no explicit wake pending we still run once
            # (callers invoke execute_with_coalescing to drive the drain
            # proactively). Clear the pending flag on entry.
            self._pending_wake = False

        try:
            while True:
                try:
                    result = drain_fn()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:  # noqa: BLE001
                    logger.exception("CoalescedWakeupHelper: drain_fn raised")
                    raise
                async with self._lock:
                    if self._pending_wake:
                        self._pending_wake = False
                        logger.debug("CoalescedWakeupHelper: coalesced wake; re-draining")
                        continue
                    self._active = False
                    break
        finally:
            # Defensive: ensure _active is reset even on exception.
            async with self._lock:
                self._active = False

    def reset(self) -> None:
        """Force-reset all internal state (intended for tests/shutdown)."""
        self._active = False
        self._pending_wake = False


__all__ = ["CoalescedWakeupHelper"]
