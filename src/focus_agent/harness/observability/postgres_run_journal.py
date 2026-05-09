from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from focus_agent.repositories.postgres_schema import ensure_app_postgres_schema_on_connection

from ..streaming import StreamEvent
from .run_journal import (
    JournalEvent,
    JournalRun,
    JournalToolEvent,
    _copy_json,
    _dict_data,
    _event_id,
    _limit,
    _now_iso,
    _snapshot,
    _tool_event_from_journal_event,
    _trajectory_summary,
)


class PostgresRunJournal:
    """PostgreSQL-backed harness run journal."""

    def __init__(self, database_uri: str) -> None:
        self.database_uri = database_uri
        self._lock = asyncio.Lock()

    def setup(self) -> None:
        with psycopg.connect(self.database_uri) as conn:
            ensure_app_postgres_schema_on_connection(conn)

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

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
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO focus_harness_runs (
                            run_id, thread_id, assistant_id, user_id, status, on_disconnect,
                            multitask_strategy, metadata_json, kwargs_json, error, created_at,
                            updated_at, completion_json
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb
                        )
                        ON CONFLICT (run_id) DO UPDATE SET
                            thread_id = EXCLUDED.thread_id,
                            assistant_id = EXCLUDED.assistant_id,
                            user_id = EXCLUDED.user_id,
                            status = EXCLUDED.status,
                            on_disconnect = EXCLUDED.on_disconnect,
                            multitask_strategy = EXCLUDED.multitask_strategy,
                            metadata_json = EXCLUDED.metadata_json,
                            kwargs_json = EXCLUDED.kwargs_json,
                            error = EXCLUDED.error,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (
                            run_id,
                            thread_id,
                            assistant_id,
                            user_id,
                            status,
                            on_disconnect,
                            multitask_strategy,
                            Jsonb(_copy_json(metadata or {})),
                            Jsonb(_copy_json(kwargs or {})),
                            error,
                            now,
                            now,
                        ),
                    )

    async def update_status(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
    ) -> None:
        async with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE focus_harness_runs
                        SET status = %s, error = COALESCE(%s, error), updated_at = %s
                        WHERE run_id = %s
                        """,
                        (status, error, _now_iso(), run_id),
                    )

    async def update_run_completion(self, run_id: str, **kwargs: Any) -> None:
        async with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT completion_json FROM focus_harness_runs WHERE run_id = %s",
                        (run_id,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return
                    completion = _dict_json(row.get("completion_json"))
                    completion.update(_copy_json(kwargs))
                    cur.execute(
                        """
                        UPDATE focus_harness_runs
                        SET completion_json = %s, updated_at = %s
                        WHERE run_id = %s
                        """,
                        (Jsonb(completion), _now_iso(), run_id),
                    )

    async def get_run(self, run_id: str) -> JournalRun | None:
        async with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM focus_harness_runs WHERE run_id = %s", (run_id,))
                    row = cur.fetchone()
        return _row_to_run(row) if row is not None else None

    async def list_runs(self, *, thread_id: str | None = None) -> list[JournalRun]:
        async with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    if thread_id is None:
                        cur.execute(
                            "SELECT * FROM focus_harness_runs ORDER BY created_at, run_id"
                        )
                    else:
                        cur.execute(
                            """
                            SELECT * FROM focus_harness_runs
                            WHERE thread_id = %s
                            ORDER BY created_at, run_id
                            """,
                            (thread_id,),
                        )
                    rows = cur.fetchall()
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
        async with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    if sequence is None:
                        cur.execute(
                            "SELECT pg_advisory_xact_lock(hashtext(%s), 0)",
                            (run_id,),
                        )
                        cur.execute(
                            """
                            SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence
                            FROM focus_harness_run_events
                            WHERE run_id = %s
                            """,
                            (run_id,),
                        )
                        sequence = int(cur.fetchone()["sequence"])
                    entry = JournalEvent(
                        event_id=event_id or _event_id(),
                        run_id=run_id,
                        event=event,
                        data=payload,
                        sequence=sequence,
                        stream_event_id=stream_event_id,
                        created_at=created_at or _now_iso(),
                    )
                    cur.execute(
                        """
                        INSERT INTO focus_harness_run_events (
                            event_id, run_id, event, data_json, sequence,
                            stream_event_id, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            entry.event_id,
                            entry.run_id,
                            entry.event,
                            Jsonb(entry.data),
                            entry.sequence,
                            entry.stream_event_id,
                            entry.created_at,
                        ),
                    )
                    tool_event = _tool_event_from_journal_event(entry)
                    if tool_event is not None:
                        cur.execute(
                            """
                            INSERT INTO focus_harness_tool_events (
                                event_id, run_id, tool_call_id, tool_name, status, sequence,
                                args_json, result_json, error, duration_ms, metadata_json,
                                created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                tool_event.event_id,
                                tool_event.run_id,
                                tool_event.tool_call_id,
                                tool_event.tool_name,
                                tool_event.status,
                                tool_event.sequence,
                                Jsonb(tool_event.args),
                                Jsonb(_copy_json(tool_event.result)),
                                tool_event.error,
                                tool_event.duration_ms,
                                Jsonb(tool_event.metadata),
                                tool_event.created_at,
                            ),
                        )
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
            with self._connect() as conn:
                with conn.cursor() as cur:
                    if event is None:
                        cur.execute(
                            """
                            SELECT * FROM focus_harness_run_events
                            WHERE run_id = %s
                            ORDER BY sequence, created_at
                            """,
                            (run_id,),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT * FROM focus_harness_run_events
                            WHERE run_id = %s AND event = %s
                            ORDER BY sequence, created_at
                            """,
                            (run_id, event),
                        )
                    rows = cur.fetchall()
        return _limit([_row_to_event(row) for row in rows], limit)

    async def count_events(self, run_id: str, *, event: str | None = None) -> int:
        async with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    if event is None:
                        cur.execute(
                            "SELECT COUNT(*) AS count FROM focus_harness_run_events WHERE run_id = %s",
                            (run_id,),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT COUNT(*) AS count
                            FROM focus_harness_run_events
                            WHERE run_id = %s AND event = %s
                            """,
                            (run_id, event),
                        )
                    row = cur.fetchone()
        return int(row["count"])

    async def list_tool_events(
        self,
        run_id: str,
        *,
        tool_name: str | None = None,
        limit: int | None = None,
    ) -> list[JournalToolEvent]:
        async with self._lock:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    if tool_name is None:
                        cur.execute(
                            """
                            SELECT * FROM focus_harness_tool_events
                            WHERE run_id = %s
                            ORDER BY sequence, created_at
                            """,
                            (run_id,),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT * FROM focus_harness_tool_events
                            WHERE run_id = %s AND tool_name = %s
                            ORDER BY sequence, created_at
                            """,
                            (run_id, tool_name),
                        )
                    rows = cur.fetchall()
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


def _row_to_run(row: dict[str, Any]) -> JournalRun:
    return JournalRun(
        run_id=str(row["run_id"]),
        thread_id=str(row["thread_id"]),
        assistant_id=_optional_str(row.get("assistant_id")),
        user_id=_optional_str(row.get("user_id")),
        status=str(row["status"]),
        on_disconnect=str(row.get("on_disconnect") or "cancel"),
        multitask_strategy=str(row["multitask_strategy"]),
        metadata=_dict_json(row.get("metadata_json")),
        kwargs=_dict_json(row.get("kwargs_json")),
        error=_optional_str(row.get("error")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
        completion=_dict_json(row.get("completion_json")),
    )


def _row_to_event(row: dict[str, Any]) -> JournalEvent:
    return JournalEvent(
        event_id=str(row["event_id"]),
        run_id=str(row["run_id"]),
        event=str(row["event"]),
        data=_dict_json(row.get("data_json")),
        sequence=int(row["sequence"]),
        stream_event_id=_optional_str(row.get("stream_event_id")),
        created_at=_iso(row.get("created_at")),
    )


def _row_to_tool_event(row: dict[str, Any]) -> JournalToolEvent:
    return JournalToolEvent(
        event_id=str(row["event_id"]),
        run_id=str(row["run_id"]),
        tool_call_id=_optional_str(row.get("tool_call_id")),
        tool_name=_optional_str(row.get("tool_name")),
        status=str(row["status"]),
        sequence=int(row["sequence"]),
        args=_dict_json(row.get("args_json")),
        result=row.get("result_json"),
        error=_optional_str(row.get("error")),
        duration_ms=_optional_float(row.get("duration_ms")),
        metadata=_dict_json(row.get("metadata_json")),
        created_at=_iso(row.get("created_at")),
    )


def _dict_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return _copy_json(value)
    if value is None:
        return {}
    return {"value": _copy_json(value)}


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


__all__ = ["PostgresRunJournal"]
