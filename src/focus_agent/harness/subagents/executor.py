from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from ..runtime import RunManager, RunRecord, RunStatus
from ..tools.envelope import ToolResultContent, ToolResultEnvelope

DEFAULT_SUBAGENT_MAX_PARALLEL = 3


@dataclass(frozen=True, slots=True)
class SubagentTaskRequest:
    """Portable request for a harness-owned subagent task."""

    instruction: str
    thread_id: str | None = None
    assistant_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SubagentTaskResult:
    """Portable result returned by a lightweight subagent task runner."""

    content: ToolResultContent = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    artifact: dict[str, Any] = field(default_factory=dict)


class SubagentTaskRunner(Protocol):
    async def run(
        self,
        request: SubagentTaskRequest,
        *,
        run_record: RunRecord,
    ) -> SubagentTaskResult:
        """Execute a subagent task and return portable result data."""


class SubagentExecutor:
    """Bounded subagent task executor that always returns tool envelopes."""

    def __init__(
        self,
        runner: SubagentTaskRunner,
        *,
        max_parallel: int = DEFAULT_SUBAGENT_MAX_PARALLEL,
        run_manager: RunManager | None = None,
    ) -> None:
        if max_parallel <= 0:
            raise ValueError("max_parallel must be positive.")
        self._runner = runner
        self._max_parallel = max_parallel
        self._run_manager = run_manager or RunManager()
        self._lock = asyncio.Lock()
        self._active = 0

    @property
    def max_parallel(self) -> int:
        return self._max_parallel

    @property
    def active_count(self) -> int:
        return self._active

    async def execute(
        self,
        request: SubagentTaskRequest,
        *,
        tool_call_id: str | None = None,
        tool_name: str = "task",
    ) -> ToolResultEnvelope:
        call_id = tool_call_id or f"subagent-call-{uuid.uuid4()}"
        started_at = _now_iso()
        accepted = await self._try_acquire_slot()
        if not accepted:
            return self._error_envelope(
                tool_call_id=call_id,
                tool_name=tool_name,
                content=(
                    "Subagent parallelism limit reached "
                    f"({self._active}/{self._max_parallel} active)."
                ),
                runtime={
                    "executor": "subagent",
                    "status": "rejected",
                    "reason": "parallelism_limit",
                    "max_parallel": self._max_parallel,
                    "active": self._active,
                    "started_at": started_at,
                    "ended_at": _now_iso(),
                },
            )

        record: RunRecord | None = None
        try:
            record = await self._run_manager.create(
                request.thread_id or f"subagent-thread-{uuid.uuid4()}",
                request.assistant_id,
                metadata={
                    "kind": "subagent_task",
                    **dict(request.metadata),
                },
                kwargs={
                    "instruction": request.instruction,
                    "input": dict(request.input),
                },
            )
            await self._run_manager.set_status(record.run_id, RunStatus.RUNNING)
            result = await self._runner.run(request, run_record=record)
            await self._run_manager.set_status(record.run_id, RunStatus.SUCCESS)
            ended_at = _now_iso()
            return ToolResultEnvelope(
                tool_call_id=call_id,
                tool_name=tool_name,
                content=result.content,
                status="success",
                runtime={
                    "executor": "subagent",
                    "status": "success",
                    "run_id": record.run_id,
                    "thread_id": record.thread_id,
                    "assistant_id": record.assistant_id,
                    "max_parallel": self._max_parallel,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    **dict(result.metadata),
                },
                artifact={
                    "run": record.to_dict(),
                    **dict(result.artifact),
                },
            )
        except Exception as exc:  # noqa: BLE001
            if record is not None:
                await self._run_manager.set_status(record.run_id, RunStatus.ERROR, error=str(exc))
            return self._error_envelope(
                tool_call_id=call_id,
                tool_name=tool_name,
                content=f"Subagent task failed: {exc}",
                runtime={
                    "executor": "subagent",
                    "status": "error",
                    "run_id": record.run_id if record is not None else None,
                    "thread_id": record.thread_id if record is not None else request.thread_id,
                    "assistant_id": (
                        record.assistant_id if record is not None else request.assistant_id
                    ),
                    "max_parallel": self._max_parallel,
                    "started_at": started_at,
                    "ended_at": _now_iso(),
                    "error_type": type(exc).__name__,
                },
                artifact={"run": record.to_dict()} if record is not None else {},
            )
        finally:
            await self._release_slot()

    async def _try_acquire_slot(self) -> bool:
        async with self._lock:
            if self._active >= self._max_parallel:
                return False
            self._active += 1
            return True

    async def _release_slot(self) -> None:
        async with self._lock:
            self._active = max(0, self._active - 1)

    def _error_envelope(
        self,
        *,
        tool_call_id: str,
        tool_name: str,
        content: str,
        runtime: Mapping[str, Any],
        artifact: Mapping[str, Any] | None = None,
    ) -> ToolResultEnvelope:
        return ToolResultEnvelope(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            content=content,
            status="error",
            runtime={str(key): value for key, value in runtime.items()},
            artifact={str(key): value for key, value in (artifact or {}).items()},
        )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
