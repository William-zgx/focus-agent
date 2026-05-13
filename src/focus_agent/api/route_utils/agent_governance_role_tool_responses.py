from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from focus_agent.agent_roles import AgentRole, RoleModelResolver, build_role_route_plan
from focus_agent.capabilities.tool_router import (
    build_capability_registry,
    build_tool_route_plan,
    build_toolset_registry,
)
from focus_agent.config import Settings
from focus_agent.engine.runtime import AppRuntime
from focus_agent.repositories.postgres_trajectory_repository import TrajectoryTurnQuery

from ..contracts import (
    AgentCapabilityListResponse,
    AgentToolsetListResponse,
    AgentRoleDecisionListResponse,
    AgentRoleDryRunRequest,
    AgentRoleDryRunResponse,
    AgentRolePolicyResponse,
    AgentToolRouteDecisionListResponse,
    AgentToolRouteRequest,
    AgentToolRouteResponse,
)
from .agent_governance_trajectory_responses import _list_response_fields, _role_route_decision_items
from .trajectory import _maybe_get_trajectory_repository


def _agent_role_policy_response(settings: Settings | Any) -> AgentRolePolicyResponse:
    resolver = RoleModelResolver(settings)
    return AgentRolePolicyResponse(
        enabled=bool(getattr(settings, "agent_role_routing_enabled", False)),
        default_model=str(getattr(settings, "model", "")),
        helper_model=getattr(settings, "helper_model", None),
        max_parallel_runs=max(1, int(getattr(settings, "agent_role_max_parallel_runs", 1) or 1)),
        roles=[role.value for role in AgentRole],
        role_models={role.value: resolver.resolve(role) for role in AgentRole},
        fallback_order=[
            "role-specific model override",
            "executor selected model",
            "helper model for planning and critique roles",
            "default model",
        ],
    )


def _available_tool_names(runtime: AppRuntime | Any) -> list[str]:
    registry = getattr(runtime, "tool_registry", None)
    return [
        str(getattr(tool, "name", "")).strip()
        for tool in tuple(getattr(registry, "tools", ()) or ())
        if str(getattr(tool, "name", "")).strip()
    ]


def _agent_role_dry_run_response(
    *,
    payload: AgentRoleDryRunRequest,
    runtime: AppRuntime | Any,
) -> AgentRoleDryRunResponse:
    available_tools = payload.available_tools or _available_tool_names(runtime)
    plan = build_role_route_plan(
        settings=runtime.settings,
        task_text=payload.message,
        available_tool_names=available_tools,
        tool_policy=payload.scene,
    )
    return AgentRoleDryRunResponse(
        policy=_agent_role_policy_response(runtime.settings),
        plan=plan.model_dump(mode="json"),
    )


def _agent_role_decisions_response(
    *,
    runtime: AppRuntime | Any,
    limit: int,
) -> AgentRoleDecisionListResponse:
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return AgentRoleDecisionListResponse(
            items=[],
            count=0,
            trajectory_available=False,
        )
    try:
        rows = repo.list_turns(TrajectoryTurnQuery(limit=limit, newest_first=True))
    except Exception as exc:  # noqa: BLE001
        return AgentRoleDecisionListResponse(
            items=[],
            count=0,
            trajectory_available=False,
            trajectory_error=str(exc),
        )
    items = _role_route_decision_items(rows)
    return AgentRoleDecisionListResponse(
        items=items,
        count=len(items),
        trajectory_available=True,
    )


def _agent_capabilities_response(runtime: AppRuntime | Any) -> AgentCapabilityListResponse:
    registry = getattr(runtime, "tool_registry", None)
    items = build_capability_registry(registry) if registry is not None else []
    return AgentCapabilityListResponse(
        items=[item.model_dump(mode="json") for item in items],
        count=len(items),
    )


def _agent_toolsets_response(runtime: AppRuntime | Any) -> AgentToolsetListResponse:
    registry = getattr(runtime, "tool_registry", None)
    items = build_toolset_registry(registry) if registry is not None else []
    return AgentToolsetListResponse(
        items=[item.model_dump(mode="json") for item in items],
        count=len(items),
    )


def _agent_tool_route_response(
    *,
    payload: AgentToolRouteRequest,
    runtime: AppRuntime | Any,
) -> AgentToolRouteResponse:
    registry = getattr(runtime, "tool_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="Tool registry is unavailable.")
    plan = build_tool_route_plan(
        tool_registry=registry,
        role=payload.role,
        tool_policy=payload.tool_policy,
        available_tool_names=payload.available_tools or _available_tool_names(runtime),
        enforce=(
            bool(getattr(runtime.settings, "agent_tool_router_enforce", True))
            if payload.enforce is None
            else bool(payload.enforce)
        ),
    )
    return AgentToolRouteResponse(plan=plan.model_dump(mode="json"))


def _agent_tool_route_decisions_response(
    *,
    runtime: AppRuntime | Any,
    limit: int,
) -> AgentToolRouteDecisionListResponse:
    return AgentToolRouteDecisionListResponse(
        **_list_response_fields(runtime=runtime, key="tool_route_plan", limit=limit, decisions=True)
    )


__all__ = [
    "_agent_capabilities_response",
    "_agent_toolsets_response",
    "_agent_role_decisions_response",
    "_agent_role_dry_run_response",
    "_agent_role_policy_response",
    "_agent_tool_route_decisions_response",
    "_agent_tool_route_response",
    "_available_tool_names",
]
