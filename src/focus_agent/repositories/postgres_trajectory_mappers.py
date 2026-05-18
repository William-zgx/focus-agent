from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from ..observability.trajectory import TrajectoryStep, TurnTrajectoryRecord


class PostgresTrajectoryMapperMixin:
    @staticmethod
    def _turn_params(record: TurnTrajectoryRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "schema_version": record.schema_version,
            "kind": record.kind,
            "status": record.status,
            "thread_id": record.thread_id,
            "root_thread_id": record.root_thread_id,
            "request_id": record.request_id,
            "trace_id": record.trace_id,
            "root_span_id": record.root_span_id,
            "environment": record.environment,
            "deployment": record.deployment,
            "app_version": record.app_version,
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
    def _step_params(turn_id: str, step_index: int, step: TrajectoryStep) -> dict[str, Any]:
        return {
            "turn_id": turn_id,
            "step_index": step_index,
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
        }

    @staticmethod
    def _row_to_turn_summary(row: dict[str, Any]) -> dict[str, Any]:
        metrics = as_dict(row.get("metrics"))
        return {
            "id": str(row["id"]),
            "schema_version": int(row["schema_version"]),
            "kind": str(row["kind"]),
            "status": str(row["status"]),
            "thread_id": str(row["thread_id"]),
            "root_thread_id": str(row["root_thread_id"]),
            "request_id": optional_text(row.get("request_id")),
            "trace_id": optional_text(row.get("trace_id")),
            "root_span_id": optional_text(row.get("root_span_id")),
            "environment": optional_text(row.get("environment")),
            "deployment": optional_text(row.get("deployment")),
            "app_version": optional_text(row.get("app_version")),
            "parent_thread_id": optional_text(row.get("parent_thread_id")),
            "branch_id": optional_text(row.get("branch_id")),
            "branch_role": optional_text(row.get("branch_role")),
            "scene": str(row["scene"]),
            "turn_index": optional_int(row.get("turn_index")),
            "task_brief": optional_text(row.get("task_brief")),
            "user_message": optional_text(row.get("user_message")),
            "answer": optional_text(row.get("answer")),
            "selected_model": optional_text(row.get("selected_model")),
            "selected_thinking_mode": optional_text(row.get("selected_thinking_mode")),
            "error": optional_text(row.get("error")),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
            "created_at": row.get("created_at"),
            "metrics": metrics,
            "plan_meta": as_dict(row.get("plan_meta")),
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
            request_id=optional_text(row.get("request_id")),
            trace_id=optional_text(row.get("trace_id")),
            root_span_id=optional_text(row.get("root_span_id")),
            environment=optional_text(row.get("environment")),
            deployment=optional_text(row.get("deployment")),
            app_version=optional_text(row.get("app_version")),
            parent_thread_id=optional_text(row.get("parent_thread_id")),
            branch_id=optional_text(row.get("branch_id")),
            branch_role=optional_text(row.get("branch_role")),
            user_id_hash=str(row["user_id_hash"]),
            scene=str(row["scene"]),
            turn_index=optional_int(row.get("turn_index")),
            task_brief=optional_text(row.get("task_brief")),
            user_message=optional_text(row.get("user_message")),
            answer=optional_text(row.get("answer")),
            selected_model=optional_text(row.get("selected_model")),
            selected_thinking_mode=optional_text(row.get("selected_thinking_mode")),
            plan=row.get("plan"),
            reflection=row.get("reflection"),
            plan_meta=as_dict(row.get("plan_meta")),
            metrics=as_dict(row.get("metrics")),
            error=optional_text(row.get("error")),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            trajectory=[
                PostgresTrajectoryMapperMixin._step_dict_to_model(step_row)
                for step_row in (step_rows or [])
            ],
        )

    @staticmethod
    def _row_to_step_dict(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "turn_id": str(row["turn_id"]),
            "step_index": int(row["step_index"]),
            "tool": str(row["tool"]),
            "args": as_dict(row.get("args")),
            "observation": str(row.get("observation") or ""),
            "observation_truncated": bool(row.get("observation_truncated", False)),
            "duration_ms": float(row.get("duration_ms") or 0.0),
            "error": optional_text(row.get("error")),
            "cache_hit": bool(row.get("cache_hit", False)),
            "fallback_used": bool(row.get("fallback_used", False)),
            "fallback_group": optional_text(row.get("fallback_group")),
            "parallel_batch_size": optional_int(row.get("parallel_batch_size")),
            "runtime": as_dict(row.get("runtime")),
            "created_at": row.get("created_at"),
        }

    @staticmethod
    def _step_dict_to_model(step_row: dict[str, Any]) -> TrajectoryStep:
        return TrajectoryStep(
            tool=str(step_row["tool"]),
            args=as_dict(step_row.get("args")),
            observation=str(step_row.get("observation") or ""),
            duration_ms=float(step_row.get("duration_ms") or 0.0),
            error=optional_text(step_row.get("error")),
            cache_hit=bool(step_row.get("cache_hit", False)),
            fallback_used=bool(step_row.get("fallback_used", False)),
            fallback_group=optional_text(step_row.get("fallback_group")),
            parallel_batch_size=optional_int(step_row.get("parallel_batch_size")),
            runtime=as_dict(step_row.get("runtime")),
            observation_truncated=bool(step_row.get("observation_truncated", False)),
        )

    @staticmethod
    def _row_to_stats_row(row: dict[str, Any]) -> dict[str, Any]:
        return {str(key): value for key, value in (row or {}).items()}

    @staticmethod
    def _iso_datetime(value: Any) -> str | None:
        return iso_datetime(value)


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def iso_datetime(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return optional_text(value)


def parse_datetime_like(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
