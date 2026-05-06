from __future__ import annotations

from typing import Any, Sequence

from focus_agent.core.state import (
    governance_metric_defaults,
    governance_metrics_from_record_payloads,
    governance_plan_meta_payload,
)
from focus_agent.engine.runtime import AppRuntime
from focus_agent.repositories.postgres_trajectory_repository import TrajectoryTurnQuery

from .trajectory import _maybe_get_trajectory_repository


def _role_route_decision_items(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        plan_meta = dict(row.get("plan_meta") or {})
        role_route_plan = _plan_meta_governance_payload(plan_meta, "role_route_plan")
        if not isinstance(role_route_plan, dict):
            continue
        decisions = role_route_plan.get("decisions")
        if not isinstance(decisions, list):
            decisions = []
        items.append(
            {
                "turn_id": row.get("id"),
                "request_id": row.get("request_id"),
                "trace_id": row.get("trace_id"),
                "thread_id": row.get("thread_id"),
                "root_thread_id": row.get("root_thread_id"),
                "status": row.get("status"),
                "started_at": row.get("started_at"),
                "enabled": bool(role_route_plan.get("enabled", False)),
                "route_reason": role_route_plan.get("route_reason"),
                "max_parallel_runs": role_route_plan.get("max_parallel_runs"),
                "orchestrator_model_id": role_route_plan.get("orchestrator_model_id"),
                "role_count": len(decisions),
                "decisions": decisions,
            }
        )
    return items


def _list_response_fields(
    *,
    runtime: AppRuntime | Any,
    key: str,
    limit: int,
    decisions: bool = False,
) -> dict[str, Any]:
    items, available, error = (
        _list_plan_meta_decisions(runtime=runtime, key=key, limit=limit)
        if decisions
        else _list_plan_meta_list_items(runtime=runtime, key=key, limit=limit)
    )
    return {
        "items": items,
        "count": len(items),
        "trajectory_available": available,
        "trajectory_error": error,
    }


def _plan_meta_items(rows: Sequence[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        plan_meta = dict(row.get("plan_meta") or {})
        payload = _plan_meta_governance_payload(plan_meta, key)
        if not isinstance(payload, dict):
            continue
        items.append(
            {
                "turn_id": row.get("id"),
                "request_id": row.get("request_id"),
                "trace_id": row.get("trace_id"),
                "thread_id": row.get("thread_id"),
                "root_thread_id": row.get("root_thread_id"),
                "status": row.get("status"),
                "started_at": row.get("started_at"),
                **payload,
            }
        )
    return items


def _list_plan_meta_decisions(
    *,
    runtime: AppRuntime | Any,
    key: str,
    limit: int,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return [], False, None
    try:
        rows = repo.list_turns(TrajectoryTurnQuery(limit=limit, newest_first=True))
    except Exception as exc:  # noqa: BLE001
        return [], False, str(exc)
    return _plan_meta_items(rows, key), True, None


def _list_plan_meta_list_items(
    *,
    runtime: AppRuntime | Any,
    key: str,
    limit: int,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return [], False, None
    try:
        rows = repo.list_turns(TrajectoryTurnQuery(limit=limit, newest_first=True))
    except Exception as exc:  # noqa: BLE001
        return [], False, str(exc)
    items: list[dict[str, Any]] = []
    for row in rows:
        plan_meta = dict(row.get("plan_meta") or {})
        payload = _plan_meta_governance_payload(plan_meta, key)
        if not isinstance(payload, list):
            continue
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            items.append(
                {
                    "turn_id": row.get("id"),
                    "request_id": row.get("request_id"),
                    "trace_id": row.get("trace_id"),
                    "thread_id": row.get("thread_id"),
                    "root_thread_id": row.get("root_thread_id"),
                    "status": row.get("status"),
                    "started_at": row.get("started_at"),
                    **raw,
                }
            )
    return items[:limit], True, None


def _agent_governance_metrics_from_turns(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    metrics = governance_metric_defaults()
    for row in rows:
        plan_meta = dict(row.get("plan_meta") or {})
        for key, value in governance_metrics_from_record_payloads(plan_meta, include_zero=True).items():
            metrics[key] = metrics.get(key, 0) + value
    return metrics


def _plan_meta_governance_payload(plan_meta: dict[str, Any], key: str) -> Any:
    return governance_plan_meta_payload(plan_meta, key, default=None)


__all__ = [
    "_agent_governance_metrics_from_turns",
    "_list_plan_meta_decisions",
    "_list_plan_meta_list_items",
    "_list_response_fields",
    "_plan_meta_items",
    "_role_route_decision_items",
]
