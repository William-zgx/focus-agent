from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from focus_agent.core.productivity import (
    FocusNote,
    FocusTask,
    FocusTaskEvent,
    FocusTaskEventKind,
    FocusTaskStatus,
)

from .productivity_repository import ProductivityRepository, _task_event


class SQLiteProductivityRepository(ProductivityRepository):
    def __init__(self, db_path: str):
        self.db_path = str(Path(db_path).expanduser())
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._setup()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _setup(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS focus_notes (
                    note_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    source_thread_id TEXT,
                    source_artifact_id TEXT,
                    source_kind TEXT,
                    source_id TEXT,
                    source_url TEXT,
                    pinned_context_json TEXT,
                    captured_from TEXT,
                    is_archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    archived_at TEXT,
                    data_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS focus_tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    due_at TEXT,
                    source_thread_id TEXT,
                    source_note_id TEXT,
                    source_artifact_id TEXT,
                    source_kind TEXT,
                    source_id TEXT,
                    source_url TEXT,
                    pinned_context_json TEXT,
                    captured_from TEXT,
                    assignee_user_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    archived_at TEXT,
                    data_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS focus_task_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES focus_tasks(task_id)
                )
                """
            )
            _add_column_if_missing(conn, "focus_notes", "source_kind", "TEXT")
            _add_column_if_missing(conn, "focus_notes", "source_id", "TEXT")
            _add_column_if_missing(conn, "focus_notes", "source_url", "TEXT")
            _add_column_if_missing(conn, "focus_notes", "pinned_context_json", "TEXT")
            _add_column_if_missing(conn, "focus_notes", "captured_from", "TEXT")
            _add_column_if_missing(conn, "focus_tasks", "source_artifact_id", "TEXT")
            _add_column_if_missing(conn, "focus_tasks", "source_kind", "TEXT")
            _add_column_if_missing(conn, "focus_tasks", "source_id", "TEXT")
            _add_column_if_missing(conn, "focus_tasks", "source_url", "TEXT")
            _add_column_if_missing(conn, "focus_tasks", "pinned_context_json", "TEXT")
            _add_column_if_missing(conn, "focus_tasks", "captured_from", "TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_focus_notes_user_updated ON focus_notes(user_id, is_archived, updated_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_focus_tasks_user_status_updated ON focus_tasks(user_id, status, updated_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_focus_task_events_task_created ON focus_task_events(task_id, created_at)"
            )
            conn.commit()

    @staticmethod
    def _note_from_row(row: sqlite3.Row) -> FocusNote:
        return FocusNote.model_validate(json.loads(row["data_json"]))

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> FocusTask:
        return FocusTask.model_validate(json.loads(row["data_json"]))

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> FocusTaskEvent:
        return FocusTaskEvent.model_validate(json.loads(row["data_json"]))

    def create_note(self, note: FocusNote) -> None:
        self.save_note(note)

    def save_note(self, note: FocusNote) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO focus_notes (
                    note_id, user_id, title, body, status, source_thread_id,
                    source_artifact_id, source_kind, source_id, source_url, pinned_context_json,
                    captured_from, is_archived, created_at, updated_at, archived_at, data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(note_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    title = excluded.title,
                    body = excluded.body,
                    status = excluded.status,
                    source_thread_id = excluded.source_thread_id,
                    source_artifact_id = excluded.source_artifact_id,
                    source_kind = excluded.source_kind,
                    source_id = excluded.source_id,
                    source_url = excluded.source_url,
                    pinned_context_json = excluded.pinned_context_json,
                    captured_from = excluded.captured_from,
                    is_archived = excluded.is_archived,
                    updated_at = excluded.updated_at,
                    archived_at = excluded.archived_at,
                    data_json = excluded.data_json
                """,
                (
                    note.note_id,
                    note.user_id,
                    note.title,
                    note.body,
                    note.status.value,
                    note.source_thread_id,
                    note.source_artifact_id,
                    note.source_kind,
                    note.source_id,
                    note.source_url,
                    json.dumps(note.pinned_context, ensure_ascii=False, sort_keys=True),
                    note.captured_from,
                    1 if note.is_archived else 0,
                    note.created_at,
                    note.updated_at,
                    note.archived_at,
                    note.model_dump_json(),
                ),
            )
            conn.commit()

    def get_note(self, *, note_id: str, user_id: str) -> FocusNote | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM focus_notes WHERE note_id = ? AND user_id = ?",
                (note_id, user_id),
            ).fetchone()
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
        clauses = ["user_id = ?"]
        params: list[object] = [user_id]
        if not include_archived:
            clauses.append("is_archived = 0")
        query_text = str(query or "").strip()
        if query_text:
            clauses.append("(LOWER(title) LIKE ? OR LOWER(body) LIKE ?)")
            like = f"%{query_text.casefold()}%"
            params.extend([like, like])
        sql = f"""
            SELECT data_json FROM focus_notes
            WHERE {" AND ".join(clauses)}
            ORDER BY updated_at DESC, note_id DESC
            LIMIT ? OFFSET ?
        """
        params.extend([max(0, limit), max(0, offset)])
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        notes = [self._note_from_row(row) for row in rows]
        tag_filter = {str(tag).strip() for tag in (tags or []) if str(tag).strip()}
        if tag_filter:
            notes = [note for note in notes if tag_filter.issubset(set(note.tags))]
        return notes

    def create_task(self, task: FocusTask) -> None:
        self.save_task(task, event=_task_event(task, kind=FocusTaskEventKind.CREATED))

    def save_task(self, task: FocusTask, *, event: FocusTaskEvent | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO focus_tasks (
                    task_id, user_id, title, status, due_at, source_thread_id,
                    source_note_id, source_artifact_id, source_kind, source_id, source_url,
                    pinned_context_json, captured_from, assignee_user_id, created_at, updated_at,
                    completed_at, archived_at, data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    user_id = excluded.user_id,
                    title = excluded.title,
                    status = excluded.status,
                    due_at = excluded.due_at,
                    source_thread_id = excluded.source_thread_id,
                    source_note_id = excluded.source_note_id,
                    source_artifact_id = excluded.source_artifact_id,
                    source_kind = excluded.source_kind,
                    source_id = excluded.source_id,
                    source_url = excluded.source_url,
                    pinned_context_json = excluded.pinned_context_json,
                    captured_from = excluded.captured_from,
                    assignee_user_id = excluded.assignee_user_id,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at,
                    archived_at = excluded.archived_at,
                    data_json = excluded.data_json
                """,
                (
                    task.task_id,
                    task.user_id,
                    task.title,
                    task.status.value,
                    task.due_at,
                    task.source_thread_id,
                    task.source_note_id,
                    task.source_artifact_id,
                    task.source_kind,
                    task.source_id,
                    task.source_url,
                    json.dumps(task.pinned_context, ensure_ascii=False, sort_keys=True),
                    task.captured_from,
                    task.assignee_user_id,
                    task.created_at,
                    task.updated_at,
                    task.completed_at,
                    task.archived_at,
                    task.model_dump_json(),
                ),
            )
            if event is not None:
                conn.execute(
                    """
                    INSERT INTO focus_task_events (
                        event_id, task_id, user_id, kind, created_at, data_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_id) DO UPDATE SET data_json = excluded.data_json
                    """,
                    (
                        event.event_id,
                        event.task_id,
                        event.user_id,
                        event.kind.value,
                        event.created_at,
                        event.model_dump_json(),
                    ),
                )
            conn.commit()

    def get_task(self, *, task_id: str, user_id: str) -> FocusTask | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM focus_tasks WHERE task_id = ? AND user_id = ?",
                (task_id, user_id),
            ).fetchone()
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
        clauses = ["user_id = ?"]
        params: list[object] = [user_id]
        if status:
            clauses.append("status = ?")
            params.append(FocusTaskStatus(status).value)
        elif not include_archived:
            clauses.append("status != ?")
            params.append(FocusTaskStatus.ARCHIVED.value)
        sql = f"""
            SELECT data_json FROM focus_tasks
            WHERE {" AND ".join(clauses)}
            ORDER BY updated_at DESC, task_id DESC
            LIMIT ? OFFSET ?
        """
        params.extend([max(0, limit), max(0, offset)])
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._task_from_row(row) for row in rows]

    def list_task_events(self, *, task_id: str, user_id: str) -> list[FocusTaskEvent]:
        if self.get_task(task_id=task_id, user_id=user_id) is None:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT data_json FROM focus_task_events
                WHERE task_id = ? AND user_id = ?
                ORDER BY created_at, event_id
                """,
                (task_id, user_id),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_type: str,
) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in existing:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


__all__ = ["SQLiteProductivityRepository"]
