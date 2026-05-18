from __future__ import annotations

import hashlib
import json
from typing import Any

from focus_agent.core.agent_team import (
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)
from focus_agent.delegation.delegation import AgentDelegationPlan
from focus_agent.delegation.roles import AgentRole

from .agent_team_planning_models import (
    AgentTeamPlanDraft,
    AgentTeamPlanOptions,
    AgentTeamTaskDraft,
)
from .agent_team_planning_rules import (
    focused_goal as _focused_goal,
)
from .agent_team_planning_rules import (
    infer_focus as _infer_focus,
)

_AGENT_ROLE_TO_TEAM_ROLE: dict[AgentRole, AgentTeamTaskRole] = {
    AgentRole.ORCHESTRATOR: AgentTeamTaskRole.ARCHITECT,
    AgentRole.PLANNER: AgentTeamTaskRole.PLANNER,
    AgentRole.EXECUTOR: AgentTeamTaskRole.BACKEND_EXECUTOR,
    AgentRole.CRITIC: AgentTeamTaskRole.REVIEWER,
    AgentRole.MEMORY_CURATOR: AgentTeamTaskRole.PLANNER,
    AgentRole.SKILL_SCOUT: AgentTeamTaskRole.PLANNER,
}


def _task_draft_from_spec(
    spec: dict[str, Any],
    *,
    sort_order: int,
    plan_source: str,
    context_refs: list[dict[str, Any]],
) -> AgentTeamTaskDraft:
    return AgentTeamTaskDraft(
        key=str(spec["key"]),
        title=str(spec["title"]),
        role=AgentTeamTaskRole(str(spec["role"])),
        goal=str(spec["goal"]),
        scope=list(spec.get("scope") or []),
        dependencies=list(spec.get("dependencies") or []),
        acceptance_criteria=list(spec["acceptance_criteria"]),
        context_refs=context_refs,
        planning_rationale=str(spec["planning_rationale"]),
        sort_order=sort_order,
        task_type=str(spec["task_type"]),
        task_kind=str(spec.get("task_kind") or spec["task_type"]),
        input_contract=dict(spec["input_contract"])
        if isinstance(spec.get("input_contract"), dict)
        else None,
        output_contract=dict(spec["output_contract"])
        if isinstance(spec.get("output_contract"), dict)
        else None,
        evidence_required=list(spec.get("evidence_required") or []),
        capability_requirements=list(spec.get("capability_requirements") or []),
        risk_level=str(spec["risk_level"]) if spec.get("risk_level") else None,
        write_scope=list(spec.get("write_scope") or []),
        resource_claims=list(spec.get("resource_claims") or []),
        replan_policy=dict(spec["replan_policy"])
        if isinstance(spec.get("replan_policy"), dict)
        else None,
        plan_source=plan_source,
    )


def _task_identity(task: AgentTeamTask) -> tuple[AgentTeamTaskRole, str]:
    return (task.role, task.goal.strip())


def _team_role_for_agent_role(role: AgentRole) -> AgentTeamTaskRole:
    return _AGENT_ROLE_TO_TEAM_ROLE.get(role, AgentTeamTaskRole.BACKEND_EXECUTOR)


def _should_prefer_adaptive_model_plan(
    *,
    session: AgentTeamSession,
    options: AgentTeamPlanOptions,
) -> bool:
    base_goal = _focused_goal(session.goal, options)
    focus = _infer_focus(base_goal, options)
    # Role routing is useful for code execution, but it can turn open-ended
    # research or validation missions into generic executor tasks. For those
    # goals, the Workbench should show a domain-shaped DAG directly.
    return focus in {"research", "debugging", "review", "verification", "writing"}


def _title_for(role: AgentTeamTaskRole, goal: str) -> str:
    prefix = {
        AgentTeamTaskRole.ARCHITECT: "Coordinate",
        AgentTeamTaskRole.PLANNER: "Plan",
        AgentTeamTaskRole.BACKEND_EXECUTOR: "Implement",
        AgentTeamTaskRole.FRONTEND_EXECUTOR: "Implement UI",
        AgentTeamTaskRole.TEST_ENGINEER: "Test",
        AgentTeamTaskRole.REVIEWER: "Review",
        AgentTeamTaskRole.VERIFIER: "Verify",
        AgentTeamTaskRole.WRITER: "Document",
    }.get(role, "Work")
    compact = " ".join(goal.split())
    if len(compact) > 72:
        compact = f"{compact[:69].rstrip()}..."
    return f"{prefix}: {compact}"


def _task_type_for(role: AgentTeamTaskRole) -> str:
    if role in {AgentTeamTaskRole.ARCHITECT, AgentTeamTaskRole.PLANNER}:
        return "coordination"
    if role in {
        AgentTeamTaskRole.REVIEWER,
        AgentTeamTaskRole.VERIFIER,
        AgentTeamTaskRole.TEST_ENGINEER,
    }:
        return "review"
    if role == AgentTeamTaskRole.WRITER:
        return "writeup"
    return "execution"


def _artifact_rationale_for(delegation: AgentDelegationPlan, task_id: str) -> str | None:
    for run in delegation.runs:
        if run.task_id != task_id:
            continue
        for artifact in run.artifacts:
            if artifact.summary:
                return artifact.summary
    return None


def _planner_model_id(delegation: AgentDelegationPlan) -> str | None:
    for run in delegation.runs:
        if run.role in {AgentRole.ORCHESTRATOR, AgentRole.PLANNER} and run.model_id:
            return run.model_id
    return delegation.runs[0].model_id if delegation.runs else None


def _planner_model_id_for_settings(settings: Any | None) -> str:
    if settings is None:
        return "adaptive-planner:v1"
    for attr in ("agent_role_orchestrator_model", "agent_role_planner_model", "model"):
        value = getattr(settings, attr, None)
        if value:
            return str(value)
    return "adaptive-planner:v1"


def _context_refs_for(session: AgentTeamSession) -> list[dict[str, Any]]:
    return [{"kind": "thread", "id": session.root_thread_id}]


def _adaptive_plan_rationale(
    goal: str,
    *,
    focus: str,
    task_count: int,
    language: str,
    planning_note: str | None,
) -> str:
    if language == "zh":
        rationale = f"根据目标语义识别为「{focus}」型 Mission，并从交付物、依赖、合约和证据生成 {task_count} 个 DAG 任务。"
        if planning_note:
            rationale += " 已绕过不可用的 delegation 路径，改用自适应规划。"
        return rationale
    rationale = (
        f"Classified the mission as {focus} work and compiled {task_count} DAG tasks "
        "from deliverables, dependencies, contracts, and required evidence."
    )
    if planning_note:
        rationale += " Delegation planning was unavailable, so adaptive planning was used."
    return rationale


def _validate_task_draft(tasks: list[AgentTeamTaskDraft]) -> None:
    if not 1 <= len(tasks) <= 8:
        raise ValueError("Agent Team planning requires between 1 and 8 tasks.")
    seen: set[str] = set()
    for task in tasks:
        if not task.goal.strip():
            raise ValueError(f"Planned task {task.key} is missing a goal.")
        if task.key in seen:
            raise ValueError(f"Planned task {task.key} is duplicated.")
        for dependency in task.dependencies:
            if dependency not in seen:
                raise ValueError(
                    f"Planned task {task.key} has an unknown or cyclic dependency: {dependency}."
                )
        seen.add(task.key)


def _plan_hash(
    session: AgentTeamSession,
    options: AgentTeamPlanOptions,
    draft: AgentTeamPlanDraft,
) -> str:
    payload = {
        "goal": session.goal,
        "options": {
            "granularity": options.granularity,
            "focus": options.focus,
            "max_tasks": options.max_tasks,
        },
        "source": draft.planning_source,
        "tasks": [
            task.model_dump(
                mode="json",
                exclude={"sort_order"},
            )
            for task in draft.tasks
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_unstarted(task: AgentTeamTask) -> bool:
    return (
        task.status == AgentTeamTaskStatus.PENDING
        and not task.started_at
        and not task.run_status
        and not task.execution_status
        and not task.agent_run_id
        and not task.output_artifact_ids
    )


__all__ = [
    "_adaptive_plan_rationale",
    "_artifact_rationale_for",
    "_context_refs_for",
    "_is_unstarted",
    "_plan_hash",
    "_planner_model_id",
    "_planner_model_id_for_settings",
    "_should_prefer_adaptive_model_plan",
    "_task_draft_from_spec",
    "_task_identity",
    "_task_type_for",
    "_team_role_for_agent_role",
    "_title_for",
    "_validate_task_draft",
]
