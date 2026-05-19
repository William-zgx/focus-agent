from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from focus_agent.storage.postgres import PostgresConnectionProvider

from ..observability.trajectory import TurnTrajectoryRecord
from ._postgres_base import PostgresMixin
from .postgres_trajectory_mappers import PostgresTrajectoryMapperMixin
from .postgres_trajectory_query import PostgresTrajectoryQueryMixin
from .postgres_trajectory_schema import PostgresTrajectorySchemaMixin
from .postgres_trajectory_stats import PostgresTrajectoryStatsMixin


@dataclass(slots=True)
class TrajectoryTurnQuery:
    turn_ids: Sequence[str] | None = None
    request_id: str | None = None
    trace_id: str | None = None
    thread_id: str | None = None
    root_thread_id: str | None = None
    parent_thread_id: str | None = None
    branch_id: str | None = None
    branch_role: str | Sequence[str] | None = None
    status: str | Sequence[str] | None = None
    scene: str | Sequence[str] | None = None
    kind: str | Sequence[str] | None = None
    selected_model: str | Sequence[str] | None = None
    tool: str | Sequence[str] | None = None
    fallback_used: bool | None = None
    cache_hit: bool | None = None
    has_error: bool | None = None
    min_latency_ms: float | None = None
    max_latency_ms: float | None = None
    min_tool_calls: int | None = None
    max_tool_calls: int | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int | None = 100
    offset: int = 0
    newest_first: bool = True


_PSYCOPG_MODULE = psycopg  # Preserve the legacy monkeypatch path used by unit tests.


class PostgresTrajectoryRepository(
    PostgresMixin,
    PostgresTrajectorySchemaMixin,
    PostgresTrajectoryStatsMixin,
    PostgresTrajectoryQueryMixin,
    PostgresTrajectoryMapperMixin,
):
    def __init__(
        self,
        database_uri: str,
        *,
        connection_provider: PostgresConnectionProvider | None = None,
    ):
        self.database_uri = database_uri
        self.connection_provider = connection_provider

    def record_turn(self, record: TurnTrajectoryRecord) -> None:
        with self._cursor(dict_row=True) as cur:
            cur.execute(
                """
                    INSERT INTO focus_trajectory_turns (
                        id,
                        schema_version,
                        kind,
                        status,
                        thread_id,
                        root_thread_id,
                        request_id,
                        trace_id,
                        root_span_id,
                        environment,
                        deployment,
                        app_version,
                        parent_thread_id,
                        branch_id,
                        branch_role,
                        user_id_hash,
                        scene,
                        turn_index,
                        task_brief,
                        user_message,
                        answer,
                        selected_model,
                        selected_thinking_mode,
                        plan,
                        reflection,
                        plan_meta,
                        metrics,
                        error,
                        started_at,
                        finished_at
                    )
                    VALUES (
                        %(id)s,
                        %(schema_version)s,
                        %(kind)s,
                        %(status)s,
                        %(thread_id)s,
                        %(root_thread_id)s,
                        %(request_id)s,
                        %(trace_id)s,
                        %(root_span_id)s,
                        %(environment)s,
                        %(deployment)s,
                        %(app_version)s,
                        %(parent_thread_id)s,
                        %(branch_id)s,
                        %(branch_role)s,
                        %(user_id_hash)s,
                        %(scene)s,
                        %(turn_index)s,
                        %(task_brief)s,
                        %(user_message)s,
                        %(answer)s,
                        %(selected_model)s,
                        %(selected_thinking_mode)s,
                        %(plan)s,
                        %(reflection)s,
                        %(plan_meta)s,
                        %(metrics)s,
                        %(error)s,
                        %(started_at)s,
                        %(finished_at)s
                    )
                    """,
                self._turn_params(record),
            )
            for index, step in enumerate(record.trajectory):
                cur.execute(
                    """
                        INSERT INTO focus_trajectory_steps (
                            turn_id,
                            step_index,
                            tool,
                            args,
                            observation,
                            observation_truncated,
                            duration_ms,
                            error,
                            cache_hit,
                            fallback_used,
                            fallback_group,
                            parallel_batch_size,
                            runtime
                        )
                        VALUES (
                            %(turn_id)s,
                            %(step_index)s,
                            %(tool)s,
                            %(args)s,
                            %(observation)s,
                            %(observation_truncated)s,
                            %(duration_ms)s,
                            %(error)s,
                            %(cache_hit)s,
                            %(fallback_used)s,
                            %(fallback_group)s,
                            %(parallel_batch_size)s,
                            %(runtime)s
                        )
                        """,
                    self._step_params(record.id, index, step),
                )

    def list_turns(
        self,
        query: TrajectoryTurnQuery | dict[str, Any] | None = None,
        *,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        normalized = self._normalize_query(query, filters=filters, limit=limit, offset=offset)
        sql, params = self._build_turn_select_sql(query=normalized, select_clause="SELECT t.*")
        with self._cursor(dict_row=True) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return [self._row_to_turn_summary(row) for row in rows]

    def get_turn(self, turn_id: str) -> TurnTrajectoryRecord | None:
        with self._cursor(dict_row=True) as cur:
            cur.execute(
                "SELECT t.* FROM focus_trajectory_turns t WHERE t.id = %(turn_id)s",
                {"turn_id": turn_id},
            )
            row = cur.fetchone()
        if row is None:
            return None

        steps_by_turn_id = self.list_steps_by_turn_ids([turn_id])
        return self._row_to_turn_record(row, steps_by_turn_id.get(turn_id, []))

    def list_steps_by_turn_ids(self, turn_ids: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        normalized_turn_ids = [str(turn_id) for turn_id in turn_ids if str(turn_id)]
        if not normalized_turn_ids:
            return {}

        with self._cursor(dict_row=True) as cur:
            cur.execute(
                """
                    SELECT s.*
                    FROM focus_trajectory_steps s
                    WHERE s.turn_id = ANY(%(turn_ids)s)
                    ORDER BY s.turn_id, s.step_index
                    """,
                {"turn_ids": normalized_turn_ids},
            )
            rows = cur.fetchall()

        steps_by_turn_id: dict[str, list[dict[str, Any]]] = {
            turn_id: [] for turn_id in normalized_turn_ids
        }
        for row in rows:
            steps_by_turn_id.setdefault(str(row["turn_id"]), []).append(self._row_to_step_dict(row))
        return steps_by_turn_id

    def export_turns(
        self,
        query: TrajectoryTurnQuery | dict[str, Any] | None = None,
        *,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        normalized = self._normalize_query(query, filters=filters, limit=limit, offset=offset)
        sql, params = self._build_turn_select_sql(query=normalized, select_clause="SELECT t.*")
        with self._cursor(dict_row=True) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        turn_ids = [str(row["id"]) for row in rows]
        steps_by_turn_id = self.list_steps_by_turn_ids(turn_ids)
        exports: list[dict[str, Any]] = []
        for row in rows:
            turn_id = str(row["id"])
            payload = self._row_to_turn_record(row, steps_by_turn_id.get(turn_id, [])).to_dict()
            payload["created_at"] = self._iso_datetime(row.get("created_at"))
            exports.append(payload)
        return exports
