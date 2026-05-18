from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .delegation_models import (
    AgentArtifact,
    AgentBudget,
    AgentDecision,
    AgentDelegationPlan,
    AgentRun,
    AgentRunStatus,
    AgentTask,
)
from .execution_modes import normalize_delegation_execution_mode
from .roles import AgentRole, RoleModelResolver, build_role_route_plan, normalize_agent_role
from ..config import Settings


def build_agent_delegation_plan(
    *,
    settings: Settings,
    task_text: str,
    role_route_plan: dict[str, Any] | None = None,
    available_tool_names: Iterable[str] = (),
    tool_policy: str = "",
) -> AgentDelegationPlan:
    if not bool(getattr(settings, "agent_delegation_enabled", False)):
        return AgentDelegationPlan(
            enabled=False,
            enforce=False,
            source="disabled",
            route_reason="AGENT_DELEGATION_ENABLED is off.",
            max_parallel_runs=max(1, int(getattr(settings, "agent_role_max_parallel_runs", 1))),
        )

    route_plan = role_route_plan or build_role_route_plan(
        settings=settings,
        task_text=task_text,
        available_tool_names=available_tool_names,
        tool_policy=tool_policy,
    ).model_dump(mode="json")
    route_decisions = _route_decisions(route_plan)
    resolver = RoleModelResolver(settings)
    tasks: list[AgentTask] = []
    runs: list[AgentRun] = []
    decisions: list[AgentDecision] = []
    enforce = bool(getattr(settings, "agent_delegation_enforce", False))
    execution_mode = normalize_delegation_execution_mode(
        str(getattr(settings, "agent_delegation_execution_mode", "observe") or "observe")
    )
    if not route_decisions:
        return AgentDelegationPlan(
            enabled=True,
            enforce=enforce,
            execution_mode=execution_mode,
            source="delegation_runtime",
            route_reason=str(route_plan.get("route_reason") or "No valid delegation route decisions."),
            max_parallel_runs=max(
                1,
                int(
                    route_plan.get("max_parallel_runs")
                    or getattr(settings, "agent_role_max_parallel_runs", 1)
                ),
            ),
            legacy_execution_unchanged=execution_mode == "observe",
            skipped_reason="no_valid_route_decisions",
        )

    for index, raw in enumerate(route_decisions):
        role = normalize_agent_role(str(raw.get("role") or AgentRole.EXECUTOR.value))
        task_id = f"task-{index + 1}-{role.value}"
        governance = (
            raw.get("tool_governance") if isinstance(raw.get("tool_governance"), dict) else {}
        )
        task = AgentTask(
            task_id=task_id,
            parent_task_id=None if role == AgentRole.ORCHESTRATOR else "task-1-orchestrator",
            role=role,
            goal=str(raw.get("task_slice") or task_text or f"{role.value} delegated task"),
            constraints=[
                "Respect Memory Curator scope.",
                "Respect Tool Router allow/deny plan.",
            ],
            allowed_tools=[str(item) for item in governance.get("allowed_tools") or []],
            memory_scope="branch_local" if role == AgentRole.MEMORY_CURATOR else "thread",
            budget=_budget_for_role(role),
            acceptance_criteria=[
                str(raw.get("rationale") or "Role output is traceable and reviewable.")
            ],
            max_turns=_max_turns_for_role(role),
            timeout_seconds=_timeout_for_role(role),
            max_depth=1,
            requires_workspace_write=bool(governance.get("allow_workspace_write", False)),
            requires_network=bool(governance.get("allow_network", False)),
            context_refs=[
                dict(item) for item in raw.get("context_refs") or [] if isinstance(item, dict)
            ],
            run_isolation_key=str(raw.get("run_isolation_key") or f"role:{role.value}"),
        )
        tasks.append(task)
        status: AgentRunStatus = "planned"
        run_artifacts = [
            AgentArtifact(
                artifact_id=f"artifact-{task_id}",
                kind="decision",
                title=f"{role.value} delegation plan",
                summary=str(raw.get("rationale") or ""),
            )
        ]
        runs.append(
            AgentRun(
                run_id=f"run-{task_id}",
                task_id=task_id,
                role=role,
                status=status,
                model_id=str(raw.get("model_id") or resolver.resolve(role)),
                artifacts=run_artifacts,
                execution_mode=execution_mode,
            )
        )
        decisions.append(
            AgentDecision(
                decision_id=f"decision-{task_id}",
                kind="delegate",
                role=role,
                task_id=task_id,
                rationale=str(raw.get("rationale") or "Delegated from role route plan."),
                payload={
                    "run_isolation_key": task.run_isolation_key,
                    "depends_on": raw.get("depends_on") or [],
                },
            )
        )

    return AgentDelegationPlan(
        enabled=True,
        enforce=enforce,
        execution_mode=execution_mode,
        source="delegation_runtime",
        route_reason=str(route_plan.get("route_reason") or "Delegation runtime built role tasks."),
        max_parallel_runs=max(
            1,
            int(
                route_plan.get("max_parallel_runs")
                or getattr(settings, "agent_role_max_parallel_runs", 1)
            ),
        ),
        tasks=tasks,
        runs=runs,
        decisions=decisions,
        legacy_execution_unchanged=execution_mode == "observe",
    )


def _route_decisions(route_plan: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = route_plan.get("decisions") if isinstance(route_plan, dict) else None
    if isinstance(decisions, list) and decisions:
        return [
            item
            for item in (dict(item) for item in decisions if isinstance(item, dict))
            if _is_valid_route_decision(item)
        ]
    return []


def _is_valid_route_decision(raw: dict[str, Any]) -> bool:
    goal = str(raw.get("task_slice") or "").strip()
    if not goal or goal.lower() == "execute the user request.":
        return False
    rationale = str(raw.get("rationale") or "").strip()
    governance = raw.get("tool_governance") if isinstance(raw.get("tool_governance"), dict) else {}
    context_refs = [item for item in raw.get("context_refs") or [] if isinstance(item, dict)]
    allowed_tools = [str(item) for item in governance.get("allowed_tools") or [] if str(item)]
    if not (rationale or context_refs or allowed_tools):
        return False
    return True


def _budget_for_role(role: AgentRole) -> AgentBudget:
    if role == AgentRole.ORCHESTRATOR:
        return AgentBudget(max_llm_calls=1, max_tool_calls=0)
    if role == AgentRole.CRITIC:
        return AgentBudget(max_llm_calls=1, max_tool_calls=2)
    if role in {AgentRole.MEMORY_CURATOR, AgentRole.SKILL_SCOUT}:
        return AgentBudget(max_llm_calls=1, max_tool_calls=2)
    return AgentBudget(max_llm_calls=2, max_tool_calls=5)


def _max_turns_for_role(role: AgentRole) -> int:
    if role == AgentRole.ORCHESTRATOR:
        return 1
    if role == AgentRole.EXECUTOR:
        return 3
    return 2


def _timeout_for_role(role: AgentRole) -> int:
    if role == AgentRole.EXECUTOR:
        return 120
    if role == AgentRole.CRITIC:
        return 60
    return 30


__all__ = ["build_agent_delegation_plan"]
