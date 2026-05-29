from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from focus_agent.runtime.thread_pool import shared_thread_pool

from ..streaming import StreamEvent
from .run_journal_helpers import (
    _copy_json,
    _dict_data,
    _event_id,
    _json_dumps,
    _json_loads,
    _limit,
    _now_iso,
    _row_to_event,
    _row_to_run,
    _row_to_tool_event,
    _snapshot,
    _tool_event_from_journal_event,
    _trajectory_summary,
)

if TYPE_CHECKING:
    from .run_journal import JournalEvent, JournalRun, JournalToolEvent

T = TypeVar("T")


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
            return await loop.run_in_executor(
                shared_thread_pool(), self._run_db_sync, operation
            )

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
            lambda conn: conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
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
        from .run_journal import JournalEvent

        payload = _copy_json(data or {})

        def operation(conn: sqlite3.Connection) -> JournalEvent:
            effective_sequence = sequence
            if effective_sequence is None:
                row = conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence "
                    "FROM run_events WHERE run_id = ?",
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


__all__ = ["SQLiteRunJournal"]
