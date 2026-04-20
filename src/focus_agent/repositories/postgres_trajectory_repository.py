from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ..observability.trajectory import TurnTrajectoryRecord


class PostgresTrajectoryRepository:
    def __init__(self, database_uri: str):
        self.database_uri = database_uri

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
