from __future__ import annotations

from typing import Any, Sequence

from focus_agent.engine.runtime import AppRuntime
from focus_agent.repositories.postgres_trajectory_repository import TrajectoryTurnQuery

from .trajectory import _maybe_get_trajectory_repository


def _role_route_decision_items(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        plan_meta = dict(row.get("plan_meta") or {})
        role_route_plan = plan_meta.get("role_route_plan")
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
        payload = plan_meta.get(key)
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
        payload: Any = plan_meta
        for part in key.split("."):
            payload = payload.get(part) if isinstance(payload, dict) else None
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
    metrics = {
        "memory_promotions": 0,
        "memory_conflicts": 0,
        "tool_router_denied": 0,
        "tool_router_enforced": 0,
        "agent_delegation_runs": 0,
        "critic_rejects": 0,
        "agent_review_pending": 0,
        "model_router_fallback": 0,
        "agent_failures": 0,
        "context_artifact_refs": 0,
        "context_over_budget": 0,
        "agent_task_ledger_tasks": 0,
        "delegated_artifacts": 0,
        "critic_gate_rejected": 0,
    }
    for row in rows:
        plan_meta = dict(row.get("plan_meta") or {})
        memory_decision = plan_meta.get("memory_curator_decision")
        if isinstance(memory_decision, dict):
            metrics["memory_promotions"] += len(memory_decision.get("promoted_memory_ids") or [])
            metrics["memory_conflicts"] += len(memory_decision.get("conflicts") or [])
        tool_plan = plan_meta.get("tool_route_plan")
        if isinstance(tool_plan, dict):
            metrics["tool_router_denied"] += len(tool_plan.get("denied_tools") or [])
            metrics["tool_router_enforced"] += 1 if tool_plan.get("enforce") else 0
        delegation_plan = plan_meta.get("agent_delegation_plan")
        if isinstance(delegation_plan, dict):
            metrics["agent_delegation_runs"] += len(delegation_plan.get("runs") or [])
        model_decision = plan_meta.get("model_route_decision")
        if isinstance(model_decision, dict):
            metrics["model_router_fallback"] += 1 if model_decision.get("fallback_used") else 0
        failures = plan_meta.get("agent_failure_records")
        if isinstance(failures, list):
            metrics["agent_failures"] += len(failures)
            metrics["critic_rejects"] += len(
                [item for item in failures if isinstance(item, dict) and item.get("failure_type") == "critic_rejected"]
            )
        review_queue = plan_meta.get("agent_review_queue")
        if isinstance(review_queue, list):
            metrics["agent_review_pending"] += len(
                [item for item in review_queue if isinstance(item, dict) and item.get("status") == "pending"]
            )
        context_refs = plan_meta.get("context_artifact_refs")
        if isinstance(context_refs, list):
            metrics["context_artifact_refs"] += len(context_refs)
        context_budget = plan_meta.get("context_budget_decision")
        if isinstance(context_budget, dict):
            metrics["context_over_budget"] += 1 if int(context_budget.get("over_budget_chars") or 0) > 0 else 0
        task_ledger = plan_meta.get("agent_task_ledger")
        if isinstance(task_ledger, dict):
            metrics["agent_task_ledger_tasks"] += len(task_ledger.get("tasks") or [])
        delegated_artifacts = plan_meta.get("delegated_artifacts")
        if isinstance(delegated_artifacts, list):
            metrics["delegated_artifacts"] += len(delegated_artifacts)
        critic_gate = plan_meta.get("critic_gate_result")
        if isinstance(critic_gate, dict):
            metrics["critic_gate_rejected"] += len(critic_gate.get("rejected_artifact_ids") or [])
    return metrics


__all__ = [
    "_agent_governance_metrics_from_turns",
    "_list_plan_meta_decisions",
    "_list_plan_meta_list_items",
    "_list_response_fields",
    "_plan_meta_items",
    "_role_route_decision_items",
]
