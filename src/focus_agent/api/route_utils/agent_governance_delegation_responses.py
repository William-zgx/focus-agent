from __future__ import annotations

from typing import Any

from focus_agent.config import Settings
from focus_agent.delegation.delegation import (
    apply_review_decision,
    build_agent_delegation_plan,
    build_model_route_decision,
    build_self_repair_preview,
)
from focus_agent.delegation.roles import AgentRole, RoleModelResolver, build_role_route_plan
from focus_agent.engine.runtime import AppRuntime

from ..contracts import (
    AgentDelegationPlanRequest,
    AgentDelegationPlanResponse,
    AgentDelegationPolicyResponse,
    AgentDelegationRunListResponse,
    AgentModelRouterDecisionListResponse,
    AgentModelRouteRequest,
    AgentModelRouteResponse,
    AgentModelRouterPolicyResponse,
    AgentReviewQueueDecisionResponse,
    AgentReviewQueueListResponse,
    AgentSelfRepairFailureListResponse,
    AgentSelfRepairPromotePreviewRequest,
    AgentSelfRepairPromotePreviewResponse,
)
from .agent_governance_role_tool_responses import _available_tool_names
from .agent_governance_trajectory_responses import _list_response_fields


def _agent_delegation_policy_response(settings: Settings | Any) -> AgentDelegationPolicyResponse:
    return AgentDelegationPolicyResponse(
        enabled=bool(getattr(settings, "agent_delegation_enabled", False)),
        enforce=bool(getattr(settings, "agent_delegation_enforce", False)),
        max_parallel_runs=max(1, int(getattr(settings, "agent_role_max_parallel_runs", 1) or 1)),
    )


def _agent_model_router_policy_response(settings: Settings | Any) -> AgentModelRouterPolicyResponse:
    resolver = RoleModelResolver(settings)
    return AgentModelRouterPolicyResponse(
        enabled=bool(getattr(settings, "agent_model_router_enabled", False)),
        mode=str(getattr(settings, "agent_model_router_mode", "observe") or "observe"),
        default_model=str(getattr(settings, "model", "")),
        helper_model=getattr(settings, "helper_model", None),
        role_models={role.value: resolver.resolve(role) for role in AgentRole},
    )


def _agent_delegation_plan_response(
    *,
    payload: AgentDelegationPlanRequest,
    runtime: AppRuntime | Any,
) -> AgentDelegationPlanResponse:
    available_tools = payload.available_tools or _available_tool_names(runtime)
    role_route = build_role_route_plan(
        settings=runtime.settings,
        task_text=payload.message,
        available_tool_names=available_tools,
        tool_policy=payload.scene,
    )
    plan = build_agent_delegation_plan(
        settings=runtime.settings,
        task_text=payload.message,
        role_route_plan=role_route.model_dump(mode="json"),
        available_tool_names=available_tools,
        tool_policy=payload.scene,
    )
    return AgentDelegationPlanResponse(
        policy=_agent_delegation_policy_response(runtime.settings),
        plan=plan.model_dump(mode="json"),
    )


def _agent_delegation_runs_response(
    *,
    runtime: AppRuntime | Any,
    limit: int,
) -> AgentDelegationRunListResponse:
    fields = _list_response_fields(runtime=runtime, key="agent_runs", limit=limit)
    if not fields["items"]:
        fields = _list_response_fields(
            runtime=runtime, key="agent_delegation_plan.runs", limit=limit
        )
    return AgentDelegationRunListResponse(**fields)


def _agent_model_route_response(
    *,
    payload: AgentModelRouteRequest,
    runtime: AppRuntime | Any,
) -> AgentModelRouteResponse:
    decision = build_model_route_decision(
        settings=runtime.settings,
        role=payload.role,
        selected_model=payload.selected_model,
        task_text=payload.task_text,
        tool_risk=payload.tool_risk,
        context_size=payload.context_size,
    )
    return AgentModelRouteResponse(decision=decision.model_dump(mode="json"))


def _agent_model_router_decisions_response(
    *,
    runtime: AppRuntime | Any,
    limit: int,
) -> AgentModelRouterDecisionListResponse:
    return AgentModelRouterDecisionListResponse(
        **_list_response_fields(
            runtime=runtime, key="model_route_decision", limit=limit, decisions=True
        )
    )


def _agent_self_repair_failures_response(
    *,
    runtime: AppRuntime | Any,
    limit: int,
) -> AgentSelfRepairFailureListResponse:
    return AgentSelfRepairFailureListResponse(
        **_list_response_fields(runtime=runtime, key="agent_failure_records", limit=limit)
    )


def _agent_self_repair_preview_response(
    payload: AgentSelfRepairPromotePreviewRequest,
) -> AgentSelfRepairPromotePreviewResponse:
    preview = build_self_repair_preview(
        failures=payload.failures,
        case_id_prefix=payload.case_id_prefix,
    )
    return AgentSelfRepairPromotePreviewResponse(preview=preview.model_dump(mode="json"))


def _agent_review_queue_response(
    *,
    runtime: AppRuntime | Any,
    limit: int,
) -> AgentReviewQueueListResponse:
    return AgentReviewQueueListResponse(
        **_list_response_fields(runtime=runtime, key="agent_review_queue", limit=limit)
    )


def _agent_review_queue_decision_response(
    *,
    item_id: str,
    approved: bool,
) -> AgentReviewQueueDecisionResponse:
    summary = "Approved by operator." if approved else "Rejected by operator."
    item = apply_review_decision(
        {"item_id": item_id, "item_type": "manual", "summary": summary}, approved=approved
    )
    return AgentReviewQueueDecisionResponse(item=item.model_dump(mode="json"))


__all__ = [
    "_agent_delegation_plan_response",
    "_agent_delegation_policy_response",
    "_agent_delegation_runs_response",
    "_agent_model_route_response",
    "_agent_model_router_decisions_response",
    "_agent_model_router_policy_response",
    "_agent_review_queue_decision_response",
    "_agent_review_queue_response",
    "_agent_self_repair_failures_response",
    "_agent_self_repair_preview_response",
]
