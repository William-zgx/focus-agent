from __future__ import annotations

import json
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from focus_agent.core.agent_team import AgentTeamSession, AgentTeamTask, AgentTeamTaskOutput

from .agent_team_repository import AgentTeamRepository
from .postgres_schema import ensure_app_postgres_schema_on_connection


class PostgresAgentTeamRepository(AgentTeamRepository):
    def __init__(self, database_uri: str):
        self.database_uri = database_uri

    def setup(self) -> None:
        with psycopg.connect(self.database_uri) as conn:
            ensure_app_postgres_schema_on_connection(conn)

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    @staticmethod
    def _model_payload(value: AgentTeamSession | AgentTeamTask | AgentTeamTaskOutput) -> dict[str, Any]:
        return value.model_dump(mode="json")

    @staticmethod
    def _decode_payload(value: object) -> dict[str, Any]:
        if isinstance(value, str):
            return json.loads(value)
        if isinstance(value, dict):
            return value
        return dict(value)  # type: ignore[arg-type]

    @classmethod
    def _session_from_row(cls, row: dict[str, object]) -> AgentTeamSession:
        return AgentTeamSession.model_validate(cls._decode_payload(row["data_json"]))

    @classmethod
    def _task_from_row(cls, row: dict[str, object]) -> AgentTeamTask:
        return AgentTeamTask.model_validate(cls._decode_payload(row["data_json"]))

    @classmethod
    def _output_from_row(cls, row: dict[str, object]) -> AgentTeamTaskOutput:
        return AgentTeamTaskOutput.model_validate(cls._decode_payload(row["data_json"]))

    def create_session(self, session: AgentTeamSession) -> None:
        self._upsert_session(session)

    def save_session(self, session: AgentTeamSession) -> None:
        self._upsert_session(session)

    def _upsert_session(self, session: AgentTeamSession) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_agent_team_sessions (
                        session_id, root_thread_id, user_id, created_at, updated_at, data_json
                    ) VALUES (
                        %(session_id)s, %(root_thread_id)s, %(user_id)s,
                        %(created_at)s, %(updated_at)s, %(data_json)s
                    )
                    ON CONFLICT (session_id) DO UPDATE SET
                        root_thread_id = EXCLUDED.root_thread_id,
                        user_id = EXCLUDED.user_id,
                        updated_at = EXCLUDED.updated_at,
                        data_json = EXCLUDED.data_json
                    """,
                    {
                        "session_id": session.session_id,
                        "root_thread_id": session.root_thread_id,
                        "user_id": session.user_id,
                        "created_at": session.created_at,
                        "updated_at": session.updated_at,
                        "data_json": Jsonb(self._model_payload(session)),
                    },
                )

    def get_session(self, session_id: str) -> AgentTeamSession:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data_json FROM focus_agent_team_sessions WHERE session_id = %s",
                    (session_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise KeyError(f"Unknown agent team session: {session_id}")
        return self._session_from_row(row)

    def list_sessions(self, *, user_id: str | None = None) -> list[AgentTeamSession]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                if user_id is None:
                    cur.execute(
                        """
                        SELECT data_json FROM focus_agent_team_sessions
                        ORDER BY created_at DESC, session_id DESC
                        """
                    )
                else:
                    cur.execute(
                        """
                        SELECT data_json FROM focus_agent_team_sessions
                        WHERE user_id = %s
                        ORDER BY created_at DESC, session_id DESC
                        """,
                        (user_id,),
                    )
                rows = cur.fetchall()
        return [self._session_from_row(row) for row in rows]

    def create_task(self, task: AgentTeamTask) -> None:
        self._upsert_task(task)

    def save_task(self, task: AgentTeamTask) -> None:
        self._upsert_task(task)

    def _upsert_task(self, task: AgentTeamTask) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_agent_team_tasks (
                        task_id, session_id, created_at, updated_at, data_json
                    ) VALUES (
                        %(task_id)s, %(session_id)s,
                        %(created_at)s, %(updated_at)s, %(data_json)s
                    )
                    ON CONFLICT (task_id) DO UPDATE SET
                        session_id = EXCLUDED.session_id,
                        updated_at = EXCLUDED.updated_at,
                        data_json = EXCLUDED.data_json
                    """,
                    {
                        "task_id": task.task_id,
                        "session_id": task.session_id,
                        "created_at": task.created_at,
                        "updated_at": task.updated_at,
                        "data_json": Jsonb(self._model_payload(task)),
                    },
                )

    def get_task(self, task_id: str) -> AgentTeamTask:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT data_json FROM focus_agent_team_tasks WHERE task_id = %s",
                    (task_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise KeyError(f"Unknown agent team task: {task_id}")
        return self._task_from_row(row)

    def list_tasks(self, *, session_id: str) -> list[AgentTeamTask]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT data_json FROM focus_agent_team_tasks
                    WHERE session_id = %s
                    ORDER BY created_at, task_id
                    """,
                    (session_id,),
                )
                rows = cur.fetchall()
        return [self._task_from_row(row) for row in rows]

    def add_task_output(self, output: AgentTeamTaskOutput) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_agent_team_outputs (
                        output_id, task_id, created_at, data_json
                    ) VALUES (
                        %(output_id)s, %(task_id)s, %(created_at)s, %(data_json)s
                    )
                    ON CONFLICT (output_id) DO UPDATE SET
                        task_id = EXCLUDED.task_id,
                        created_at = EXCLUDED.created_at,
                        data_json = EXCLUDED.data_json
                    """,
                    {
                        "output_id": output.output_id,
                        "task_id": output.task_id,
                        "created_at": output.created_at,
                        "data_json": Jsonb(self._model_payload(output)),
                    },
                )

    def list_task_outputs(self, *, task_id: str) -> list[AgentTeamTaskOutput]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT data_json FROM focus_agent_team_outputs
                    WHERE task_id = %s
                    ORDER BY created_at, output_id
                    """,
                    (task_id,),
                )
                rows = cur.fetchall()
        return [self._output_from_row(row) for row in rows]


__all__ = ["PostgresAgentTeamRepository"]
