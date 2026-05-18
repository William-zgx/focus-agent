from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, TypeVar

from focus_agent.core.repo_call import has_repo_method
from focus_agent.observability.trajectory import TrajectoryStep
from focus_agent.runtime.thread_pool import shared_thread_pool

from ..streaming import END_SENTINEL, InMemoryStreamBridge, StreamEvent

T = TypeVar("T")


TOOL_EVENT_NAMES = frozenset(
    {
        "tool.call.delta",
        "tool.requested",
        "tool.result",
        "tool.error",
    }
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


class SQLiteRunJournal:
    """SQLite-backed harness run journal.

    The schema intentionally mirrors the logical stores requested by the harness:
    ``runs``, ``run_events``, and ``tool_events``.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(Path(db_path).expanduser())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._setup()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _setup(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    assistant_id TEXT,
                    user_id TEXT,
                    status TEXT NOT NULL,
                    on_disconnect TEXT NOT NULL DEFAULT 'cancel',
                    multitask_strategy TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    kwargs_json TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completion_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    stream_event_id TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    tool_call_id TEXT,
                    tool_name TEXT,
                    status TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    args_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    error TEXT,
                    duration_ms REAL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id, sequence)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tool_events_run ON tool_events(run_id, sequence)"
            )
            conn.commit()

    async def _run_db(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        async with self._lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(shared_thread_pool(), self._run_db_sync, operation)

    def _run_db_sync(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        with self._connect() as conn:
            return operation(conn)

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

        def operation(conn: sqlite3.Connection) -> None:
            existing = conn.execute(
                "SELECT created_at, completion_json FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, thread_id, assistant_id, user_id, status, on_disconnect,
                    multitask_strategy, metadata_json, kwargs_json, error, created_at,
                    updated_at, completion_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    thread_id,
                    assistant_id,
                    user_id,
                    status,
                    on_disconnect,
                    multitask_strategy,
                    _json_dumps(metadata or {}),
                    _json_dumps(kwargs or {}),
                    error,
                    existing["created_at"] if existing else now,
                    now,
                    existing["completion_json"] if existing else "{}",
                ),
            )
            conn.commit()

        await self._run_db(operation)

    async def update_status(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
    ) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            conn.execute(
                """
                UPDATE runs
                SET status = ?, error = COALESCE(?, error), updated_at = ?
                WHERE run_id = ?
                """,
                (status, error, _now_iso(), run_id),
            )
            conn.commit()

        await self._run_db(operation)

    async def update_run_completion(self, run_id: str, **kwargs: Any) -> None:
        def operation(conn: sqlite3.Connection) -> None:
            row = conn.execute(
                "SELECT completion_json FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                return
            completion = _json_loads(row["completion_json"])
            completion.update(_copy_json(kwargs))
            conn.execute(
                "UPDATE runs SET completion_json = ?, updated_at = ? WHERE run_id = ?",
                (_json_dumps(completion), _now_iso(), run_id),
            )
            conn.commit()

        await self._run_db(operation)

    async def get_run(self, run_id: str) -> JournalRun | None:
        row = await self._run_db(
            lambda conn: conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        )
        return _row_to_run(row) if row is not None else None

    async def list_runs(self, *, thread_id: str | None = None) -> list[JournalRun]:
        def operation(conn: sqlite3.Connection) -> list[sqlite3.Row]:
            if thread_id is None:
                return conn.execute("SELECT * FROM runs ORDER BY created_at, run_id").fetchall()
            return conn.execute(
                "SELECT * FROM runs WHERE thread_id = ? ORDER BY created_at, run_id",
                (thread_id,),
            ).fetchall()

        rows = await self._run_db(operation)
        return [_row_to_run(row) for row in rows]

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

        def operation(conn: sqlite3.Connection) -> JournalEvent:
            effective_sequence = sequence
            if effective_sequence is None:
                row = conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM run_events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                effective_sequence = int(row["sequence"])
            entry = JournalEvent(
                event_id=event_id or _event_id(),
                run_id=run_id,
                event=event,
                data=payload,
                sequence=effective_sequence,
                stream_event_id=stream_event_id,
                created_at=created_at or _now_iso(),
            )
            conn.execute(
                """
                INSERT INTO run_events (
                    event_id, run_id, event, data_json, sequence, stream_event_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.event_id,
                    entry.run_id,
                    entry.event,
                    _json_dumps(entry.data),
                    entry.sequence,
                    entry.stream_event_id,
                    entry.created_at,
                ),
            )
            tool_event = _tool_event_from_journal_event(entry)
            if tool_event is not None:
                conn.execute(
                    """
                    INSERT INTO tool_events (
                        event_id, run_id, tool_call_id, tool_name, status, sequence,
                        args_json, result_json, error, duration_ms, metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tool_event.event_id,
                        tool_event.run_id,
                        tool_event.tool_call_id,
                        tool_event.tool_name,
                        tool_event.status,
                        tool_event.sequence,
                        _json_dumps(tool_event.args),
                        _json_dumps(tool_event.result),
                        tool_event.error,
                        tool_event.duration_ms,
                        _json_dumps(tool_event.metadata),
                        tool_event.created_at,
                    ),
                )
            conn.commit()
            return entry

        return await self._run_db(operation)

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
        def operation(conn: sqlite3.Connection) -> list[sqlite3.Row]:
            if event is None:
                return conn.execute(
                    "SELECT * FROM run_events WHERE run_id = ? ORDER BY sequence, created_at",
                    (run_id,),
                ).fetchall()
            return conn.execute(
                """
                SELECT * FROM run_events
                WHERE run_id = ? AND event = ?
                ORDER BY sequence, created_at
                """,
                (run_id, event),
            ).fetchall()

        rows = await self._run_db(operation)
        return _limit([_row_to_event(row) for row in rows], limit)

    async def count_events(self, run_id: str, *, event: str | None = None) -> int:
        def operation(conn: sqlite3.Connection) -> sqlite3.Row:
            if event is None:
                return conn.execute(
                    "SELECT COUNT(*) AS count FROM run_events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            return conn.execute(
                "SELECT COUNT(*) AS count FROM run_events WHERE run_id = ? AND event = ?",
                (run_id, event),
            ).fetchone()

        row = await self._run_db(operation)
        return int(row["count"])

    async def list_tool_events(
        self,
        run_id: str,
        *,
        tool_name: str | None = None,
        limit: int | None = None,
    ) -> list[JournalToolEvent]:
        def operation(conn: sqlite3.Connection) -> list[sqlite3.Row]:
            if tool_name is None:
                return conn.execute(
                    "SELECT * FROM tool_events WHERE run_id = ? ORDER BY sequence, created_at",
                    (run_id,),
                ).fetchall()
            return conn.execute(
                """
                SELECT * FROM tool_events
                WHERE run_id = ? AND tool_name = ?
                ORDER BY sequence, created_at
                """,
                (run_id, tool_name),
            ).fetchall()

        rows = await self._run_db(operation)
        return _limit([_row_to_tool_event(row) for row in rows], limit)

    async def count_tool_events(self, run_id: str, *, tool_name: str | None = None) -> int:
        return len(await self.list_tool_events(run_id, tool_name=tool_name))

    async def snapshot(self, run_id: str) -> dict[str, Any]:
        run = await self.get_run(run_id)
        events = await self.list_events(run_id)
        tool_events = await self.list_tool_events(run_id)
        return _snapshot(run, events, tool_events)

    async def trajectory_summary(self, run_id: str) -> dict[str, Any]:
        return _trajectory_summary(await self.snapshot(run_id))


class JournaledStreamBridge:
    """Bridge wrapper that persists every published stream event into a run journal."""

    def __init__(
        self,
        journal: RunJournal,
        bridge: InMemoryStreamBridge | None = None,
    ) -> None:
        self.journal = journal
        self.bridge = bridge or InMemoryStreamBridge()

    async def publish(self, run_id: str, event: str, data: Any) -> StreamEvent:
        entry = await self.bridge.publish(run_id, event, data)
        await self.journal.append_stream_event(run_id, entry)
        return entry

    async def publish_event(self, run_id: str, event: StreamEvent) -> StreamEvent:
        entry = await self.bridge.publish_event(run_id, event)
        await self.journal.append_stream_event(run_id, entry)
        return entry

    async def publish_end(self, run_id: str) -> None:
        await self.bridge.publish_end(run_id)

    async def subscribe(
        self,
        run_id: str,
        *,
        last_event_id: str | None = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[StreamEvent]:
        yielded_ids: set[str] = set()
        history = await self.journal.list_events(run_id)
        replay_start = _journal_replay_start(history, last_event_id)
        replay_events = history[replay_start:]
        bridge_last_event_id = last_event_id

        for event in replay_events:
            stream_event = _stream_event_from_journal_event(event)
            yielded_ids.add(stream_event.id)
            bridge_last_event_id = stream_event.id
            yield stream_event

        if history and history[-1].event == "run.closed":
            yield END_SENTINEL
            return
        bridge_ended = await _bridge_stream_ended(self.bridge, run_id)
        if await _journal_run_is_terminal(self.journal, run_id) and bridge_ended is not False:
            yield END_SENTINEL
            return

        async for event in self.bridge.subscribe(
            run_id,
            last_event_id=bridge_last_event_id,
            heartbeat_interval=heartbeat_interval,
        ):
            if event is END_SENTINEL:
                yield event
                return
            if event.id and event.id in yielded_ids:
                continue
            if event.id:
                yielded_ids.add(event.id)
            yield event

    def __getattr__(self, name: str) -> Any:
        return getattr(self.bridge, name)


def trajectory_summary_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return _trajectory_summary(snapshot)


def _snapshot(
    run: JournalRun | None,
    events: Iterable[JournalEvent],
    tool_events: Iterable[JournalToolEvent],
) -> dict[str, Any]:
    event_dicts = [event.to_dict() for event in events]
    tool_dicts = [event.to_dict() for event in tool_events]
    return {
        "run": run.to_dict() if run is not None else None,
        "events": event_dicts,
        "tool_events": tool_dicts,
        "counts": {
            "events": len(event_dicts),
            "tool_events": len(tool_dicts),
        },
    }


def _journal_replay_start(events: list[JournalEvent], last_event_id: str | None) -> int:
    if last_event_id is None:
        return 0
    for index, event in enumerate(events):
        if event.stream_event_id == last_event_id or event.event_id == last_event_id:
            return index + 1
    return 0


def _stream_event_from_journal_event(event: JournalEvent) -> StreamEvent:
    return StreamEvent(
        id=event.stream_event_id or event.event_id,
        event=event.event,
        data=event.data,
    )


async def _journal_run_is_terminal(journal: RunJournal, run_id: str) -> bool:
    if not has_repo_method(journal, "get_run"):
        return False
    run = await journal.get_run(run_id)
    if run is None:
        return False
    status = getattr(run, "status", None)
    return str(status) in {"success", "error", "timeout", "interrupted"}


async def _bridge_stream_ended(bridge: InMemoryStreamBridge, run_id: str) -> bool | None:
    if not has_repo_method(bridge, "stream_ended"):
        return None
    return await bridge.stream_ended(run_id)


def _trajectory_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    run = snapshot.get("run") or {}
    tool_events = list(snapshot.get("tool_events") or [])
    steps: list[dict[str, Any]] = []
    for event in tool_events:
        if event.get("status") not in {"result", "error"}:
            continue
        steps.append(
            TrajectoryStep(
                tool=str(event.get("tool_name") or "unknown_tool"),
                args=dict(event.get("args") or {}),
                observation=_observation_text(event),
                duration_ms=float(event.get("duration_ms") or 0.0),
                error=str(event["error"]) if event.get("error") else None,
            ).to_dict()
        )
    return {
        "id": run.get("run_id"),
        "kind": "harness_run",
        "status": run.get("status", "unknown"),
        "thread_id": run.get("thread_id"),
        "trajectory": steps,
        "metrics": {
            "events": (snapshot.get("counts") or {}).get("events", 0),
            "tool_calls": len(steps),
        },
        "error": run.get("error"),
    }


def _tool_event_from_journal_event(event: JournalEvent) -> JournalToolEvent | None:
    if event.event not in TOOL_EVENT_NAMES:
        return None
    data = event.data
    tool_name = _first_str(data, "tool_name", "name", "tool")
    status = _tool_status(event.event)
    return JournalToolEvent(
        event_id=event.event_id,
        run_id=event.run_id,
        tool_call_id=_first_str(data, "tool_call_id", "call_id", "id"),
        tool_name=tool_name,
        status=status,
        sequence=event.sequence,
        args=dict(data.get("args") or data.get("arguments") or {}),
        result=data.get("result") if "result" in data else data.get("observation"),
        error=_first_str(data, "error"),
        duration_ms=_optional_float(data.get("duration_ms")),
        metadata={key: value for key, value in data.items() if key not in _TOOL_PAYLOAD_KEYS},
        created_at=event.created_at,
    )


def _tool_status(event: str) -> str:
    if event == "tool.requested":
        return "requested"
    if event == "tool.error":
        return "error"
    if event == "tool.result":
        return "result"
    return "delta"


def _observation_text(event: dict[str, Any]) -> str:
    if event.get("error"):
        return str(event["error"])
    result = event.get("result")
    if isinstance(result, str):
        return result
    if result is None:
        return ""
    return _json_dumps(result)


def _replace_run(run: JournalRun, **changes: Any) -> JournalRun:
    values = run.to_dict()
    values.update(changes)
    return JournalRun(**values)


def _row_to_run(row: sqlite3.Row) -> JournalRun:
    return JournalRun(
        run_id=row["run_id"],
        thread_id=row["thread_id"],
        assistant_id=row["assistant_id"],
        user_id=row["user_id"],
        status=row["status"],
        on_disconnect=row["on_disconnect"] if "on_disconnect" in row.keys() else "cancel",
        multitask_strategy=row["multitask_strategy"],
        metadata=_json_loads(row["metadata_json"]),
        kwargs=_json_loads(row["kwargs_json"]),
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completion=_json_loads(row["completion_json"]),
    )


def _row_to_event(row: sqlite3.Row) -> JournalEvent:
    return JournalEvent(
        event_id=row["event_id"],
        run_id=row["run_id"],
        event=row["event"],
        data=_json_loads(row["data_json"]),
        sequence=int(row["sequence"]),
        stream_event_id=row["stream_event_id"],
        created_at=row["created_at"],
    )


def _row_to_tool_event(row: sqlite3.Row) -> JournalToolEvent:
    return JournalToolEvent(
        event_id=row["event_id"],
        run_id=row["run_id"],
        tool_call_id=row["tool_call_id"],
        tool_name=row["tool_name"],
        status=row["status"],
        sequence=int(row["sequence"]),
        args=_json_loads(row["args_json"]),
        result=_json_loads_any(row["result_json"]),
        error=row["error"],
        duration_ms=row["duration_ms"],
        metadata=_json_loads(row["metadata_json"]),
        created_at=row["created_at"],
    )


def _limit(items: list[T], limit: int | None) -> list[T]:
    if limit is None:
        return items
    return items[: max(int(limit), 0)]


def _next_sequence(events: list[JournalEvent]) -> int:
    if not events:
        return 1
    return max(event.sequence for event in events) + 1


def _dict_data(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return _copy_json(data)
    return {"value": _copy_json(data)}


def _first_str(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return str(value)
    return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _copy_json(value: T) -> T:
    return json.loads(_json_dumps(value))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _json_loads_any(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _event_id() -> str:
    return str(uuid.uuid4())


_TOOL_PAYLOAD_KEYS = {
    "args",
    "arguments",
    "call_id",
    "duration_ms",
    "error",
    "id",
    "name",
    "observation",
    "result",
    "tool",
    "tool_call_id",
    "tool_name",
}


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
