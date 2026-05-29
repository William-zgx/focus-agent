from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..streaming import StreamEvent
from .run_journal_helpers import (
    TOOL_EVENT_NAMES,
    _copy_json,
    _dict_data,
    _event_id,
    _limit,
    _next_sequence,
    _now_iso,
    _replace_run,
    _snapshot,
    _tool_event_from_journal_event,
    _trajectory_summary,
    trajectory_summary_from_snapshot,
)


@dataclass(frozen=True, slots=True)
class JournalRun:
    run_id: str
    thread_id: str
    assistant_id: str | None = None
    user_id: str | None = None
    status: str = "pending"
    on_disconnect: str = "cancel"
    multitask_strategy: str = "reject"
    metadata: dict[str, Any] = field(default_factory=dict)
    kwargs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""
    completion: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "thread_id": self.thread_id,
            "assistant_id": self.assistant_id,
            "user_id": self.user_id,
            "status": self.status,
            "on_disconnect": self.on_disconnect,
            "multitask_strategy": self.multitask_strategy,
            "metadata": _copy_json(self.metadata),
            "kwargs": _copy_json(self.kwargs),
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completion": _copy_json(self.completion),
        }


@dataclass(frozen=True, slots=True)
class JournalEvent:
    event_id: str
    run_id: str
    event: str
    data: dict[str, Any]
    sequence: int
    stream_event_id: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event": self.event,
            "data": _copy_json(self.data),
            "sequence": self.sequence,
            "stream_event_id": self.stream_event_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class JournalToolEvent:
    event_id: str
    run_id: str
    tool_call_id: str | None
    tool_name: str | None
    status: str
    sequence: int
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "status": self.status,
            "sequence": self.sequence,
            "args": _copy_json(self.args),
            "result": _copy_json(self.result),
            "error": self.error,
            "duration_ms": self.duration_ms,
            "metadata": _copy_json(self.metadata),
            "created_at": self.created_at,
        }


class RunJournal(Protocol):
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
    ) -> None: ...

    async def update_status(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
    ) -> None: ...

    async def update_run_completion(self, run_id: str, **kwargs: Any) -> None: ...

    async def append_event(
        self,
        run_id: str,
        event: str,
        data: dict[str, Any] | None = None,
        *,
        event_id: str | None = None,
        stream_event_id: str | None = None,
        sequence: int | None = None,
        created_at: str | None = None,
    ) -> JournalEvent: ...

    async def append_stream_event(self, run_id: str, event: StreamEvent) -> JournalEvent: ...

    async def list_events(
        self,
        run_id: str,
        *,
        event: str | None = None,
        limit: int | None = None,
    ) -> list[JournalEvent]: ...

    async def count_events(self, run_id: str, *, event: str | None = None) -> int: ...

    async def snapshot(self, run_id: str) -> dict[str, Any]: ...

class InMemoryRunJournal:
    """Small reusable harness run journal suitable for tests and single-process runs."""

    def __init__(self) -> None:
        self._runs: dict[str, JournalRun] = {}
        self._events: dict[str, list[JournalEvent]] = {}
        self._tool_events: dict[str, list[JournalToolEvent]] = {}
        self._lock = asyncio.Lock()

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
        now = created_at or _now_iso()
        async with self._lock:
            existing = self._runs.get(run_id)
            self._runs[run_id] = JournalRun(
                run_id=run_id,
                thread_id=thread_id,
                assistant_id=assistant_id,
                user_id=user_id,
                status=status,
                on_disconnect=on_disconnect,
                multitask_strategy=multitask_strategy,
                metadata=_copy_json(metadata or {}),
                kwargs=_copy_json(kwargs or {}),
                error=error,
                created_at=existing.created_at if existing else now,
                updated_at=now,
                completion=existing.completion if existing else {},
            )

    async def update_status(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
    ) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            self._runs[run_id] = _replace_run(
                run,
                status=status,
                error=error if error is not None else run.error,
                updated_at=_now_iso(),
            )

    async def update_run_completion(self, run_id: str, **kwargs: Any) -> None:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return
            completion = dict(run.completion)
            completion.update(_copy_json(kwargs))
            self._runs[run_id] = _replace_run(
                run,
                completion=completion,
                updated_at=_now_iso(),
            )

    async def get_run(self, run_id: str) -> JournalRun | None:
        async with self._lock:
            return self._runs.get(run_id)

    async def list_runs(self, *, thread_id: str | None = None) -> list[JournalRun]:
        async with self._lock:
            return [
                run
                for run in self._runs.values()
                if thread_id is None or run.thread_id == thread_id
            ]

    async def append_event(
        self,
        run_id: str,
        event: str,
        data: dict[str, Any] | None = None,
        *,
        event_id: str | None = None,
        stream_event_id: str | None = None,
        sequence: int | None = None,
        created_at: str | None = None,
    ) -> JournalEvent:
        payload = _copy_json(data or {})
        async with self._lock:
            entry = JournalEvent(
                event_id=event_id or _event_id(),
                run_id=run_id,
                event=event,
                data=payload,
                sequence=sequence
                if sequence is not None
                else _next_sequence(self._events.get(run_id, [])),
                stream_event_id=stream_event_id,
                created_at=created_at or _now_iso(),
            )
            self._events.setdefault(run_id, []).append(entry)
            tool_event = _tool_event_from_journal_event(entry)
            if tool_event is not None:
                self._tool_events.setdefault(run_id, []).append(tool_event)
            return entry

    async def append_stream_event(self, run_id: str, event: StreamEvent) -> JournalEvent:
        return await self.append_event(
            run_id,
            event.event,
            _dict_data(event.data),
            stream_event_id=event.id,
        )

    async def list_events(
        self,
        run_id: str,
        *,
        event: str | None = None,
        limit: int | None = None,
    ) -> list[JournalEvent]:
        async with self._lock:
            events = [
                entry
                for entry in self._events.get(run_id, [])
                if event is None or entry.event == event
            ]
        return _limit(events, limit)

    async def count_events(self, run_id: str, *, event: str | None = None) -> int:
        return len(await self.list_events(run_id, event=event))

    async def list_tool_events(
        self,
        run_id: str,
        *,
        tool_name: str | None = None,
        limit: int | None = None,
    ) -> list[JournalToolEvent]:
        async with self._lock:
            events = [
                entry
                for entry in self._tool_events.get(run_id, [])
                if tool_name is None or entry.tool_name == tool_name
            ]
        return _limit(events, limit)

    async def count_tool_events(self, run_id: str, *, tool_name: str | None = None) -> int:
        return len(await self.list_tool_events(run_id, tool_name=tool_name))

    async def snapshot(self, run_id: str) -> dict[str, Any]:
        async with self._lock:
            run = self._runs.get(run_id)
            events = list(self._events.get(run_id, []))
            tool_events = list(self._tool_events.get(run_id, []))
        return _snapshot(run, events, tool_events)

    async def trajectory_summary(self, run_id: str) -> dict[str, Any]:
        return _trajectory_summary(await self.snapshot(run_id))


from .run_journal_bridge import JournaledStreamBridge as JournaledStreamBridge  # noqa: E402
from .sqlite_run_journal import SQLiteRunJournal as SQLiteRunJournal  # noqa: E402

__all__ = [
    "InMemoryRunJournal",
    "JournalEvent",
    "JournalRun",
    "JournalToolEvent",
    "JournaledStreamBridge",
    "RunJournal",
    "SQLiteRunJournal",
    "TOOL_EVENT_NAMES",
    "trajectory_summary_from_snapshot",
]
