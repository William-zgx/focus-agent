from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from focus_agent.core.productivity import (
    FocusNote,
    FocusTask,
    FocusTaskEvent,
    FocusTaskEventKind,
    FocusTaskStatus,
)

from .postgres_schema import ensure_app_postgres_schema_on_connection
from .productivity_repository import ProductivityRepository, _task_event


class PostgresProductivityRepository(ProductivityRepository):
    def __init__(self, database_uri: str):
        self.database_uri = database_uri

    def setup(self) -> None:
        with psycopg.connect(self.database_uri) as conn:
            ensure_app_postgres_schema_on_connection(conn)

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    @staticmethod
    def _decode_payload(value: object) -> dict[str, Any]:
        if isinstance(value, str):
            return json.loads(value)
        if isinstance(value, dict):
            return value
        return dict(value)  # type: ignore[arg-type]

    @classmethod
    def _note_from_row(cls, row: dict[str, object]) -> FocusNote:
        return FocusNote.model_validate(cls._decode_payload(row["data_json"]))

    @classmethod
    def _task_from_row(cls, row: dict[str, object]) -> FocusTask:
        return FocusTask.model_validate(cls._decode_payload(row["data_json"]))

    @classmethod
    def _event_from_row(cls, row: dict[str, object]) -> FocusTaskEvent:
        return FocusTaskEvent.model_validate(cls._decode_payload(row["data_json"]))

    def create_note(self, note: FocusNote) -> None:
        self.save_note(note)

    def save_note(self, note: FocusNote) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_notes (
                        note_id, user_id, title, body, tags, status, source_thread_id,
                        source_artifact_id, source_kind, source_id, source_url,
                        pinned_context, captured_from, is_archived, created_at, updated_at,
                        archived_at, data_json
                    ) VALUES (
                        %(note_id)s, %(user_id)s, %(title)s, %(body)s, %(tags)s,
                        %(status)s, %(source_thread_id)s, %(source_artifact_id)s,
                        %(source_kind)s, %(source_id)s, %(source_url)s,
                        %(pinned_context)s, %(captured_from)s,
                        %(is_archived)s, %(created_at)s, %(updated_at)s, %(archived_at)s,
                        %(data_json)s
                    )
                    ON CONFLICT (note_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        title = EXCLUDED.title,
                        body = EXCLUDED.body,
                        tags = EXCLUDED.tags,
                        status = EXCLUDED.status,
                        source_thread_id = EXCLUDED.source_thread_id,
                        source_artifact_id = EXCLUDED.source_artifact_id,
                        source_kind = EXCLUDED.source_kind,
                        source_id = EXCLUDED.source_id,
                        source_url = EXCLUDED.source_url,
                        pinned_context = EXCLUDED.pinned_context,
                        captured_from = EXCLUDED.captured_from,
                        is_archived = EXCLUDED.is_archived,
                        updated_at = EXCLUDED.updated_at,
                        archived_at = EXCLUDED.archived_at,
                        data_json = EXCLUDED.data_json
                    """,
                    {
                        "note_id": note.note_id,
                        "user_id": note.user_id,
                        "title": note.title,
                        "body": note.body,
                        "tags": note.tags,
                        "status": note.status.value,
                        "source_thread_id": note.source_thread_id,
                        "source_artifact_id": note.source_artifact_id,
                        "source_kind": note.source_kind,
                        "source_id": note.source_id,
                        "source_url": note.source_url,
                        "pinned_context": Jsonb(note.pinned_context),
                        "captured_from": note.captured_from,
                        "is_archived": note.is_archived,
                        "created_at": note.created_at,
                        "updated_at": note.updated_at,
                        "archived_at": note.archived_at,
                        "data_json": Jsonb(note.model_dump(mode="json")),
                    },
                )

    def get_note(self, *, note_id: str, user_id: str) -> FocusNote | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data_json FROM focus_notes WHERE note_id = %s AND user_id = %s",
                    (note_id, user_id),
                )
                row = cur.fetchone()
        return None if row is None else self._note_from_row(row)

    def list_notes(
        self,
        *,
        user_id: str,
        query: str | None = None,
        tags: list[str] | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FocusNote]:
        clauses = ["user_id = %(user_id)s"]
        params: dict[str, object] = {
            "user_id": user_id,
            "limit": max(0, limit),
            "offset": max(0, offset),
        }
        if not include_archived:
            clauses.append("is_archived = false")
        query_text = str(query or "").strip()
        if query_text:
            clauses.append("(title ILIKE %(query)s OR body ILIKE %(query)s)")
            params["query"] = f"%{query_text}%"
        tag_filter = [str(tag).strip() for tag in (tags or []) if str(tag).strip()]
        if tag_filter:
            clauses.append("tags @> %(tags)s")
            params["tags"] = tag_filter
        sql = f"""
            SELECT data_json FROM focus_notes
            WHERE {' AND '.join(clauses)}
            ORDER BY updated_at DESC, note_id DESC
            LIMIT %(limit)s OFFSET %(offset)s
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [self._note_from_row(row) for row in rows]

    def create_task(self, task: FocusTask) -> None:
        self.save_task(task, event=_task_event(task, kind=FocusTaskEventKind.CREATED))

    def save_task(self, task: FocusTask, *, event: FocusTaskEvent | None = None) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_tasks (
                        task_id, user_id, title, description, status, due_at, priority,
                        source_thread_id, source_note_id, source_kind, source_id, source_url,
                        pinned_context, captured_from,
                        assignee_user_id, tags,
                        created_at, updated_at, completed_at, archived_at, data_json
                    ) VALUES (
                        %(task_id)s, %(user_id)s, %(title)s, %(description)s,
                        %(status)s, %(due_at)s, %(priority)s,
                        %(source_thread_id)s, %(source_note_id)s, %(source_kind)s,
                        %(source_id)s, %(source_url)s, %(pinned_context)s,
                        %(captured_from)s, %(assignee_user_id)s,
                        %(tags)s,
                        %(created_at)s, %(updated_at)s, %(completed_at)s, %(archived_at)s,
                        %(data_json)s
                    )
                    ON CONFLICT (task_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        status = EXCLUDED.status,
                        due_at = EXCLUDED.due_at,
                        priority = EXCLUDED.priority,
                        source_thread_id = EXCLUDED.source_thread_id,
                        source_note_id = EXCLUDED.source_note_id,
                        source_kind = EXCLUDED.source_kind,
                        source_id = EXCLUDED.source_id,
                        source_url = EXCLUDED.source_url,
                        pinned_context = EXCLUDED.pinned_context,
                        captured_from = EXCLUDED.captured_from,
                        assignee_user_id = EXCLUDED.assignee_user_id,
                        tags = EXCLUDED.tags,
                        updated_at = EXCLUDED.updated_at,
                        completed_at = EXCLUDED.completed_at,
                        archived_at = EXCLUDED.archived_at,
                        data_json = EXCLUDED.data_json
                    """,
                    {
                        "task_id": task.task_id,
                        "user_id": task.user_id,
                        "title": task.title,
                        "description": task.description,
                        "status": task.status.value,
                        "due_at": task.due_at,
                        "priority": task.priority,
                        "source_thread_id": task.source_thread_id,
                        "source_note_id": task.source_note_id,
                        "source_kind": task.source_kind,
                        "source_id": task.source_id,
                        "source_url": task.source_url,
                        "pinned_context": Jsonb(task.pinned_context),
                        "captured_from": task.captured_from,
                        "assignee_user_id": task.assignee_user_id,
                        "tags": task.tags,
                        "created_at": task.created_at,
                        "updated_at": task.updated_at,
                        "completed_at": task.completed_at,
                        "archived_at": task.archived_at,
                        "data_json": Jsonb(task.model_dump(mode="json")),
                    },
                )
                if event is not None:
                    cur.execute(
                        """
                        INSERT INTO focus_task_events (
                            event_id, task_id, user_id, kind, created_at, data_json
                        ) VALUES (
                            %(event_id)s, %(task_id)s, %(user_id)s, %(kind)s,
                            %(created_at)s, %(data_json)s
                        )
                        ON CONFLICT (event_id) DO UPDATE SET data_json = EXCLUDED.data_json
                        """,
                        {
                            "event_id": event.event_id,
                            "task_id": event.task_id,
                            "user_id": event.user_id,
                            "kind": event.kind.value,
                            "created_at": event.created_at,
                            "data_json": Jsonb(event.model_dump(mode="json")),
                        },
                    )

    def get_task(self, *, task_id: str, user_id: str) -> FocusTask | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data_json FROM focus_tasks WHERE task_id = %s AND user_id = %s",
                    (task_id, user_id),
                )
                row = cur.fetchone()
        return None if row is None else self._task_from_row(row)

    def list_tasks(
        self,
        *,
        user_id: str,
        status: FocusTaskStatus | str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FocusTask]:
        clauses = ["user_id = %(user_id)s"]
        params: dict[str, object] = {
            "user_id": user_id,
            "limit": max(0, limit),
            "offset": max(0, offset),
        }
        if status:
            clauses.append("status = %(status)s")
            params["status"] = FocusTaskStatus(status).value
        elif not include_archived:
            clauses.append("status != %(archived)s")
            params["archived"] = FocusTaskStatus.ARCHIVED.value
        sql = f"""
            SELECT data_json FROM focus_tasks
            WHERE {' AND '.join(clauses)}
            ORDER BY updated_at DESC, task_id DESC
            LIMIT %(limit)s OFFSET %(offset)s
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [self._task_from_row(row) for row in rows]

    def list_task_events(self, *, task_id: str, user_id: str) -> list[FocusTaskEvent]:
        if self.get_task(task_id=task_id, user_id=user_id) is None:
            return []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT data_json FROM focus_task_events
                    WHERE task_id = %s AND user_id = %s
                    ORDER BY created_at, event_id
                    """,
                    (task_id, user_id),
                )
                rows = cur.fetchall()
        return [self._event_from_row(row) for row in rows]


__all__ = ["PostgresProductivityRepository"]
