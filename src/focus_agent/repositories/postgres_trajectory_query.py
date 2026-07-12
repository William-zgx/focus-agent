from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from .postgres_trajectory_mappers import parse_datetime_like


class PostgresTrajectoryQueryMixin:
    @staticmethod
    def _normalize_query(
        query: Any,
        *,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> Any:
        from .postgres_trajectory_repository import TrajectoryTurnQuery

        if isinstance(query, TrajectoryTurnQuery):
            normalized = replace(query)
        else:
            merged_filters = dict(filters or {})
            if isinstance(query, dict):
                merged_filters.update(query)
            normalized = TrajectoryTurnQuery(
                **PostgresTrajectoryQueryMixin._query_kwargs_from_filters(merged_filters)
            )
        if limit is not None:
            normalized.limit = limit
        if offset is not None:
            normalized.offset = offset
        return normalized

    def _build_turn_select_sql(
        self,
        *,
        query: Any,
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
        query: Any,
    ) -> tuple[str, dict[str, Any], list[str], dict[str, Any]]:
        turn_conditions: list[str] = []
        step_conditions: list[str] = []
        params: dict[str, Any] = {}
        step_params: dict[str, Any] = {}

        self._add_scalar_filter(turn_conditions, params, "turn_ids", "t.id", query.turn_ids)
        if query.owner_user_id is not None:
            params["owner_user_id"] = str(query.owner_user_id)
            turn_conditions.append(
                """
                EXISTS (
                    SELECT 1
                    FROM focus_thread_access ta
                    WHERE ta.thread_id = t.thread_id
                      AND ta.owner_user_id = %(owner_user_id)s
                )
                """.strip()
            )
        self._add_scalar_filter(
            turn_conditions, params, "request_id", "t.request_id", query.request_id
        )
        self._add_scalar_filter(turn_conditions, params, "trace_id", "t.trace_id", query.trace_id)
        self._add_scalar_filter(
            turn_conditions, params, "thread_id", "t.thread_id", query.thread_id
        )
        self._add_scalar_filter(
            turn_conditions, params, "root_thread_id", "t.root_thread_id", query.root_thread_id
        )
        self._add_scalar_filter(
            turn_conditions,
            params,
            "parent_thread_id",
            "t.parent_thread_id",
            query.parent_thread_id,
        )
        self._add_scalar_filter(
            turn_conditions, params, "branch_id", "t.branch_id", query.branch_id
        )
        self._add_scalar_filter(
            turn_conditions, params, "branch_role", "t.branch_role", query.branch_role
        )
        self._add_scalar_filter(turn_conditions, params, "status", "t.status", query.status)
        self._add_scalar_filter(turn_conditions, params, "scene", "t.scene", query.scene)
        self._add_scalar_filter(turn_conditions, params, "kind", "t.kind", query.kind)
        self._add_scalar_filter(
            turn_conditions, params, "selected_model", "t.selected_model", query.selected_model
        )

        if query.since is not None:
            params["since"] = query.since
            turn_conditions.append("t.created_at >= %(since)s")
        if query.until is not None:
            params["until"] = query.until
            turn_conditions.append("t.created_at <= %(until)s")
        if query.min_latency_ms is not None:
            params["min_latency_ms"] = float(query.min_latency_ms)
            turn_conditions.append(
                "COALESCE((t.metrics ->> 'latency_ms')::DOUBLE PRECISION, 0) >= %(min_latency_ms)s"
            )
        if query.max_latency_ms is not None:
            params["max_latency_ms"] = float(query.max_latency_ms)
            turn_conditions.append(
                "COALESCE((t.metrics ->> 'latency_ms')::DOUBLE PRECISION, 0) <= %(max_latency_ms)s"
            )
        if query.min_tool_calls is not None:
            params["min_tool_calls"] = int(query.min_tool_calls)
            turn_conditions.append(
                "COALESCE((t.metrics ->> 'tool_calls')::INT, 0) >= %(min_tool_calls)s"
            )
        if query.max_tool_calls is not None:
            params["max_tool_calls"] = int(query.max_tool_calls)
            turn_conditions.append(
                "COALESCE((t.metrics ->> 'tool_calls')::INT, 0) <= %(max_tool_calls)s"
            )

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
    def _query_kwargs_from_filters(filters: dict[str, Any]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        if "turn_id" in filters and filters["turn_id"] is not None:
            parsed["turn_ids"] = [str(filters["turn_id"])]
        if "turn_ids" in filters and filters["turn_ids"] is not None:
            parsed["turn_ids"] = list(filters["turn_ids"])
        for key in (
            "owner_user_id",
            "thread_id",
            "request_id",
            "trace_id",
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
            parsed["since"] = parse_datetime_like(since_value)
        if until_value is not None:
            parsed["until"] = parse_datetime_like(until_value)
        return parsed
