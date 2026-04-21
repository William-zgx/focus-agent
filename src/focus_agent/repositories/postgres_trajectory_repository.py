from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..observability.trajectory import TrajectoryStep, TurnTrajectoryRecord


@dataclass(slots=True)
class TrajectoryTurnQuery:
    turn_ids: Sequence[str] | None = None
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


class PostgresTrajectoryRepository:
    def __init__(self, database_uri: str):
        self.database_uri = database_uri

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    def setup(self) -> None:
        with psycopg.connect(self.database_uri) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS focus_trajectory_turns (
                        id UUID PRIMARY KEY,
                        schema_version INT NOT NULL DEFAULT 1,
                        kind TEXT NOT NULL,
                        status TEXT NOT NULL,
                        thread_id TEXT NOT NULL,
                        root_thread_id TEXT NOT NULL,
                        parent_thread_id TEXT,
                        branch_id TEXT,
                        branch_role TEXT,
                        user_id_hash TEXT NOT NULL,
                        scene TEXT NOT NULL,
                        turn_index INT,
                        task_brief TEXT,
                        user_message TEXT,
                        answer TEXT,
                        selected_model TEXT,
                        selected_thinking_mode TEXT,
                        plan JSONB,
                        reflection JSONB,
                        plan_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
                        metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
                        error TEXT,
                        started_at TIMESTAMPTZ NOT NULL,
                        finished_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS focus_trajectory_steps (
                        id BIGSERIAL PRIMARY KEY,
                        turn_id UUID NOT NULL REFERENCES focus_trajectory_turns(id) ON DELETE CASCADE,
                        step_index INT NOT NULL,
                        tool TEXT NOT NULL,
                        args JSONB NOT NULL DEFAULT '{}'::jsonb,
                        observation TEXT NOT NULL DEFAULT '',
                        observation_truncated BOOLEAN NOT NULL DEFAULT false,
                        duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
                        error TEXT,
                        cache_hit BOOLEAN NOT NULL DEFAULT false,
                        fallback_used BOOLEAN NOT NULL DEFAULT false,
                        fallback_group TEXT,
                        parallel_batch_size INT,
                        runtime JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        UNIQUE (turn_id, step_index)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_focus_traj_turns_thread_time
                    ON focus_trajectory_turns(thread_id, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_focus_traj_turns_root_time
                    ON focus_trajectory_turns(root_thread_id, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_focus_traj_steps_turn
                    ON focus_trajectory_steps(turn_id, step_index)
                    """
                )

    def record_turn(self, record: TurnTrajectoryRecord) -> None:
        with psycopg.connect(self.database_uri) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_trajectory_turns (
                        id,
                        schema_version,
                        kind,
                        status,
                        thread_id,
                        root_thread_id,
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
                        {
                            "turn_id": record.id,
                            "step_index": index,
                            "tool": step.tool,
                            "args": Jsonb(step.args),
                            "observation": step.observation,
                            "observation_truncated": step.observation_truncated,
                            "duration_ms": step.duration_ms,
                            "error": step.error,
                            "cache_hit": step.cache_hit,
                            "fallback_used": step.fallback_used,
                            "fallback_group": step.fallback_group,
                            "parallel_batch_size": step.parallel_batch_size,
                            "runtime": Jsonb(step.runtime),
                        },
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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [self._row_to_turn_summary(row) for row in rows]

    def get_turn(self, turn_id: str) -> TurnTrajectoryRecord | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT t.* FROM focus_trajectory_turns t WHERE t.id = %(turn_id)s", {"turn_id": turn_id})
                row = cur.fetchone()
        if row is None:
            return None

        steps_by_turn_id = self.list_steps_by_turn_ids([turn_id])
        return self._row_to_turn_record(row, steps_by_turn_id.get(turn_id, []))

    def list_steps_by_turn_ids(self, turn_ids: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        normalized_turn_ids = [str(turn_id) for turn_id in turn_ids if str(turn_id)]
        if not normalized_turn_ids:
            return {}

        with self._connect() as conn:
            with conn.cursor() as cur:
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

        steps_by_turn_id: dict[str, list[dict[str, Any]]] = {turn_id: [] for turn_id in normalized_turn_ids}
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
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        turn_ids = [str(row["id"]) for row in rows]
        steps_by_turn_id = self.list_steps_by_turn_ids(turn_ids)
        exports: list[dict[str, Any]] = []
        for row in rows:
            turn_id = str(row["id"])
            payload = self._row_to_turn_record(row, steps_by_turn_id.get(turn_id, [])).to_dict()
            payload["created_at"] = _iso_datetime(row.get("created_at"))
            exports.append(payload)
        return exports

    def get_turn_stats(
        self,
        query: TrajectoryTurnQuery | dict[str, Any] | None = None,
        *,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = replace(self._normalize_query(query, filters=filters), limit=None, offset=0)
        where_sql, params, step_conditions, step_params = self._build_turn_where_clause(normalized)

        overview_sql = f"""
            SELECT
                COUNT(*)::INT AS turn_count,
                COALESCE(SUM(CASE WHEN t.status = 'succeeded' THEN 1 ELSE 0 END), 0)::INT AS succeeded_count,
                COALESCE(SUM(CASE WHEN t.status <> 'succeeded' THEN 1 ELSE 0 END), 0)::INT AS non_succeeded_count,
                COALESCE(SUM(COALESCE((t.metrics ->> 'tool_calls')::INT, 0)), 0)::INT AS total_tool_calls,
                COALESCE(SUM(COALESCE((t.metrics ->> 'llm_calls')::INT, 0)), 0)::INT AS total_llm_calls,
                COALESCE(SUM(COALESCE((t.metrics ->> 'cache_hits')::INT, 0)), 0)::INT AS total_cache_hits,
                COALESCE(SUM(COALESCE((t.metrics ->> 'fallback_uses')::INT, 0)), 0)::INT AS total_fallback_uses,
                COALESCE(AVG(COALESCE((t.metrics ->> 'latency_ms')::DOUBLE PRECISION, 0)), 0)::DOUBLE PRECISION AS avg_latency_ms,
                COALESCE(MAX(COALESCE((t.metrics ->> 'latency_ms')::DOUBLE PRECISION, 0)), 0)::DOUBLE PRECISION AS max_latency_ms
            FROM focus_trajectory_turns t
            {where_sql}
        """
        by_status_sql = f"""
            SELECT
                t.status AS key,
                COUNT(*)::INT AS turn_count,
                COALESCE(AVG(COALESCE((t.metrics ->> 'latency_ms')::DOUBLE PRECISION, 0)), 0)::DOUBLE PRECISION AS avg_latency_ms
            FROM focus_trajectory_turns t
            {where_sql}
            GROUP BY t.status
            ORDER BY turn_count DESC, key ASC
        """
        by_scene_sql = f"""
            SELECT
                t.scene AS key,
                COUNT(*)::INT AS turn_count,
                COALESCE(AVG(COALESCE((t.metrics ->> 'latency_ms')::DOUBLE PRECISION, 0)), 0)::DOUBLE PRECISION AS avg_latency_ms
            FROM focus_trajectory_turns t
            {where_sql}
            GROUP BY t.scene
            ORDER BY turn_count DESC, key ASC
        """
        by_branch_role_sql = f"""
            SELECT
                COALESCE(t.branch_role, 'unassigned') AS key,
                COUNT(*)::INT AS turn_count
            FROM focus_trajectory_turns t
            {where_sql}
            GROUP BY COALESCE(t.branch_role, 'unassigned')
            ORDER BY turn_count DESC, key ASC
        """
        by_tool_where_sql = where_sql
        by_tool_params = dict(params)
        if step_conditions:
            by_tool_where_sql = self._append_clause(
                where_sql,
                " AND ".join(step_conditions),
                prefix="WHERE" if not where_sql else "AND",
            )
            by_tool_params.update(step_params)
        by_tool_sql = f"""
            SELECT
                s.tool AS key,
                COUNT(*)::INT AS step_count,
                COUNT(DISTINCT t.id)::INT AS turn_count,
                COALESCE(SUM(CASE WHEN s.cache_hit THEN 1 ELSE 0 END), 0)::INT AS cache_hit_steps,
                COALESCE(SUM(CASE WHEN s.fallback_used THEN 1 ELSE 0 END), 0)::INT AS fallback_steps,
                COALESCE(AVG(s.duration_ms), 0)::DOUBLE PRECISION AS avg_duration_ms
            FROM focus_trajectory_turns t
            JOIN focus_trajectory_steps s ON s.turn_id = t.id
            {by_tool_where_sql}
            GROUP BY s.tool
            ORDER BY step_count DESC, key ASC
        """

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(overview_sql, params)
                overview_row = cur.fetchone() or {}
                cur.execute(by_status_sql, params)
                by_status_rows = cur.fetchall()
                cur.execute(by_scene_sql, params)
                by_scene_rows = cur.fetchall()
                cur.execute(by_branch_role_sql, params)
                by_branch_role_rows = cur.fetchall()
                cur.execute(by_tool_sql, by_tool_params)
                by_tool_rows = cur.fetchall()

        return {
            "overview": self._row_to_stats_row(overview_row),
            "by_status": [self._row_to_stats_row(row) for row in by_status_rows],
            "by_scene": [self._row_to_stats_row(row) for row in by_scene_rows],
            "by_branch_role": [self._row_to_stats_row(row) for row in by_branch_role_rows],
            "by_tool": [self._row_to_stats_row(row) for row in by_tool_rows],
        }

    def stats(self, *, filters: dict[str, Any]) -> dict[str, Any]:
        return self.get_turn_stats(filters=filters)

    @staticmethod
    def _turn_params(record: TurnTrajectoryRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "schema_version": record.schema_version,
            "kind": record.kind,
            "status": record.status,
            "thread_id": record.thread_id,
            "root_thread_id": record.root_thread_id,
            "parent_thread_id": record.parent_thread_id,
            "branch_id": record.branch_id,
            "branch_role": record.branch_role,
            "user_id_hash": record.user_id_hash,
            "scene": record.scene,
            "turn_index": record.turn_index,
            "task_brief": record.task_brief,
            "user_message": record.user_message,
            "answer": record.answer,
            "selected_model": record.selected_model,
            "selected_thinking_mode": record.selected_thinking_mode,
            "plan": Jsonb(record.plan),
            "reflection": Jsonb(record.reflection),
            "plan_meta": Jsonb(record.plan_meta),
            "metrics": Jsonb(record.metrics),
            "error": record.error,
            "started_at": record.started_at,
            "finished_at": record.finished_at,
        }

    @staticmethod
    def _normalize_query(
        query: TrajectoryTurnQuery | dict[str, Any] | None,
        *,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> TrajectoryTurnQuery:
        if isinstance(query, TrajectoryTurnQuery):
            normalized = replace(query)
        else:
            merged_filters = dict(filters or {})
            if isinstance(query, dict):
                merged_filters.update(query)
            normalized = TrajectoryTurnQuery(**PostgresTrajectoryRepository._query_kwargs_from_filters(merged_filters))
        if limit is not None:
            normalized.limit = limit
        if offset is not None:
            normalized.offset = offset
        return normalized

    def _build_turn_select_sql(
        self,
        *,
        query: TrajectoryTurnQuery,
        select_clause: str,
    ) -> tuple[str, dict[str, Any]]:
        where_sql, params, _, _ = self._build_turn_where_clause(query)
        order_direction = "DESC" if query.newest_first else "ASC"
        sql = f"""
            {select_clause}
            FROM focus_trajectory_turns t
            {where_sql}
            ORDER BY t.created_at {order_direction}, t.id {order_direction}
        """
        if query.limit is not None:
            sql += "\nLIMIT %(limit)s"
            params["limit"] = max(int(query.limit), 0)
        if query.offset:
            sql += "\nOFFSET %(offset)s"
            params["offset"] = max(int(query.offset), 0)
        return sql, params

    def _build_turn_where_clause(
        self,
        query: TrajectoryTurnQuery,
    ) -> tuple[str, dict[str, Any], list[str], dict[str, Any]]:
        turn_conditions: list[str] = []
        step_conditions: list[str] = []
        params: dict[str, Any] = {}
        step_params: dict[str, Any] = {}

        self._add_scalar_filter(turn_conditions, params, "turn_ids", "t.id", query.turn_ids)
        self._add_scalar_filter(turn_conditions, params, "thread_id", "t.thread_id", query.thread_id)
        self._add_scalar_filter(turn_conditions, params, "root_thread_id", "t.root_thread_id", query.root_thread_id)
        self._add_scalar_filter(turn_conditions, params, "parent_thread_id", "t.parent_thread_id", query.parent_thread_id)
        self._add_scalar_filter(turn_conditions, params, "branch_id", "t.branch_id", query.branch_id)
        self._add_scalar_filter(turn_conditions, params, "branch_role", "t.branch_role", query.branch_role)
        self._add_scalar_filter(turn_conditions, params, "status", "t.status", query.status)
        self._add_scalar_filter(turn_conditions, params, "scene", "t.scene", query.scene)
        self._add_scalar_filter(turn_conditions, params, "kind", "t.kind", query.kind)
        self._add_scalar_filter(turn_conditions, params, "selected_model", "t.selected_model", query.selected_model)

        if query.since is not None:
            params["since"] = query.since
            turn_conditions.append("t.created_at >= %(since)s")
        if query.until is not None:
            params["until"] = query.until
            turn_conditions.append("t.created_at <= %(until)s")
        if query.min_latency_ms is not None:
            params["min_latency_ms"] = float(query.min_latency_ms)
            turn_conditions.append("COALESCE((t.metrics ->> 'latency_ms')::DOUBLE PRECISION, 0) >= %(min_latency_ms)s")
        if query.max_latency_ms is not None:
            params["max_latency_ms"] = float(query.max_latency_ms)
            turn_conditions.append("COALESCE((t.metrics ->> 'latency_ms')::DOUBLE PRECISION, 0) <= %(max_latency_ms)s")
        if query.min_tool_calls is not None:
            params["min_tool_calls"] = int(query.min_tool_calls)
            turn_conditions.append("COALESCE((t.metrics ->> 'tool_calls')::INT, 0) >= %(min_tool_calls)s")
        if query.max_tool_calls is not None:
            params["max_tool_calls"] = int(query.max_tool_calls)
            turn_conditions.append("COALESCE((t.metrics ->> 'tool_calls')::INT, 0) <= %(max_tool_calls)s")

        self._add_scalar_filter(step_conditions, step_params, "step_tool", "s.tool", query.tool)
        if query.fallback_used is not None:
            step_params["step_fallback_used"] = query.fallback_used
            step_conditions.append("s.fallback_used = %(step_fallback_used)s")
        if query.cache_hit is not None:
            step_params["step_cache_hit"] = query.cache_hit
            step_conditions.append("s.cache_hit = %(step_cache_hit)s")
        if query.has_error is True:
            turn_conditions.append(
                """
                (
                    COALESCE(t.error, '') <> ''
                    OR EXISTS (
                        SELECT 1
                        FROM focus_trajectory_steps es
                        WHERE es.turn_id = t.id AND COALESCE(es.error, '') <> ''
                    )
                )
                """.strip()
            )
        elif query.has_error is False:
            turn_conditions.append(
                """
                (
                    COALESCE(t.error, '') = ''
                    AND NOT EXISTS (
                        SELECT 1
                        FROM focus_trajectory_steps es
                        WHERE es.turn_id = t.id AND COALESCE(es.error, '') <> ''
                    )
                )
                """.strip()
            )

        if step_conditions:
            params.update(step_params)
            turn_conditions.append(
                f"EXISTS (SELECT 1 FROM focus_trajectory_steps s WHERE s.turn_id = t.id AND {' AND '.join(step_conditions)})"
            )

        where_sql = ""
        if turn_conditions:
            where_sql = "WHERE " + " AND ".join(turn_conditions)
        return where_sql, params, step_conditions, step_params

    @staticmethod
    def _append_clause(base: str, clause: str, *, prefix: str) -> str:
        if not clause:
            return base
        if not base:
            return f"{prefix} {clause}"
        return f"{base} {prefix} {clause}"

    @staticmethod
    def _add_scalar_filter(
        conditions: list[str],
        params: dict[str, Any],
        param_name: str,
        column: str,
        value: Any,
    ) -> None:
        if value is None:
            return
        if isinstance(value, str):
            params[param_name] = value
            conditions.append(f"{column} = %({param_name})s")
            return
        if isinstance(value, Sequence):
            normalized = [item for item in value if item is not None]
            if not normalized:
                return
            params[param_name] = normalized
            conditions.append(f"{column} = ANY(%({param_name})s)")
            return
        params[param_name] = value
        conditions.append(f"{column} = %({param_name})s")

    @staticmethod
    def _row_to_turn_summary(row: dict[str, Any]) -> dict[str, Any]:
        metrics = _as_dict(row.get("metrics"))
        return {
            "id": str(row["id"]),
            "schema_version": int(row["schema_version"]),
            "kind": str(row["kind"]),
            "status": str(row["status"]),
            "thread_id": str(row["thread_id"]),
            "root_thread_id": str(row["root_thread_id"]),
            "parent_thread_id": _optional_text(row.get("parent_thread_id")),
            "branch_id": _optional_text(row.get("branch_id")),
            "branch_role": _optional_text(row.get("branch_role")),
            "scene": str(row["scene"]),
            "turn_index": _optional_int(row.get("turn_index")),
            "task_brief": _optional_text(row.get("task_brief")),
            "user_message": _optional_text(row.get("user_message")),
            "answer": _optional_text(row.get("answer")),
            "selected_model": _optional_text(row.get("selected_model")),
            "selected_thinking_mode": _optional_text(row.get("selected_thinking_mode")),
            "error": _optional_text(row.get("error")),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "created_at": row.get("created_at"),
            "metrics": metrics,
            "plan_meta": _as_dict(row.get("plan_meta")),
            "latency_ms": float(metrics.get("latency_ms") or 0.0),
            "tool_calls": int(metrics.get("tool_calls") or 0),
            "llm_calls": int(metrics.get("llm_calls") or 0),
            "cache_hits": int(metrics.get("cache_hits") or 0),
            "fallback_uses": int(metrics.get("fallback_uses") or 0),
        }

    @staticmethod
    def _row_to_turn_record(
        row: dict[str, Any],
        step_rows: Sequence[dict[str, Any]] | None = None,
    ) -> TurnTrajectoryRecord:
        return TurnTrajectoryRecord(
            id=str(row["id"]),
            schema_version=int(row["schema_version"]),
            kind=str(row["kind"]),
            status=str(row["status"]),
            thread_id=str(row["thread_id"]),
            root_thread_id=str(row["root_thread_id"]),
            parent_thread_id=_optional_text(row.get("parent_thread_id")),
            branch_id=_optional_text(row.get("branch_id")),
            branch_role=_optional_text(row.get("branch_role")),
            user_id_hash=str(row["user_id_hash"]),
            scene=str(row["scene"]),
            turn_index=_optional_int(row.get("turn_index")),
            task_brief=_optional_text(row.get("task_brief")),
            user_message=_optional_text(row.get("user_message")),
            answer=_optional_text(row.get("answer")),
            selected_model=_optional_text(row.get("selected_model")),
            selected_thinking_mode=_optional_text(row.get("selected_thinking_mode")),
            plan=row.get("plan"),
            reflection=row.get("reflection"),
            plan_meta=_as_dict(row.get("plan_meta")),
            metrics=_as_dict(row.get("metrics")),
            error=_optional_text(row.get("error")),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            trajectory=[PostgresTrajectoryRepository._step_dict_to_model(step_row) for step_row in (step_rows or [])],
        )

    @staticmethod
    def _row_to_step_dict(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "turn_id": str(row["turn_id"]),
            "step_index": int(row["step_index"]),
            "tool": str(row["tool"]),
            "args": _as_dict(row.get("args")),
            "observation": str(row.get("observation") or ""),
            "observation_truncated": bool(row.get("observation_truncated", False)),
            "duration_ms": float(row.get("duration_ms") or 0.0),
            "error": _optional_text(row.get("error")),
            "cache_hit": bool(row.get("cache_hit", False)),
            "fallback_used": bool(row.get("fallback_used", False)),
            "fallback_group": _optional_text(row.get("fallback_group")),
            "parallel_batch_size": _optional_int(row.get("parallel_batch_size")),
            "runtime": _as_dict(row.get("runtime")),
            "created_at": row.get("created_at"),
        }

    @staticmethod
    def _step_dict_to_model(step_row: dict[str, Any]) -> TrajectoryStep:
        return TrajectoryStep(
            tool=str(step_row["tool"]),
            args=_as_dict(step_row.get("args")),
            observation=str(step_row.get("observation") or ""),
            duration_ms=float(step_row.get("duration_ms") or 0.0),
            error=_optional_text(step_row.get("error")),
            cache_hit=bool(step_row.get("cache_hit", False)),
            fallback_used=bool(step_row.get("fallback_used", False)),
            fallback_group=_optional_text(step_row.get("fallback_group")),
            parallel_batch_size=_optional_int(step_row.get("parallel_batch_size")),
            runtime=_as_dict(step_row.get("runtime")),
            observation_truncated=bool(step_row.get("observation_truncated", False)),
        )

    @staticmethod
    def _row_to_stats_row(row: dict[str, Any]) -> dict[str, Any]:
        return {str(key): value for key, value in (row or {}).items()}

    @staticmethod
    def _query_kwargs_from_filters(filters: dict[str, Any]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        if "turn_id" in filters and filters["turn_id"] is not None:
            parsed["turn_ids"] = [str(filters["turn_id"])]
        if "turn_ids" in filters and filters["turn_ids"] is not None:
            parsed["turn_ids"] = list(filters["turn_ids"])
        for key in (
            "thread_id",
            "root_thread_id",
            "parent_thread_id",
            "branch_id",
            "branch_role",
            "status",
            "scene",
            "kind",
            "tool",
            "selected_model",
            "fallback_used",
            "cache_hit",
            "has_error",
            "min_latency_ms",
            "max_latency_ms",
            "min_tool_calls",
            "max_tool_calls",
        ):
            if key in filters and filters[key] is not None:
                parsed[key] = filters[key]
        if "model" in filters and filters["model"] is not None and "selected_model" not in parsed:
            parsed["selected_model"] = filters["model"]
        since_value = filters.get("since", filters.get("started_after"))
        until_value = filters.get("until", filters.get("started_before"))
        if since_value is not None:
            parsed["since"] = _parse_datetime_like(since_value)
        if until_value is not None:
            parsed["until"] = _parse_datetime_like(until_value)
        return parsed


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _iso_datetime(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return _optional_text(value)


def _parse_datetime_like(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
