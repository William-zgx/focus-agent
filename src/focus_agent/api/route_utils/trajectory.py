from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from focus_agent.core.repo_call import has_repo_method
from focus_agent.engine.runtime import AppRuntime
from focus_agent.repositories.postgres_trajectory_repository import (
    PostgresTrajectoryRepository,
    TrajectoryTurnQuery,
)

from ..contracts import (
    TrajectoryBatchReplaySummaryResponse,
    TrajectoryReplayResponse,
    TrajectoryStatsBucketResponse,
    TrajectoryStatsOverviewResponse,
    TrajectoryStepResponse,
    TrajectoryTurnDetailResponse,
    TrajectoryTurnStatsResponse,
    TrajectoryTurnSummaryResponse,
)


def _as_scalar_or_sequence(values: Sequence[str] | None) -> str | list[str] | None:
    if not values:
        return None
    normalized = [str(value).strip() for value in values if str(value).strip()]
    if not normalized:
        return None
    if len(normalized) == 1:
        return normalized[0]
    return normalized


def _trajectory_query_from_request(
    *,
    turn_ids: Sequence[str] | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    thread_id: str | None = None,
    root_thread_id: str | None = None,
    parent_thread_id: str | None = None,
    branch_id: str | None = None,
    branch_role: Sequence[str] | None = None,
    status: Sequence[str] | None = None,
    scene: Sequence[str] | None = None,
    kind: Sequence[str] | None = None,
    tool: Sequence[str] | None = None,
    model: Sequence[str] | None = None,
    fallback_used: bool | None = None,
    cache_hit: bool | None = None,
    has_error: bool | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    min_latency_ms: float | None = None,
    max_latency_ms: float | None = None,
    min_tool_calls: int | None = None,
    max_tool_calls: int | None = None,
    limit: int | None = None,
    offset: int = 0,
    newest_first: bool = True,
) -> TrajectoryTurnQuery:
    return TrajectoryTurnQuery(
        turn_ids=[str(turn_id) for turn_id in turn_ids or [] if str(turn_id).strip()] or None,
        request_id=request_id,
        trace_id=trace_id,
        thread_id=thread_id,
        root_thread_id=root_thread_id,
        parent_thread_id=parent_thread_id,
        branch_id=branch_id,
        branch_role=_as_scalar_or_sequence(branch_role),
        status=_as_scalar_or_sequence(status),
        scene=_as_scalar_or_sequence(scene),
        kind=_as_scalar_or_sequence(kind),
        tool=_as_scalar_or_sequence(tool),
        selected_model=_as_scalar_or_sequence(model),
        fallback_used=fallback_used,
        cache_hit=cache_hit,
        has_error=has_error,
        since=started_after,
        until=started_before,
        min_latency_ms=min_latency_ms,
        max_latency_ms=max_latency_ms,
        min_tool_calls=min_tool_calls,
        max_tool_calls=max_tool_calls,
        limit=limit,
        offset=offset,
        newest_first=newest_first,
    )


_TRAJECTORY_REPOSITORY_METHODS = (
    "list_turns",
    "get_turn",
    "list_steps_by_turn_ids",
    "get_turn_stats",
)


def _get_trajectory_repository(runtime: AppRuntime) -> PostgresTrajectoryRepository | Any:
    maybe_repository = _maybe_get_trajectory_repository(runtime)
    if maybe_repository is not None:
        return maybe_repository
    raise HTTPException(
        status_code=503,
        detail=(
            "Trajectory observability requires a configured Postgres database "
            "or an initialized trajectory recorder."
        ),
    )


def _build_trajectory_summary_response(item: dict[str, Any]) -> TrajectoryTurnSummaryResponse:
    return TrajectoryTurnSummaryResponse.model_validate(item)


def _build_trajectory_detail_response(
    *,
    record: Any,
    step_rows: Sequence[dict[str, Any]],
    created_at: Any = None,
) -> TrajectoryTurnDetailResponse:
    metrics = dict(getattr(record, "metrics", {}) or {})
    plan_meta = dict(getattr(record, "plan_meta", {}) or {})
    task_outcome, tool_outcomes = _outcome_projection(plan_meta)
    payload = {
        "id": str(record.id),
        "schema_version": int(record.schema_version),
        "kind": str(record.kind),
        "status": str(record.status),
        "thread_id": str(record.thread_id),
        "root_thread_id": str(record.root_thread_id),
        "request_id": getattr(record, "request_id", None),
        "trace_id": getattr(record, "trace_id", None),
        "root_span_id": getattr(record, "root_span_id", None),
        "environment": getattr(record, "environment", None),
        "deployment": getattr(record, "deployment", None),
        "app_version": getattr(record, "app_version", None),
        "parent_thread_id": record.parent_thread_id,
        "branch_id": record.branch_id,
        "branch_role": record.branch_role,
        "user_id_hash": str(record.user_id_hash),
        "scene": str(record.scene),
        "turn_index": record.turn_index,
        "task_brief": record.task_brief,
        "user_message": record.user_message,
        "answer": record.answer,
        "selected_model": record.selected_model,
        "selected_thinking_mode": record.selected_thinking_mode,
        "plan": record.plan,
        "reflection": record.reflection,
        "plan_meta": plan_meta,
        "task_outcome": task_outcome,
        "tool_outcomes": tool_outcomes,
        "metrics": metrics,
        "error": record.error,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "created_at": created_at,
        "latency_ms": float(metrics.get("latency_ms") or 0.0),
        "tool_calls": int(metrics.get("tool_calls") or 0),
        "llm_calls": int(metrics.get("llm_calls") or 0),
        "cache_hits": int(metrics.get("cache_hits") or 0),
        "fallback_uses": int(metrics.get("fallback_uses") or 0),
        "trajectory": [TrajectoryStepResponse.model_validate(step) for step in step_rows],
    }
    return TrajectoryTurnDetailResponse.model_validate(payload)


def _outcome_projection(plan_meta: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    task_outcome = plan_meta.get("task_outcome")
    tool_outcomes = plan_meta.get("tool_outcomes")
    return (
        dict(task_outcome) if isinstance(task_outcome, dict) else None,
        [dict(item) for item in tool_outcomes if isinstance(item, dict)]
        if isinstance(tool_outcomes, list)
        else [],
    )


def _build_trajectory_stats_response(stats: dict[str, Any]) -> TrajectoryTurnStatsResponse:
    return TrajectoryTurnStatsResponse(
        overview=TrajectoryStatsOverviewResponse.model_validate(stats.get("overview") or {}),
        by_status=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_status") or [])
        ],
        by_scene=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_scene") or [])
        ],
        by_branch_role=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_branch_role") or [])
        ],
        by_model=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_model") or [])
        ],
        by_day=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_day") or [])
        ],
        by_tool=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_tool") or [])
        ],
    )


def _trajectory_filters_payload(
    *,
    turn_ids: Sequence[str] | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    thread_id: str | None = None,
    root_thread_id: str | None = None,
    parent_thread_id: str | None = None,
    branch_id: str | None = None,
    branch_role: Sequence[str] | None = None,
    status: Sequence[str] | None = None,
    scene: Sequence[str] | None = None,
    kind: Sequence[str] | None = None,
    tool: Sequence[str] | None = None,
    model: Sequence[str] | None = None,
    fallback_used: bool | None = None,
    cache_hit: bool | None = None,
    has_error: bool | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    min_latency_ms: float | None = None,
    max_latency_ms: float | None = None,
    min_tool_calls: int | None = None,
    max_tool_calls: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    normalized_turn_ids = [str(turn_id) for turn_id in turn_ids or [] if str(turn_id).strip()]
    if normalized_turn_ids:
        payload["turn_ids"] = normalized_turn_ids
    if request_id:
        payload["request_id"] = request_id
    if trace_id:
        payload["trace_id"] = trace_id
    if thread_id:
        payload["thread_id"] = thread_id
    if root_thread_id:
        payload["root_thread_id"] = root_thread_id
    if parent_thread_id:
        payload["parent_thread_id"] = parent_thread_id
    if branch_id:
        payload["branch_id"] = branch_id
    if branch_role:
        payload["branch_role"] = list(branch_role)
    if status:
        payload["status"] = list(status)
    if scene:
        payload["scene"] = list(scene)
    if kind:
        payload["kind"] = list(kind)
    if tool:
        payload["tool"] = list(tool)
    if model:
        payload["model"] = list(model)
    if fallback_used is not None:
        payload["fallback_used"] = fallback_used
    if cache_hit is not None:
        payload["cache_hit"] = cache_hit
    if has_error is not None:
        payload["has_error"] = has_error
    if started_after is not None:
        payload["started_after"] = started_after.isoformat()
    if started_before is not None:
        payload["started_before"] = started_before.isoformat()
    if min_latency_ms is not None:
        payload["min_latency_ms"] = min_latency_ms
    if max_latency_ms is not None:
        payload["max_latency_ms"] = max_latency_ms
    if min_tool_calls is not None:
        payload["min_tool_calls"] = min_tool_calls
    if max_tool_calls is not None:
        payload["max_tool_calls"] = max_tool_calls
    return payload


def _trajectory_filters_from_batch_payload(payload: Any) -> dict[str, Any]:
    return _trajectory_filters_payload(
        turn_ids=payload.turn_ids,
        request_id=payload.request_id,
        trace_id=payload.trace_id,
        thread_id=payload.thread_id,
        root_thread_id=payload.root_thread_id,
        parent_thread_id=payload.parent_thread_id,
        branch_id=payload.branch_id,
        branch_role=payload.branch_role,
        status=payload.status,
        scene=payload.scene,
        kind=payload.kind,
        tool=payload.tool,
        model=payload.model,
        fallback_used=payload.fallback_used,
        cache_hit=payload.cache_hit,
        has_error=payload.has_error,
        started_after=payload.started_after,
        started_before=payload.started_before,
        min_latency_ms=payload.min_latency_ms,
        max_latency_ms=payload.max_latency_ms,
        min_tool_calls=payload.min_tool_calls,
        max_tool_calls=payload.max_tool_calls,
    )


def _trajectory_query_from_batch_payload(payload: Any) -> TrajectoryTurnQuery:
    return _trajectory_query_from_request(
        turn_ids=payload.turn_ids,
        request_id=payload.request_id,
        trace_id=payload.trace_id,
        thread_id=payload.thread_id,
        root_thread_id=payload.root_thread_id,
        parent_thread_id=payload.parent_thread_id,
        branch_id=payload.branch_id,
        branch_role=payload.branch_role,
        status=payload.status,
        scene=payload.scene,
        kind=payload.kind,
        tool=payload.tool,
        model=payload.model,
        fallback_used=payload.fallback_used,
        cache_hit=payload.cache_hit,
        has_error=payload.has_error,
        started_after=payload.started_after,
        started_before=payload.started_before,
        min_latency_ms=payload.min_latency_ms,
        max_latency_ms=payload.max_latency_ms,
        min_tool_calls=payload.min_tool_calls,
        max_tool_calls=payload.max_tool_calls,
        limit=payload.limit,
        offset=payload.offset,
        newest_first=payload.newest_first,
    )


def _export_trajectory_records(repo: Any, query: TrajectoryTurnQuery) -> list[dict[str, Any]]:
    if not has_repo_method(repo, "export_turns"):
        raise HTTPException(
            status_code=503,
            detail="Trajectory batch observability requires a repository that can export turns.",
        )
    return [dict(record) for record in repo.export_turns(query)]


def _build_batch_replay_summary(
    results: Sequence[TrajectoryReplayResponse],
) -> TrajectoryBatchReplaySummaryResponse:
    return TrajectoryBatchReplaySummaryResponse(
        total=len(results),
        passed=sum(1 for item in results if item.comparison.replay_passed),
        failed=sum(1 for item in results if not item.comparison.replay_passed),
        source_failed=sum(1 for item in results if item.comparison.source_failed),
        tool_path_changed=sum(1 for item in results if item.comparison.tool_path_changed),
    )


def _maybe_get_trajectory_repository(
    runtime: AppRuntime | Any,
) -> PostgresTrajectoryRepository | Any | None:
    repository = getattr(runtime, "trajectory_recorder", None)
    if repository is not None and all(
        has_repo_method(repository, name) for name in _TRAJECTORY_REPOSITORY_METHODS
    ):
        return repository
    database_uri = getattr(getattr(runtime, "settings", None), "database_uri", None)
    if database_uri:
        return PostgresTrajectoryRepository(database_uri)
    return None


__all__ = [
    "_as_scalar_or_sequence",
    "_trajectory_query_from_request",
    "_get_trajectory_repository",
    "_build_trajectory_summary_response",
    "_build_trajectory_detail_response",
    "_build_trajectory_stats_response",
    "_trajectory_filters_payload",
    "_trajectory_filters_from_batch_payload",
    "_trajectory_query_from_batch_payload",
    "_export_trajectory_records",
    "_build_batch_replay_summary",
    "_maybe_get_trajectory_repository",
    "TrajectoryTurnQuery",
]
