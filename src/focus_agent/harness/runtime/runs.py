from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .rollback import CheckpointRollbackResult

logger = logging.getLogger("focus_agent.harness.runtime")
_ROLLBACK_READY_WAIT_SECONDS = 10.0


def _completed_event() -> asyncio.Event:
    event = asyncio.Event()
    event.set()
    return event


class RunStatus(StrEnum):
    """Lifecycle status for a harness run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    INTERRUPTED = "interrupted"
    pending = "pending"
    running = "running"
    success = "success"
    error = "error"
    timeout = "timeout"
    interrupted = "interrupted"


class DisconnectMode(StrEnum):
    """Behavior when a stream consumer disconnects."""

    CANCEL = "cancel"
    CONTINUE = "continue"
    cancel = "cancel"
    continue_ = "continue"
    ROLLBACK = "rollback"


class MultitaskStrategy(StrEnum):
    """Concurrency policy for creating runs on a thread."""

    REJECT = "reject"
    INTERRUPT = "interrupt"
    ROLLBACK = "rollback"
    ENQUEUE = "enqueue"
    reject = "reject"
    interrupt = "interrupt"
    rollback = "rollback"
    enqueue = "enqueue"


RunCancelAction = Literal["interrupt", "rollback"]
RollbackHandler = Callable[["RunRecord"], Awaitable[Any]]
RunLifecyclePublisher = Callable[["RunRecord", str, dict[str, Any]], Awaitable[None]]


class RunRequest(BaseModel):
    """Portable request payload for creating a harness run."""

    model_config = ConfigDict(extra="forbid")

    assistant_id: str | None = None
    input: dict[str, Any] | None = None
    command: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    checkpoint_id: str | None = None
    checkpoint: dict[str, Any] | None = None
    interrupt_before: list[str] | Literal["*"] | None = None
    interrupt_after: list[str] | Literal["*"] | None = None
    stream_mode: list[str] | str | None = None
    stream_subgraphs: bool = False
    on_disconnect: DisconnectMode = DisconnectMode.CANCEL
    on_completion: Literal["delete", "keep"] = "keep"
    multitask_strategy: MultitaskStrategy = MultitaskStrategy.REJECT
    after_seconds: float | None = Field(default=None, ge=0.0)
    user_id: str | None = None

    def normalized_stream_modes(self, default: Sequence[str] | None = None) -> list[str]:
        if self.stream_mode is None:
            return list(default or ("messages", "custom", "updates", "tasks"))
        if isinstance(self.stream_mode, str):
            return [self.stream_mode]
        return list(self.stream_mode)

    def run_kwargs(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "command": self.command,
            "config": self.config,
            "context": self.context,
            "checkpoint_id": self.checkpoint_id,
            "checkpoint": self.checkpoint,
            "interrupt_before": self.interrupt_before,
            "interrupt_after": self.interrupt_after,
            "stream_mode": self.stream_mode,
            "stream_subgraphs": self.stream_subgraphs,
            "on_completion": self.on_completion,
        }


class RunStore(Protocol):
    async def put(
        self,
        run_id: str,
        *,
        thread_id: str,
        assistant_id: str | None = None,
        user_id: str | None = None,
        status: str = "pending",
        on_disconnect: str = "cancel",
        multitask_strategy: str = "reject",
        metadata: dict[str, Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        error: str | None = None,
        created_at: str | None = None,
    ) -> None:
        """Persist a newly created run record."""

    async def update_status(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
    ) -> None:
        """Persist a run status transition."""

    async def update_run_completion(self, run_id: str, **kwargs: Any) -> None:
        """Persist completion metadata such as token usage."""


HarnessRunStore = RunStore


@dataclass(slots=True)
class RunRecord:
    """Mutable in-process record for a single harness run."""

    run_id: str
    thread_id: str
    assistant_id: str | None
    status: RunStatus
    on_disconnect: DisconnectMode
    multitask_strategy: MultitaskStrategy = MultitaskStrategy.REJECT
    metadata: dict[str, Any] = field(default_factory=dict)
    kwargs: dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None
    rollback_target: Any | None = field(default=None, repr=False)
    created_at: str = ""
    updated_at: str = ""
    task: asyncio.Task[Any] | None = field(default=None, repr=False)
    abort_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    abort_action: RunCancelAction = "interrupt"
    rollback_ready: asyncio.Event = field(default_factory=_completed_event, repr=False)
    rollback_completed: asyncio.Event = field(default_factory=_completed_event, repr=False)
    error: str | None = None
    rollback_result: dict[str, Any] | None = None

    @property
    def inflight(self) -> bool:
        return self.status in {RunStatus.PENDING, RunStatus.RUNNING}

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "assistant_id": self.assistant_id,
            "status": self.status.value,
            "on_disconnect": self.on_disconnect.value,
            "multitask_strategy": self.multitask_strategy.value,
            "metadata": dict(self.metadata),
            "kwargs": dict(self.kwargs),
            "user_id": self.user_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "rollback_result": self.rollback_result,
        }


class RunManager:
    """In-memory run registry with optional best-effort persistence."""

    def __init__(
        self,
        store: RunStore | None = None,
        *,
        rollback_handler: RollbackHandler | None = None,
        lifecycle_publisher: RunLifecyclePublisher | None = None,
        enable_followup_drain: bool = False,
    ) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = asyncio.Lock()
        self._store = store
        self._rollback_handler = rollback_handler
        self._lifecycle_publisher = lifecycle_publisher
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

            self._coalesced_wakeup: CoalescedWakeupHelper | None = CoalescedWakeupHelper()
        except Exception:  # noqa: BLE001 - optional dependency
            self._coalesced_wakeup = None
        self._drain_worker_task: asyncio.Task[None] | None = None
        # Optional callback the runtime wires up to actually start a new
        # turn when a followup arrives. Signature:
        # ``async (thread_id: str, message: str) -> None``.
        self._followup_handler: Callable[[str, str], Awaitable[None]] | None = None

    async def create(
        self,
        thread_id: str,
        assistant_id: str | None = None,
        *,
        on_disconnect: DisconnectMode | str = DisconnectMode.CANCEL,
        metadata: dict[str, Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        multitask_strategy: MultitaskStrategy | str = MultitaskStrategy.REJECT,
        user_id: str | None = None,
        rollback_target: Any | None = None,
    ) -> RunRecord:
        record = self._new_record(
            thread_id=thread_id,
            assistant_id=assistant_id,
            on_disconnect=on_disconnect,
            metadata=metadata,
            kwargs=kwargs,
            multitask_strategy=multitask_strategy,
            user_id=user_id,
            rollback_target=rollback_target,
        )
        async with self._lock:
            self._runs[record.run_id] = record
        await self._persist_created(record)
        logger.info("Harness run created: run_id=%s thread_id=%s", record.run_id, thread_id)
        return record

    async def create_from_request(
        self,
        thread_id: str,
        request: RunRequest,
        *,
        multitask_strategy: MultitaskStrategy | str | None = None,
    ) -> RunRecord:
        return await self.create_or_reject(
            thread_id,
            request.assistant_id,
            on_disconnect=request.on_disconnect,
            metadata=request.metadata,
            kwargs=request.run_kwargs(),
            multitask_strategy=multitask_strategy or request.multitask_strategy,
            user_id=request.user_id,
            rollback_target=None,
        )

    async def create_or_reject(
        self,
        thread_id: str,
        assistant_id: str | None = None,
        *,
        on_disconnect: DisconnectMode | str = DisconnectMode.CANCEL,
        metadata: dict[str, Any] | None = None,
        kwargs: dict[str, Any] | None = None,
        multitask_strategy: MultitaskStrategy | str = MultitaskStrategy.REJECT,
        user_id: str | None = None,
        rollback_target: Any | None = None,
    ) -> RunRecord:
        strategy = _coerce_multitask_strategy(multitask_strategy)
        if strategy == MultitaskStrategy.ENQUEUE:
            raise UnsupportedStrategyError("Multitask strategy 'enqueue' is not supported yet.")

        record = self._new_record(
            thread_id=thread_id,
            assistant_id=assistant_id,
            on_disconnect=on_disconnect,
            metadata=metadata,
            kwargs=kwargs,
            multitask_strategy=strategy,
            user_id=user_id,
            rollback_target=rollback_target,
        )
        interrupted: list[RunRecord] = []
        async with self._lock:
            inflight = [
                run
                for run in self._runs.values()
                if run.thread_id == thread_id
                and run.inflight
                and (user_id is None or run.user_id == user_id)
            ]
            if strategy == MultitaskStrategy.REJECT and inflight:
                raise ConflictError(f"Thread {thread_id} already has an active run")
            if strategy in {MultitaskStrategy.INTERRUPT, MultitaskStrategy.ROLLBACK}:
                for run in inflight:
                    self._cancel_record(run, action=strategy.value)
                    interrupted.append(run)
            self._runs[record.run_id] = record

        for run in interrupted:
            await self._publish_lifecycle(
                run,
                "run.interrupt",
                {"action": run.abort_action},
            )
        await self._rollback_records([run for run in interrupted if run.abort_action == "rollback"])
        await self._settle_records(interrupted)
        await self._persist_created(record)
        for run in interrupted:
            await self._persist_status(run)
        logger.info("Harness run created: run_id=%s thread_id=%s", record.run_id, thread_id)
        return record

    def get(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    async def attach_task(self, run_id: str, task: asyncio.Task[Any]) -> bool:
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                return False
            record.task = task
            record.updated_at = _now_iso()
        return True

    async def list_by_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
    ) -> list[RunRecord]:
        async with self._lock:
            return [
                run
                for run in self._runs.values()
                if run.thread_id == thread_id and (user_id is None or run.user_id == user_id)
            ]

    async def has_inflight(self, thread_id: str, *, user_id: str | None = None) -> bool:
        async with self._lock:
            return any(
                run.thread_id == thread_id
                and run.inflight
                and (user_id is None or run.user_id == user_id)
                for run in self._runs.values()
            )

    async def set_status(
        self,
        run_id: str,
        status: RunStatus | str,
        *,
        error: str | None = None,
    ) -> None:
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                logger.warning("set_status called for unknown harness run %s", run_id)
                return
            record.status = _coerce_run_status(status)
            record.updated_at = _now_iso()
            if error is not None:
                record.error = error
        await self._persist_status(record)
        logger.info("Harness run %s -> %s", run_id, record.status.value)

    async def update_run_completion(self, run_id: str, **kwargs: Any) -> None:
        if self._store is None:
            return
        try:
            await self._store.update_run_completion(run_id, **kwargs)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to persist harness run completion for %s", run_id, exc_info=True)

    async def cancel(
        self,
        run_id: str,
        *,
        action: RunCancelAction = "interrupt",
        wait: bool = False,
    ) -> bool:
        async with self._lock:
            record = self._runs.get(run_id)
            if record is None or not record.inflight:
                return False
            self._cancel_record(record, action=action)
        await self._persist_status(record)
        await self._publish_lifecycle(record, "run.interrupt", {"action": record.abort_action})
        if action == "rollback":
            await self._rollback_records([record])
        if wait or action == "rollback":
            await self._settle_records([record])
        logger.info("Harness run %s cancelled (action=%s)", run_id, action)
        return True

    async def cancel_thread(
        self,
        thread_id: str,
        *,
        user_id: str | None = None,
        action: RunCancelAction = "interrupt",
        wait: bool = False,
    ) -> list[str]:
        async with self._lock:
            records = [
                record
                for record in self._runs.values()
                if record.thread_id == thread_id
                and record.inflight
                and (user_id is None or record.user_id == user_id)
            ]
            for record in records:
                self._cancel_record(record, action=action)
        for record in records:
            await self._persist_status(record)
            await self._publish_lifecycle(record, "run.interrupt", {"action": record.abort_action})
        if action == "rollback":
            await self._rollback_records(records)
        if wait or action == "rollback":
            await self._settle_records(records)
        if records:
            logger.info(
                "Harness thread %s cancelled %s active run(s) (action=%s)",
                thread_id,
                len(records),
                action,
            )
        return [record.run_id for record in records]

    async def cleanup(self, run_id: str, *, delay: float = 300.0) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        async with self._lock:
            self._runs.pop(run_id, None)
        logger.debug("Harness run record %s cleaned up", run_id)

    # ------------------------------------------------------------------
    # Dual-queue steering / follow-up support (pi-style queues)
    # ------------------------------------------------------------------

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
        """Synchronous, best-effort drain of the steer queue.

        Does not acquire the async lock (so it is safe to call from
        synchronous graph nodes). Reads the queue reference directly and
        drains pending items via ``get_nowait``. A steer message queued
        concurrently with this call may be missed; it will be picked up
        on the next LLM invocation.
        """
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
        """Synchronous, best-effort drain of the follow-up queue."""
        queue = self._followup_queues.get(thread_id)
        if queue is None:
            return []
        return _drain_queue_nowait(queue)

    def queue_depth(self, thread_id: str) -> dict[str, int]:
        """Return pending message counts for ``thread_id``.

        Returns a dict of the form ``{"steer": N, "followup": M}``.
        Missing queues are reported as depth 0.
        """
        steer = self._steer_queues.get(thread_id)
        followup = self._followup_queues.get(thread_id)
        return {
            "steer": steer.qsize() if steer is not None else 0,
            "followup": followup.qsize() if followup is not None else 0,
        }

    # ------------------------------------------------------------------
    # Coalesced-wakeup followup drain worker (P2 wiring, opt-in)
    # ------------------------------------------------------------------

    def wake(self) -> None:
        """Signal the drain worker that new follow-up work is available.

        Safe to call even if the drain worker is not running (the signal
        is simply recorded on the helper; the next ``execute_with_coalescing``
        caller will pick it up). Synchronous and non-blocking.
        """
        if self._coalesced_wakeup is not None:
            self._coalesced_wakeup.wake()

    def set_followup_handler(
        self,
        handler: Callable[[str, str], Awaitable[None]] | None,
    ) -> None:
        """Register the callback invoked per follow-up message.

        The handler is called as ``await handler(thread_id, message)`` for
        each drained message. It is the runtime's responsibility to wire
        this to a function that starts a new turn on the given thread.
        Pass ``None`` to clear an existing handler.
        """
        self._followup_handler = handler

    def start_followup_drain(self) -> bool:
        """Start the background followup drain worker.

        Returns ``True`` if a worker was started, ``False`` if the helper
        is unavailable (e.g. the ``coalesced_wakeup`` module could not be
        imported) or a worker is already running. The worker runs until
        :meth:`stop_followup_drain` is called or the event loop closes.

        This is opt-in: construction does not start it automatically.
        """
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
        """Cancel and await the background followup drain worker if running."""
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
        """Background worker that drains followup queues using coalesced wakeups.

        The worker waits on :meth:`CoalescedWakeupHelper.execute_with_coalescing`,
        which blocks until :meth:`wake` is called and coalesces multiple
        rapid signals into a single drain pass, guaranteeing no event is
        lost while bounding concurrent invocations.
        """
        if self._coalesced_wakeup is None:
            return
        logger.info("RunManager follow-up drain worker started")
        try:
            while True:
                # execute_with_coalescing runs _process_all_followups and
                # re-runs it if a wake arrived mid-flight, until no wakes
                # are pending. When idle it does NOT block; we yield and
                # wait for the next explicit wake by sleeping briefly to
                # avoid a tight loop.
                await self._coalesced_wakeup.execute_with_coalescing(
                    self._process_all_followups
                )
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            logger.info("RunManager follow-up drain worker cancelled")
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("RunManager follow-up drain worker crashed")

    async def _process_all_followups(self) -> None:
        """Drain and dispatch pending followups across all threads.

        For each thread with queued followups we drain all queued messages
        then invoke ``_followup_handler`` for each one. When no handler is
        registered the messages stay drained (i.e. dropped); callers that
        care about reliability should install a handler before starting
        the drain worker.
        """
        handler = self._followup_handler
        if handler is None:
            return
        # Snapshot keys under the lock so we don't race queue creation.
        async with self._lock:
            thread_ids = list(self._followup_queues.keys())
        for thread_id in thread_ids:
            messages = await self.drain_followup_queue(thread_id)
            for msg in messages:
                try:
                    await handler(thread_id, msg)
                except Exception:  # noqa: BLE001 - never let one bad message kill the worker
                    logger.warning(
                        "Followup handler failed for thread %s (msg_len=%d)",
                        thread_id,
                        len(msg),
                        exc_info=True,
                    )

    def _new_record(
        self,
        *,
        thread_id: str,
        assistant_id: str | None,
        on_disconnect: DisconnectMode | str,
        metadata: dict[str, Any] | None,
        kwargs: dict[str, Any] | None,
        multitask_strategy: MultitaskStrategy | str,
        user_id: str | None,
        rollback_target: Any | None,
    ) -> RunRecord:
        now = _now_iso()
        return RunRecord(
            run_id=str(uuid.uuid4()),
            thread_id=thread_id,
            assistant_id=assistant_id,
            status=RunStatus.PENDING,
            on_disconnect=_coerce_disconnect_mode(on_disconnect),
            multitask_strategy=_coerce_multitask_strategy(multitask_strategy),
            metadata=dict(metadata or {}),
            kwargs=dict(kwargs or {}),
            user_id=user_id,
            rollback_target=rollback_target,
            created_at=now,
            updated_at=now,
        )

    def _cancel_record(self, record: RunRecord, *, action: str) -> None:
        record.abort_action = "rollback" if action == "rollback" else "interrupt"
        record.abort_event.set()
        task_running = record.task is not None and not record.task.done()
        if task_running:
            record.task.cancel()
        if action == "rollback":
            if task_running:
                record.rollback_ready.clear()
            else:
                record.rollback_ready.set()
            record.rollback_completed.clear()
        else:
            record.rollback_ready.set()
            record.rollback_completed.set()
        record.status = RunStatus.INTERRUPTED
        record.updated_at = _now_iso()

    async def _settle_records(self, records: Sequence[RunRecord]) -> None:
        tasks = [record.task for record in records if record.task is not None]
        if not tasks:
            return
        await asyncio.gather(*(asyncio.shield(task) for task in tasks), return_exceptions=True)

    async def _rollback_records(self, records: Sequence[RunRecord]) -> None:
        for record in records:
            if record.abort_action != "rollback":
                record.rollback_ready.set()
                record.rollback_completed.set()
                continue
            record.rollback_completed.clear()
            await self._await_rollback_ready(record)
            await self._publish_lifecycle(record, "run.rollback.started", {})
            if self._rollback_handler is None:
                result = CheckpointRollbackResult(
                    requested=True,
                    applied=False,
                    reason="rollback_handler_unavailable",
                )
                await self._record_rollback_result(record, result)
                await self._publish_lifecycle(
                    record,
                    "run.rollback.failed",
                    {"rollback_result": record.rollback_result},
                )
                record.rollback_completed.set()
                continue
            try:
                result = await self._rollback_handler(record)
                if not isinstance(result, CheckpointRollbackResult):
                    result = CheckpointRollbackResult(
                        requested=True,
                        applied=False,
                        reason="rollback_handler_returned_none",
                    )
                await self._record_rollback_result(record, result)
                event = (
                    "run.rollback.succeeded"
                    if record.rollback_result
                    and record.rollback_result.get("applied") is True
                    and not record.rollback_result.get("error")
                    else "run.rollback.failed"
                )
                await self._publish_lifecycle(
                    record,
                    event,
                    {"rollback_result": record.rollback_result},
                )
            except Exception as exc:  # noqa: BLE001
                result = CheckpointRollbackResult(
                    requested=True,
                    applied=False,
                    reason="rollback_handler_error",
                    error=str(exc),
                )
                await self._record_rollback_result(record, result)
                await self._publish_lifecycle(
                    record,
                    "run.rollback.failed",
                    {"rollback_result": record.rollback_result},
                )
                logger.warning(
                    "Failed to rollback harness run %s",
                    record.run_id,
                    exc_info=True,
                )
            finally:
                record.rollback_completed.set()

    async def _await_rollback_ready(self, record: RunRecord) -> None:
        if record.rollback_ready.is_set():
            return
        try:
            await asyncio.wait_for(
                record.rollback_ready.wait(),
                timeout=_ROLLBACK_READY_WAIT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "Timed out waiting for run %s to reach rollback-safe finalization",
                record.run_id,
            )

    async def _record_rollback_result(
        self,
        record: RunRecord,
        result: CheckpointRollbackResult,
    ) -> None:
        augmented = _augment_rollback_result(result, record.metadata)
        payload = augmented.to_dict()
        record.rollback_result = payload
        record.updated_at = _now_iso()
        await self.update_run_completion(record.run_id, rollback_result=payload)

    async def _publish_lifecycle(
        self,
        record: RunRecord,
        event: str,
        data: dict[str, Any],
    ) -> None:
        if self._lifecycle_publisher is None:
            return
        try:
            await self._lifecycle_publisher(record, event, data)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to publish harness lifecycle event %s for run %s",
                event,
                record.run_id,
                exc_info=True,
            )

    async def _persist_created(self, record: RunRecord) -> None:
        if self._store is None:
            return
        try:
            await self._store.put(
                record.run_id,
                thread_id=record.thread_id,
                assistant_id=record.assistant_id,
                user_id=record.user_id,
                status=record.status.value,
                on_disconnect=record.on_disconnect.value,
                multitask_strategy=record.multitask_strategy.value,
                metadata=record.metadata,
                kwargs=record.kwargs,
                error=record.error,
                created_at=record.created_at,
            )
        except Exception:  # noqa: BLE001
            logger.warning("Failed to persist harness run %s", record.run_id, exc_info=True)

    async def _persist_status(self, record: RunRecord) -> None:
        if self._store is None:
            return
        try:
            await self._store.update_status(record.run_id, record.status.value, error=record.error)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to persist harness run status for %s",
                record.run_id,
                exc_info=True,
            )


class ConflictError(Exception):
    """Raised when a thread already has an active run and strategy is reject."""


RunConflictError = ConflictError


class UnsupportedStrategyError(Exception):
    """Raised when a multitask strategy is known but not implemented."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _coerce_run_status(value: RunStatus | str) -> RunStatus:
    return value if isinstance(value, RunStatus) else RunStatus(value)


def _coerce_disconnect_mode(value: DisconnectMode | str) -> DisconnectMode:
    return value if isinstance(value, DisconnectMode) else DisconnectMode(value)


def _coerce_multitask_strategy(value: MultitaskStrategy | str) -> MultitaskStrategy:
    return value if isinstance(value, MultitaskStrategy) else MultitaskStrategy(value)


def _augment_rollback_result(
    result: CheckpointRollbackResult,
    metadata: dict[str, Any],
) -> CheckpointRollbackResult:
    raw_scopes = metadata.get("harness.rollback_unreverted_scopes", ())
    if isinstance(raw_scopes, str):
        metadata_scopes = (raw_scopes,)
    else:
        try:
            metadata_scopes = tuple(str(scope) for scope in raw_scopes)
        except TypeError:
            metadata_scopes = ()
    scopes = tuple(dict.fromkeys((*result.unreverted_scopes, *metadata_scopes)))
    partial = result.partial or bool(metadata.get("harness.rollback_partial")) or bool(scopes)
    return CheckpointRollbackResult(
        requested=result.requested,
        applied=result.applied,
        reason=result.reason,
        checkpoint_id=result.checkpoint_id,
        error=result.error,
        partial=partial,
        unreverted_scopes=scopes,
    )


def _drain_queue_nowait(queue: asyncio.Queue[str]) -> list[str]:
    """Drain all items currently in *queue* using ``get_nowait``.

    Safe to call from synchronous code because it does not await.
    """
    drained: list[str] = []
    while not queue.empty():
        try:
            drained.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return drained


__all__ = [
    "ConflictError",
    "DisconnectMode",
    "MultitaskStrategy",
    "RunConflictError",
    "RunCancelAction",
    "RunLifecyclePublisher",
    "RunManager",
    "RunRecord",
    "RunRequest",
    "RunStatus",
    "RunStore",
    "HarnessRunStore",
    "UnsupportedStrategyError",
]
