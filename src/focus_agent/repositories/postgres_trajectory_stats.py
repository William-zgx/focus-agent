from __future__ import annotations

from dataclasses import replace
from typing import Any


class PostgresTrajectoryStatsMixin:
    _TOKEN_USAGE_INT_RE = r"^[0-9]+([.]0+)?$"

    _TOKEN_USAGE_SELECT_SQL = f"""
        COALESCE(
            SUM(
                COALESCE(
                    CASE
                        WHEN t.metrics ->> 'input_tokens' ~ '{_TOKEN_USAGE_INT_RE}' THEN (t.metrics ->> 'input_tokens')::NUMERIC::BIGINT
                        WHEN t.metrics ->> 'prompt_tokens' ~ '{_TOKEN_USAGE_INT_RE}' THEN (t.metrics ->> 'prompt_tokens')::NUMERIC::BIGINT
                        WHEN t.metrics ->> 'prompt_token_count' ~ '{_TOKEN_USAGE_INT_RE}' THEN (t.metrics ->> 'prompt_token_count')::NUMERIC::BIGINT
                        ELSE 0
                    END,
                    0
                )
            ),
            0
        )::BIGINT AS input_tokens,
        COALESCE(
            SUM(
                COALESCE(
                    CASE
                        WHEN t.metrics ->> 'output_tokens' ~ '{_TOKEN_USAGE_INT_RE}' THEN (t.metrics ->> 'output_tokens')::NUMERIC::BIGINT
                        WHEN t.metrics ->> 'completion_tokens' ~ '{_TOKEN_USAGE_INT_RE}' THEN (t.metrics ->> 'completion_tokens')::NUMERIC::BIGINT
                        WHEN t.metrics ->> 'completion_token_count' ~ '{_TOKEN_USAGE_INT_RE}' THEN (t.metrics ->> 'completion_token_count')::NUMERIC::BIGINT
                        ELSE 0
                    END,
                    0
                )
            ),
            0
        )::BIGINT AS output_tokens,
        COALESCE(
            SUM(
                COALESCE(
                    CASE
                        WHEN t.metrics ->> 'total_tokens' ~ '{_TOKEN_USAGE_INT_RE}' THEN NULLIF((t.metrics ->> 'total_tokens')::NUMERIC::BIGINT, 0)
                        WHEN t.metrics ->> 'total_token_count' ~ '{_TOKEN_USAGE_INT_RE}' THEN NULLIF((t.metrics ->> 'total_token_count')::NUMERIC::BIGINT, 0)
                        ELSE NULL
                    END,
                    COALESCE(
                        CASE
                            WHEN t.metrics ->> 'input_tokens' ~ '{_TOKEN_USAGE_INT_RE}' THEN (t.metrics ->> 'input_tokens')::NUMERIC::BIGINT
                            WHEN t.metrics ->> 'prompt_tokens' ~ '{_TOKEN_USAGE_INT_RE}' THEN (t.metrics ->> 'prompt_tokens')::NUMERIC::BIGINT
                            WHEN t.metrics ->> 'prompt_token_count' ~ '{_TOKEN_USAGE_INT_RE}' THEN (t.metrics ->> 'prompt_token_count')::NUMERIC::BIGINT
                            ELSE 0
                        END,
                        0
                    )
                    + COALESCE(
                        CASE
                            WHEN t.metrics ->> 'output_tokens' ~ '{_TOKEN_USAGE_INT_RE}' THEN (t.metrics ->> 'output_tokens')::NUMERIC::BIGINT
                            WHEN t.metrics ->> 'completion_tokens' ~ '{_TOKEN_USAGE_INT_RE}' THEN (t.metrics ->> 'completion_tokens')::NUMERIC::BIGINT
                            WHEN t.metrics ->> 'completion_token_count' ~ '{_TOKEN_USAGE_INT_RE}' THEN (t.metrics ->> 'completion_token_count')::NUMERIC::BIGINT
                            ELSE 0
                        END,
                        0
                    )
                )
            ),
            0
        )::BIGINT AS total_tokens
    """

    def get_turn_stats(
        self,
        query: Any = None,
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
        by_model_sql = f"""
            SELECT
                COALESCE(t.selected_model, 'unassigned') AS key,
                COUNT(*)::INT AS turn_count,
                COALESCE(AVG(COALESCE((t.metrics ->> 'latency_ms')::DOUBLE PRECISION, 0)), 0)::DOUBLE PRECISION AS avg_latency_ms
            FROM focus_trajectory_turns t
            {where_sql}
            GROUP BY COALESCE(t.selected_model, 'unassigned')
            ORDER BY turn_count DESC, key ASC
        """
        by_day_sql = f"""
            SELECT
                TO_CHAR(DATE_TRUNC('day', t.created_at AT TIME ZONE 'UTC'), 'YYYY-MM-DD') AS key,
                COUNT(*)::INT AS turn_count,
                COALESCE(SUM(CASE WHEN t.status = 'succeeded' THEN 1 ELSE 0 END), 0)::INT AS succeeded_count,
                COALESCE(SUM(CASE WHEN t.status <> 'succeeded' THEN 1 ELSE 0 END), 0)::INT AS non_succeeded_count,
                COALESCE(AVG(COALESCE((t.metrics ->> 'latency_ms')::DOUBLE PRECISION, 0)), 0)::DOUBLE PRECISION AS avg_latency_ms
            FROM focus_trajectory_turns t
            {where_sql}
            GROUP BY DATE_TRUNC('day', t.created_at AT TIME ZONE 'UTC')
            ORDER BY key ASC
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
                cur.execute(by_model_sql, params)
                by_model_rows = cur.fetchall()
                cur.execute(by_day_sql, params)
                by_day_rows = cur.fetchall()
                cur.execute(by_tool_sql, by_tool_params)
                by_tool_rows = cur.fetchall()

        return {
            "overview": self._row_to_stats_row(overview_row),
            "by_status": [self._row_to_stats_row(row) for row in by_status_rows],
            "by_scene": [self._row_to_stats_row(row) for row in by_scene_rows],
            "by_branch_role": [self._row_to_stats_row(row) for row in by_branch_role_rows],
            "by_model": [self._row_to_stats_row(row) for row in by_model_rows],
            "by_day": [self._row_to_stats_row(row) for row in by_day_rows],
            "by_tool": [self._row_to_stats_row(row) for row in by_tool_rows],
        }

    def get_root_thread_token_usage(self, root_thread_id: str) -> dict[str, int]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT {self._TOKEN_USAGE_SELECT_SQL}
                    FROM focus_trajectory_turns t
                    WHERE t.root_thread_id = %(root_thread_id)s
                    """,
                    {"root_thread_id": str(root_thread_id)},
                )
                row = cur.fetchone() or {}
        return self._row_to_token_usage(row)

    def get_thread_token_usage_for_root(self, root_thread_id: str) -> dict[str, dict[str, int]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        t.thread_id,
                        {self._TOKEN_USAGE_SELECT_SQL}
                    FROM focus_trajectory_turns t
                    WHERE t.root_thread_id = %(root_thread_id)s
                    GROUP BY t.thread_id
                    """,
                    {"root_thread_id": str(root_thread_id)},
                )
                rows = cur.fetchall()
        return {
            str(row["thread_id"]): self._row_to_token_usage(row)
            for row in rows
            if row.get("thread_id")
        }

    def stats(self, *, filters: dict[str, Any]) -> dict[str, Any]:
        return self.get_turn_stats(filters=filters)

    @staticmethod
    def _row_to_token_usage(row: dict[str, Any]) -> dict[str, int]:
        input_tokens = max(int(row.get("input_tokens") or 0), 0)
        output_tokens = max(int(row.get("output_tokens") or 0), 0)
        total_tokens = max(int(row.get("total_tokens") or (input_tokens + output_tokens)), 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }
