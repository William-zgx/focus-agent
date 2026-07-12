"""Steering and follow-up queue orchestration for harness runs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger("focus_agent.harness.runtime")


class RunFollowupsMixin:
    """Provide per-thread steering and follow-up queues for ``RunManager``."""

    def _initialize_followup_runtime(self, *, enable_followup_drain: bool) -> None:
        # Dual-queue model inspired by pi's steeringQueue + followUpQueue.
        # * steer:    messages injected mid-turn (drained before the next
        #             LLM call while a turn is running).
        # * followup: messages queued for processing after the current
        #             turn completes.
        self._steer_queues: dict[str, asyncio.Queue[str]] = {}
        self._followup_queues: dict[str, asyncio.Queue[str]] = {}
        # P2 wiring: optional coalesced-wakeup drain worker for follow-up
        # messages. Opt-in (``enable_followup_drain=True``) and must be
        # started explicitly via :meth:`start_followup_drain`; it is *not*
        # auto-started in ``__init__`` so existing callers see no behavior
        # change.
        self._enable_followup_drain = bool(enable_followup_drain)
        # Lazy import to avoid a hard dependency when the helper module
        # hasn't been vendored yet (keep RunManager importable in isolation).
        try:
            from .coalesced_wakeup import CoalescedWakeupHelper

            self._coalesced_wakeup = CoalescedWakeupHelper()
        except Exception:  # noqa: BLE001 - optional dependency
            self._coalesced_wakeup = None
        self._drain_worker_task: asyncio.Task[None] | None = None
        # Optional callback the runtime wires up to actually start a new
        # turn when a followup arrives. Signature:
        # ``async (thread_id: str, message: str) -> None``.
        self._followup_handler: Callable[[str, str], Awaitable[None]] | None = None

    @staticmethod
    def _get_or_create_queue(
        thread_id: str,
        queues_dict: dict[str, asyncio.Queue[str]],
    ) -> asyncio.Queue[str]:
        """Return the queue for ``thread_id``, creating it if necessary.

        Queues live in a plain dict; we rely on the RunManager's
        ``_lock`` for any operation that needs to read/modify the dict
        atomically, but the queues themselves are safe for ``put_nowait``
        / ``get_nowait`` across tasks because ``asyncio.Queue`` is
        task-safe.
        """
        queue = queues_dict.get(thread_id)
        if queue is None:
            queue = asyncio.Queue()
            queues_dict[thread_id] = queue
        return queue

    async def steer(self, thread_id: str, message: str) -> None:
        """Enqueue a steering message for ``thread_id``.

        Steering messages are injected into the *current* turn: they
        will be picked up by the driver loop before its next LLM call
        (typically via :meth:`drain_steer_queue`).  If no turn is
        running the message will simply wait in the queue until the
        next turn starts (or until explicitly drained).
        """
        if not isinstance(message, str):
            raise TypeError(f"steer message must be str, got {type(message).__name__}")
        # put_nowait is safe because asyncio.Queue has no maxsize by default;
        # we still take the lock briefly to ensure the queue exists.
        async with self._lock:
            queue = self._get_or_create_queue(thread_id, self._steer_queues)
        queue.put_nowait(message)
        logger.debug("Steer message queued for thread %s (depth=%d)", thread_id, queue.qsize())

    async def follow_up(self, thread_id: str, message: str) -> None:
        """Enqueue a follow-up message for ``thread_id``.

        Follow-ups are processed *after* the current turn completes. When
        the coalesced-wakeup drain worker is running (started via
        :meth:`start_followup_drain`), enqueuing a message also signals
        the worker so it drains pending followups promptly.
        """
        if not isinstance(message, str):
            raise TypeError(f"follow_up message must be str, got {type(message).__name__}")
        async with self._lock:
            queue = self._get_or_create_queue(thread_id, self._followup_queues)
        queue.put_nowait(message)
        # Signal the drain worker if available. wake() is synchronous and
        # coalesces multiple rapid signals into one pass.
        if self._coalesced_wakeup is not None:
            self._coalesced_wakeup.wake()
        logger.debug(
            "Follow-up message queued for thread %s (depth=%d)",
            thread_id,
            queue.qsize(),
        )

    async def drain_steer_queue(self, thread_id: str) -> list[str]:
        """Atomically drain and return all steering messages for ``thread_id``.

        Returns a (possibly empty) list in FIFO order.
        """
        async with self._lock:
            queue = self._steer_queues.get(thread_id)
            if queue is None:
                return []
            return _drain_queue_nowait(queue)

    def drain_steer_queue_nowait(self, thread_id: str) -> list[str]:
        """Synchronously perform a best-effort drain of the steer queue."""
        queue = self._steer_queues.get(thread_id)
        if queue is None:
            return []
        return _drain_queue_nowait(queue)

    async def drain_followup_queue(self, thread_id: str) -> list[str]:
        """Atomically drain and return all follow-up messages for ``thread_id``.

        Returns a (possibly empty) list in FIFO order.
        """
        async with self._lock:
            queue = self._followup_queues.get(thread_id)
            if queue is None:
                return []
            return _drain_queue_nowait(queue)

    def drain_followup_queue_nowait(self, thread_id: str) -> list[str]:
        """Synchronously perform a best-effort drain of the follow-up queue."""
        queue = self._followup_queues.get(thread_id)
        if queue is None:
            return []
        return _drain_queue_nowait(queue)

    def queue_depth(self, thread_id: str) -> dict[str, int]:
        """Return pending steering and follow-up message counts."""
        steer = self._steer_queues.get(thread_id)
        followup = self._followup_queues.get(thread_id)
        return {
            "steer": steer.qsize() if steer is not None else 0,
            "followup": followup.qsize() if followup is not None else 0,
        }

    def wake(self) -> None:
        """Signal the drain worker that new follow-up work is available."""
        if self._coalesced_wakeup is not None:
            self._coalesced_wakeup.wake()

    def set_followup_handler(
        self,
        handler: Callable[[str, str], Awaitable[None]] | None,
    ) -> None:
        """Register the callback invoked per follow-up message."""
        self._followup_handler = handler

    def start_followup_drain(self) -> bool:
        """Start the background follow-up drain worker."""
        if self._coalesced_wakeup is None:
            return False
        if self._drain_worker_task is not None and not self._drain_worker_task.done():
            return False
        self._drain_worker_task = asyncio.create_task(
            self._drain_worker_loop(),
            name="focus-runmanager-followup-drain",
        )
        return True

    async def stop_followup_drain(self) -> None:
        """Cancel and await the background follow-up drain worker if running."""
        task = self._drain_worker_task
        if task is None or task.done():
            self._drain_worker_task = None
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        self._drain_worker_task = None

    async def _drain_worker_loop(self) -> None:
        """Drain follow-up queues using coalesced wakeups."""
        if self._coalesced_wakeup is None:
            return
        logger.info("RunManager follow-up drain worker started")
        try:
            while True:
                await self._coalesced_wakeup.execute_with_coalescing(self._process_all_followups)
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            logger.info("RunManager follow-up drain worker cancelled")
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("RunManager follow-up drain worker crashed")

    async def _process_all_followups(self) -> None:
        """Drain and dispatch pending follow-ups across all threads."""
        handler = self._followup_handler
        if handler is None:
            return
        # Snapshot keys under the lock so we don't race queue creation.
        async with self._lock:
            thread_ids = list(self._followup_queues.keys())
        for thread_id in thread_ids:
            messages = await self.drain_followup_queue(thread_id)
            for message in messages:
                try:
                    await handler(thread_id, message)
                except Exception:  # noqa: BLE001 - isolate bad messages
                    logger.warning(
                        "Followup handler failed for thread %s (msg_len=%d)",
                        thread_id,
                        len(message),
                        exc_info=True,
                    )


def _drain_queue_nowait(queue: asyncio.Queue[str]) -> list[str]:
    """Drain all items currently in ``queue`` without awaiting."""
    drained: list[str] = []
    while not queue.empty():
        try:
            drained.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return drained


__all__ = ["RunFollowupsMixin"]
