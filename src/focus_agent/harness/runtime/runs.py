from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Any, Awaitable, Callable, Literal, Protocol
import uuid

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("focus_agent.harness.runtime")


class RunStatus(str, Enum):
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


class DisconnectMode(str, Enum):
    """Behavior when a stream consumer disconnects."""

    CANCEL = "cancel"
    CONTINUE = "continue"
    cancel = "cancel"
    continue_ = "continue"
    ROLLBACK = "rollback"


class MultitaskStrategy(str, Enum):
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
    error: str | None = None

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
        }


class RunManager:
    """In-memory run registry with optional best-effort persistence."""

    def __init__(
        self,
        store: RunStore | None = None,
        *,
        rollback_handler: RollbackHandler | None = None,
    ) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = asyncio.Lock()
        self._store = store
        self._rollback_handler = rollback_handler

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

        await self._settle_records(interrupted)
        await self._persist_created(record)
        for run in interrupted:
            await self._persist_status(run)
        await self._rollback_records(interrupted)
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
        if wait or action == "rollback":
            await self._settle_records([record])
        if action == "rollback":
            await self._rollback_records([record])
        logger.info("Harness run %s cancelled (action=%s)", run_id, action)
        return True

    async def cleanup(self, run_id: str, *, delay: float = 300.0) -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        async with self._lock:
            self._runs.pop(run_id, None)
        logger.debug("Harness run record %s cleaned up", run_id)

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
        if record.task is not None and not record.task.done():
            record.task.cancel()
        record.status = RunStatus.INTERRUPTED
        record.updated_at = _now_iso()

    async def _settle_records(self, records: Sequence[RunRecord]) -> None:
        tasks = [record.task for record in records if record.task is not None]
        if not tasks:
            return
        await asyncio.gather(*(asyncio.shield(task) for task in tasks), return_exceptions=True)

    async def _rollback_records(self, records: Sequence[RunRecord]) -> None:
        if self._rollback_handler is None:
            return
        for record in records:
            if record.abort_action != "rollback":
                continue
            try:
                await self._rollback_handler(record)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to rollback harness run %s",
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
    return datetime.now(timezone.utc).isoformat()


def _coerce_run_status(value: RunStatus | str) -> RunStatus:
    return value if isinstance(value, RunStatus) else RunStatus(value)


def _coerce_disconnect_mode(value: DisconnectMode | str) -> DisconnectMode:
    return value if isinstance(value, DisconnectMode) else DisconnectMode(value)


def _coerce_multitask_strategy(value: MultitaskStrategy | str) -> MultitaskStrategy:
    return value if isinstance(value, MultitaskStrategy) else MultitaskStrategy(value)


__all__ = [
    "ConflictError",
    "DisconnectMode",
    "MultitaskStrategy",
    "RunConflictError",
    "RunCancelAction",
    "RunManager",
    "RunRecord",
    "RunRequest",
    "RunStatus",
    "RunStore",
    "HarnessRunStore",
    "UnsupportedStrategyError",
]
