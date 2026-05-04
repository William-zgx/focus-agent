from __future__ import annotations

import psycopg


class PostgresTrajectorySchemaMixin:
    database_uri: str

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
                        request_id TEXT,
                        trace_id TEXT,
                        root_span_id TEXT,
                        environment TEXT,
                        deployment TEXT,
                        app_version TEXT,
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
                for column_name, column_type in (
                    ("request_id", "TEXT"),
                    ("trace_id", "TEXT"),
                    ("root_span_id", "TEXT"),
                    ("environment", "TEXT"),
                    ("deployment", "TEXT"),
                    ("app_version", "TEXT"),
                ):
                    cur.execute(
                        f"""
                        ALTER TABLE focus_trajectory_turns
                        ADD COLUMN IF NOT EXISTS {column_name} {column_type}
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
                    CREATE INDEX IF NOT EXISTS idx_focus_traj_turns_request_id
                    ON focus_trajectory_turns(request_id)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_focus_traj_turns_trace_id
                    ON focus_trajectory_turns(trace_id)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_focus_traj_steps_turn
                    ON focus_trajectory_steps(turn_id, step_index)
                    """
                )
