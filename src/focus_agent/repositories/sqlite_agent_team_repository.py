from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from focus_agent.core.agent_team import (
    AgentTeamMergeReview,
    AgentTeamMergeReviewEvent,
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskStatus,
)

from .agent_team_repository import AgentTeamRepository, _format_time, _now, _parse_time


class SQLiteAgentTeamRepository(AgentTeamRepository):
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
                CREATE TABLE IF NOT EXISTS agent_team_sessions (
                    session_id TEXT PRIMARY KEY,
                    root_thread_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    data_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_team_tasks (
                    task_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES agent_team_sessions(session_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_team_outputs (
                    output_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES agent_team_tasks(task_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS focus_agent_team_merge_reviews (
                    review_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    data_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS focus_agent_team_merge_review_events (
                    event_id TEXT PRIMARY KEY,
                    review_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    FOREIGN KEY(review_id) REFERENCES focus_agent_team_merge_reviews(review_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_team_sessions_user_created ON agent_team_sessions(user_id, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_team_tasks_session_created ON agent_team_tasks(session_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_team_tasks_session_updated ON agent_team_tasks(session_id, updated_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_team_outputs_task_created ON agent_team_outputs(task_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_team_merge_reviews_session_created ON focus_agent_team_merge_reviews(session_id, created_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_team_merge_review_events_review_created ON focus_agent_team_merge_review_events(review_id, created_at)"
            )
            conn.commit()

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> AgentTeamSession:
        return AgentTeamSession.model_validate(json.loads(row["data_json"]))

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> AgentTeamTask:
        return AgentTeamTask.model_validate(json.loads(row["data_json"]))

    @staticmethod
    def _output_from_row(row: sqlite3.Row) -> AgentTeamTaskOutput:
        return AgentTeamTaskOutput.model_validate(json.loads(row["data_json"]))

    @staticmethod
    def _merge_review_from_row(row: sqlite3.Row) -> AgentTeamMergeReview:
        return AgentTeamMergeReview.model_validate(json.loads(row["data_json"]))

    @staticmethod
    def _merge_review_event_from_row(row: sqlite3.Row) -> AgentTeamMergeReviewEvent:
        return AgentTeamMergeReviewEvent.model_validate(json.loads(row["data_json"]))

    def create_session(self, session: AgentTeamSession) -> None:
        self._upsert_session(session)

    def save_session(self, session: AgentTeamSession) -> None:
        self._upsert_session(session)

    def _upsert_session(self, session: AgentTeamSession) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_team_sessions (
                    session_id, root_thread_id, user_id, created_at, updated_at, data_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    root_thread_id = excluded.root_thread_id,
                    user_id = excluded.user_id,
                    updated_at = excluded.updated_at,
                    data_json = excluded.data_json
                """,
                (
                    session.session_id,
                    session.root_thread_id,
                    session.user_id,
                    session.created_at,
                    session.updated_at,
                    session.model_dump_json(),
                ),
            )
            conn.commit()

    def get_session(self, session_id: str) -> AgentTeamSession:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM agent_team_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown agent team session: {session_id}")
        return self._session_from_row(row)

    def list_sessions(self, *, user_id: str | None = None) -> list[AgentTeamSession]:
        with self._connect() as conn:
            if user_id is None:
                rows = conn.execute(
                    "SELECT data_json FROM agent_team_sessions ORDER BY created_at DESC, session_id DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT data_json FROM agent_team_sessions
                    WHERE user_id = ?
                    ORDER BY created_at DESC, session_id DESC
                    """,
                    (user_id,),
                ).fetchall()
        return [self._session_from_row(row) for row in rows]

    def create_task(self, task: AgentTeamTask) -> None:
        self._upsert_task(task)

    def save_task(self, task: AgentTeamTask) -> None:
        self._upsert_task(task)

    def _upsert_task(self, task: AgentTeamTask) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_team_tasks (
                    task_id, session_id, created_at, updated_at, data_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    updated_at = excluded.updated_at,
                    data_json = excluded.data_json
                """,
                (
                    task.task_id,
                    task.session_id,
                    task.created_at,
                    task.updated_at,
                    task.model_dump_json(),
                ),
            )
            conn.commit()

    def get_task(self, task_id: str) -> AgentTeamTask:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM agent_team_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown agent team task: {task_id}")
        return self._task_from_row(row)

    def list_tasks(self, *, session_id: str) -> list[AgentTeamTask]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT data_json FROM agent_team_tasks
                WHERE session_id = ?
                ORDER BY created_at, task_id
                """,
                (session_id,),
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def claim_task(
        self, *, task_id: str, owner: str, ttl_seconds: float
    ) -> AgentTeamTask | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT data_json FROM agent_team_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise KeyError(f"Unknown agent team task: {task_id}")
            task = self._task_from_row(row)
            now = _now()
            if task.status not in {AgentTeamTaskStatus.QUEUED, AgentTeamTaskStatus.RUNNING}:
                conn.rollback()
                return None
            if task.claimed_until and task.claim_token and _parse_time(task.claimed_until) > now:
                conn.rollback()
                return None
            claim_token = uuid4().hex
            updated = task.model_copy(
                update={
                    "status": AgentTeamTaskStatus.RUNNING,
                    "attempt": max(0, int(task.attempt or 0)) + 1,
                    "claim_token": claim_token,
                    "claim_owner": str(owner or "agent-team-worker"),
                    "claimed_until": _format_time(
                        now + timedelta(seconds=max(float(ttl_seconds or 0.0), 0.001))
                    ),
                    "heartbeat_at": _format_time(now),
                    "started_at": task.started_at or _format_time(now),
                    "updated_at": _format_time(now),
                }
            )
            conn.execute(
                """
                UPDATE agent_team_tasks
                SET updated_at = ?, data_json = ?
                WHERE task_id = ?
                """,
                (updated.updated_at, updated.model_dump_json(), task_id),
            )
            conn.commit()
            return updated

    def heartbeat_task_claim(
        self, *, task_id: str, claim_token: str, ttl_seconds: float
    ) -> bool:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT data_json FROM agent_team_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise KeyError(f"Unknown agent team task: {task_id}")
            task = self._task_from_row(row)
            now = _now()
            if (
                task.claim_token != claim_token
                or (task.claimed_until and _parse_time(task.claimed_until) <= now)
            ):
                conn.rollback()
                return False
            updated = task.model_copy(
                update={
                    "claimed_until": _format_time(
                        now + timedelta(seconds=max(float(ttl_seconds or 0.0), 0.001))
                    ),
                    "heartbeat_at": _format_time(now),
                    "updated_at": _format_time(now),
                }
            )
            conn.execute(
                "UPDATE agent_team_tasks SET updated_at = ?, data_json = ? WHERE task_id = ?",
                (updated.updated_at, updated.model_dump_json(), task_id),
            )
            conn.commit()
            return True

    def release_task_claim(
        self,
        *,
        task_id: str,
        claim_token: str,
        final_status: AgentTeamTaskStatus | str,
        error: str | None = None,
    ) -> AgentTeamTask:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT data_json FROM agent_team_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise KeyError(f"Unknown agent team task: {task_id}")
            task = self._task_from_row(row)
            now_dt = _now()
            if (
                task.claim_token != claim_token
                or (task.claimed_until and _parse_time(task.claimed_until) <= now_dt)
            ):
                conn.rollback()
                return task
            now = _format_time(now_dt)
            status = AgentTeamTaskStatus(final_status)
            updated = task.model_copy(
                update={
                    "status": status,
                    "claim_token": None,
                    "claim_owner": None,
                    "claimed_until": None,
                    "heartbeat_at": now,
                    "finished_at": now
                    if status
                    in {
                        AgentTeamTaskStatus.DONE,
                        AgentTeamTaskStatus.FAILED,
                        AgentTeamTaskStatus.CANCELLED,
                        AgentTeamTaskStatus.BLOCKED,
                    }
                    else task.finished_at,
                    "last_error": error if error is not None else task.last_error,
                    "updated_at": now,
                }
            )
            conn.execute(
                "UPDATE agent_team_tasks SET updated_at = ?, data_json = ? WHERE task_id = ?",
                (updated.updated_at, updated.model_dump_json(), task_id),
            )
            conn.commit()
            return updated

    def add_task_output(self, output: AgentTeamTaskOutput) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_team_outputs (output_id, task_id, created_at, data_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(output_id) DO UPDATE SET
                    task_id = excluded.task_id,
                    created_at = excluded.created_at,
                    data_json = excluded.data_json
                """,
                (
                    output.output_id,
                    output.task_id,
                    output.created_at,
                    output.model_dump_json(),
                ),
            )
            conn.commit()

    def list_task_outputs(self, *, task_id: str) -> list[AgentTeamTaskOutput]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT data_json FROM agent_team_outputs
                WHERE task_id = ?
                ORDER BY created_at, output_id
                """,
                (task_id,),
            ).fetchall()
        return [self._output_from_row(row) for row in rows]

    def save_merge_review(self, review: AgentTeamMergeReview) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO focus_agent_team_merge_reviews (
                    review_id, session_id, status, created_at, updated_at, data_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(review_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    data_json = excluded.data_json
                """,
                (
                    review.review_id,
                    review.session_id,
                    review.status.value,
                    review.created_at,
                    review.updated_at,
                    review.model_dump_json(),
                ),
            )
            conn.commit()

    def get_merge_review(self, review_id: str) -> AgentTeamMergeReview:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM focus_agent_team_merge_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown agent team merge review: {review_id}")
        return self._merge_review_from_row(row)

    def list_merge_reviews(self, *, session_id: str) -> list[AgentTeamMergeReview]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT data_json FROM focus_agent_team_merge_reviews
                WHERE session_id = ?
                ORDER BY created_at DESC, review_id DESC
                """,
                (session_id,),
            ).fetchall()
        return [self._merge_review_from_row(row) for row in rows]

    def add_merge_review_event(self, event: AgentTeamMergeReviewEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO focus_agent_team_merge_review_events (
                    event_id, review_id, session_id, created_at, data_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    review_id = excluded.review_id,
                    session_id = excluded.session_id,
                    created_at = excluded.created_at,
                    data_json = excluded.data_json
                """,
                (
                    event.event_id,
                    event.review_id,
                    event.session_id,
                    event.created_at,
                    event.model_dump_json(),
                ),
            )
            conn.commit()

    def list_merge_review_events(self, *, review_id: str) -> list[AgentTeamMergeReviewEvent]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT data_json FROM focus_agent_team_merge_review_events
                WHERE review_id = ?
                ORDER BY created_at, event_id
                """,
                (review_id,),
            ).fetchall()
        return [self._merge_review_event_from_row(row) for row in rows]


__all__ = ["SQLiteAgentTeamRepository"]
