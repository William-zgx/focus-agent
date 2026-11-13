from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ...core.time_utils import utc_now_iso
from .recovery import (
    HARNESS_RUN_API_LEASE_TTL_SECONDS,
    RunRecoveryMixin,
    is_replay_safe_external_outcome,
)
from .rollback import CheckpointRollbackResult
from .run_followups import RunFollowupsMixin

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
    RECONCILIATION_REQUIRED = "reconciliation_required"


REPLAYABLE_RUN_STATUSES = frozenset({RunStatus.PENDING, RunStatus.RUNNING})
EXECUTION_TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.SUCCESS,
        RunStatus.ERROR,
        RunStatus.TIMEOUT,
        RunStatus.INTERRUPTED,
    }
)
STREAM_TERMINAL_RUN_STATUSES = EXECUTION_TERMINAL_RUN_STATUSES | {RunStatus.RECONCILIATION_REQUIRED}


def is_replay_safe_run_status(value: RunStatus | str | None) -> bool:
    """Return whether the status permits replay; external outcomes are gated separately."""
    try:
        return _coerce_run_status(value) in REPLAYABLE_RUN_STATUSES
    except (TypeError, ValueError):
        return False


def is_execution_terminal_run_status(value: RunStatus | str | None) -> bool:
    try:
        return _coerce_run_status(value) in EXECUTION_TERMINAL_RUN_STATUSES
    except (TypeError, ValueError):
        return False


def is_stream_terminal_run_status(value: RunStatus | str | None) -> bool:
    try:
        return _coerce_run_status(value) in STREAM_TERMINAL_RUN_STATUSES
    except (TypeError, ValueError):
        return False


class DisconnectMode(StrEnum):
    """Behavior when a stream consumer disconnects."""

    CANCEL = "cancel"
    CONTINUE = "continue"
    ROLLBACK = "rollback"


class MultitaskStrategy(StrEnum):
    """Concurrency policy for creating runs on a thread."""

    REJECT = "reject"
    INTERRUPT = "interrupt"
    ROLLBACK = "rollback"
    ENQUEUE = "enqueue"


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
    heartbeat_task: asyncio.Task[None] | None = field(default=None, repr=False)
    abort_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    abort_action: RunCancelAction = "interrupt"
    rollback_ready: asyncio.Event = field(default_factory=_completed_event, repr=False)
    rollback_completed: asyncio.Event = field(default_factory=_completed_event, repr=False)
    error: str | None = None
    rollback_result: dict[str, Any] | None = None

    @property
    def inflight(self) -> bool:
        return self.status in REPLAYABLE_RUN_STATUSES

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


class RunManager(RunFollowupsMixin, RunRecoveryMixin):
    """In-memory run registry with optional best-effort persistence."""

    def __init__(
        self,
        store: RunStore | None = None,
        *,
        rollback_handler: RollbackHandler | None = None,
        lifecycle_publisher: RunLifecyclePublisher | None = None,
        enable_followup_drain: bool = False,
    ) -> None:
        self._loop = self._get_event_loop()
        self._runs: dict[str, RunRecord] = {}
        self._lock = asyncio.Lock()
        self._store = store
        self._rollback_handler = rollback_handler
        self._lifecycle_publisher = lifecycle_publisher
        self._heartbeat_ttl_seconds = max(
            float(
                getattr(
                    store,
                    "harness_run_lease_ttl_seconds",
                    HARNESS_RUN_API_LEASE_TTL_SECONDS,
                )
            ),
            0.001,
        )
        self._heartbeat_interval_seconds = max(
            float(
                getattr(
                    store,
                    "harness_run_heartbeat_interval_seconds",
                    min(60.0, self._heartbeat_ttl_seconds / 3.0),
                )
            ),
            0.001,
        )
        self._initialize_followup_runtime(enable_followup_drain=enable_followup_drain)

    @staticmethod
    def _get_event_loop() -> asyncio.AbstractEventLoop | None:
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

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
        self._start_run_heartbeat(record)
        logger.info("Harness run created: run_id=%s thread_id=%s", record.run_id, thread_id)
        return record

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
                raise RunConflictError(f"Thread {thread_id} already has an active run")
            if strategy in {MultitaskStrategy.INTERRUPT, MultitaskStrategy.ROLLBACK}:
                for run in inflight:
                    self._cancel_record(run, action=strategy.value)
                    interrupted.append(run)
            self._runs[record.run_id] = record

        for run in interrupted:
            await self._stop_run_heartbeat(run)
            await self._publish_lifecycle(
                run,
                "run.interrupt",
                {"action": run.abort_action},
            )
        await self._rollback_records([run for run in interrupted if run.abort_action == "rollback"])
        await self._settle_records(interrupted)
        await self._persist_created(record)
        self._start_run_heartbeat(record)
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
            record.updated_at = utc_now_iso()
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

    async def set_status(
        self,
        run_id: str,
        status: RunStatus | str,
        *,
        error: str | None = None,
    ) -> None:
        running_loop = asyncio.get_running_loop()
        manager_loop = self._loop
        if (
            manager_loop is not None
            and manager_loop is not running_loop
            and manager_loop.is_running()
        ):
            future = asyncio.run_coroutine_threadsafe(
                self.set_status(run_id, status, error=error),
                manager_loop,
            )
            await asyncio.wrap_future(future)
            return
        if manager_loop is None:
            self._loop = running_loop

        async with self._lock:
            record = self._runs.get(run_id)
            if record is None:
                logger.warning("set_status called for unknown harness run %s", run_id)
                return
            new_status = _coerce_run_status(status)
            if is_stream_terminal_run_status(record.status) and record.status != new_status:
                reconciled_replay = (
                    record.status == RunStatus.RECONCILIATION_REQUIRED
                    and is_replay_safe_run_status(new_status)
                    and is_replay_safe_external_outcome(record.metadata.get("external_outcome"))
                )
                if not reconciled_replay:
                    logger.warning(
                        "Ignoring harness run %s transition from terminal %s to %s",
                        run_id,
                        record.status.value,
                        new_status.value,
                    )
                    return
                if error is None:
                    record.error = None
            record.status = new_status
            record.updated_at = utc_now_iso()
            if error is not None:
                record.error = error
            heartbeat_task = None if record.inflight else self._cancel_run_heartbeat(record)
        await self._await_run_heartbeat(heartbeat_task)
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
        await self._stop_run_heartbeat(record)
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
            await self._stop_run_heartbeat(record)
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
            record = self._runs.pop(run_id, None)
        if record is not None:
            await self._stop_run_heartbeat(record)
        logger.debug("Harness run record %s cleaned up", run_id)

    async def close(self) -> None:
        """Stop API lease heartbeats without cancelling execution tasks."""
        async with self._lock:
            records = list(self._runs.values())
        await asyncio.gather(
            *(self._stop_run_heartbeat(record) for record in records),
            return_exceptions=True,
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
        now = utc_now_iso()
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
        record.updated_at = utc_now_iso()

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
        record.updated_at = utc_now_iso()
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


class RunConflictError(Exception):
    """Raised when a thread already has an active run and strategy is reject."""


class UnsupportedStrategyError(Exception):
    """Raised when a multitask strategy is known but not implemented."""


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


__all__ = [
    "EXECUTION_TERMINAL_RUN_STATUSES",
    "REPLAYABLE_RUN_STATUSES",
    "STREAM_TERMINAL_RUN_STATUSES",
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
    "UnsupportedStrategyError",
    "is_execution_terminal_run_status",
    "is_replay_safe_run_status",
    "is_stream_terminal_run_status",
]
