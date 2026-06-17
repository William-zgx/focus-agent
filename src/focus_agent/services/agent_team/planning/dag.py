from __future__ import annotations

import sys
from typing import Any

from focus_agent.core.agent_team import AgentTeamSession
from focus_agent.delegation.delegation import build_agent_delegation_plan

from ...agent_team_planning_dag import (
    __all__ as _planning_dag_all,
)
from ...agent_team_planning_dag import (
    _adaptive_task_specs,
    _fallback_debug_deliverables,
    classify_mission,
    compile_mission_dag,
    plan_deliverables,
)
from ...agent_team_planning_dag import (
    _fallback_task_specs as _dag_fallback_task_specs,
)
from ...agent_team_planning_models import (
    AgentTeamPlanDraft,
    AgentTeamPlanOptions,
    AgentTeamTaskDraft,
    MissionDeliverable,
    MissionProfile,
)
from ...agent_team_planning_rules import focused_goal as _focused_goal
from ...agent_team_planning_rules import max_tasks_for_options as _max_tasks_for
from ...agent_team_planning_support import (
    _adaptive_plan_rationale,
    _artifact_rationale_for,
    _context_refs_for,
    _plan_hash,
    _planner_model_id,
    _planner_model_id_for_settings,
    _should_prefer_adaptive_model_plan,
    _task_type_for,
    _team_role_for_agent_role,
    _title_for,
    _validate_task_draft,
)
from .serializer import _dedupe_values, _merge_context_refs, _skill_plan_for_session


class AgentTeamPlanningService:
    def __init__(self, *, settings: Any | None = None):
        self.settings = settings

    def build_plan(
        self,
        *,
        session: AgentTeamSession,
        options: AgentTeamPlanOptions,
    ) -> AgentTeamPlanDraft:
        adaptive_error: str | None = None
        delegation_error: str | None = None
        if _should_prefer_adaptive_model_plan(session=session, options=options):
            try:
                plan = self._adaptive_model_plan(session=session, options=options)
                return self._with_skill_plan(plan, session=session, options=options)
            except Exception as exc:  # noqa: BLE001
                adaptive_error = f"{type(exc).__name__}: {exc}"

        try:
            plan = self._build_delegation_plan(session=session, options=options)
            if plan is not None:
                return self._with_skill_plan(plan, session=session, options=options)
        except Exception as exc:  # noqa: BLE001
            delegation_error = f"{type(exc).__name__}: {exc}"

        try:
            plan = self._adaptive_model_plan(
                session=session,
                options=options,
                planning_note=delegation_error,
            )
            return self._with_skill_plan(plan, session=session, options=options)
        except Exception as exc:  # noqa: BLE001
            planning_error = f"Adaptive planning failed: {type(exc).__name__}: {exc}"
            if adaptive_error:
                planning_error = (
                    f"{planning_error}; preferred adaptive planning failed: {adaptive_error}"
                )
            if delegation_error:
                planning_error = f"{planning_error}; delegation planning failed: {delegation_error}"
            plan = self._fallback_plan(
                session=session,
                options=options,
                planning_error=planning_error,
            )
            return self._with_skill_plan(plan, session=session, options=options)

    def _with_skill_plan(
        self,
        draft: AgentTeamPlanDraft,
        *,
        session: AgentTeamSession,
        options: AgentTeamPlanOptions,
    ) -> AgentTeamPlanDraft:
        skill_plan = _skill_plan_for_session(self.settings, session)
        if not skill_plan:
            return draft

        active_skill_ids = list(skill_plan.get("selected_skill_ids") or [])
        resolution_events = [
            dict(item) for item in skill_plan.get("resolution_events", []) if isinstance(item, dict)
        ]
        skill_refs = [
            dict(item) for item in skill_plan.get("context_refs", []) if isinstance(item, dict)
        ]
        recommended_tools = _dedupe_values(
            str(tool) for tool in skill_plan.get("recommended_tools", []) if str(tool).strip()
        )
        capability_requirements = _dedupe_values(
            str(item) for item in skill_plan.get("capability_requirements", []) if str(item).strip()
        )
        skill_capabilities = [f"skill:{skill_id}" for skill_id in active_skill_ids]
        enriched_tasks: list[AgentTeamTaskDraft] = []
        for task in draft.tasks:
            enriched_tasks.append(
                task.model_copy(
                    update={
                        "scope": _dedupe_values([*task.scope, *recommended_tools]),
                        "context_refs": _merge_context_refs(task.context_refs, skill_refs),
                        "capability_requirements": _dedupe_values(
                            [
                                *task.capability_requirements,
                                *skill_capabilities,
                                *capability_requirements,
                            ]
                        ),
                        "active_skill_ids": active_skill_ids,
                        "skill_resolution_events": resolution_events,
                    }
                )
            )

        rationale = draft.planning_rationale
        if active_skill_ids:
            rationale = f"{rationale} Skill preflight selected {', '.join(active_skill_ids)}."
        elif skill_plan.get("candidates"):
            rationale = f"{rationale} Skill preflight recorded candidates without auto-activation."

        updated = draft.model_copy(
            update={
                "planning_rationale": rationale,
                "skill_plan": skill_plan,
                "tasks": enriched_tasks,
                "plan_hash": "",
            }
        )
        return updated.model_copy(update={"plan_hash": _plan_hash(session, options, updated)})

    def _build_delegation_plan(
        self,
        *,
        session: AgentTeamSession,
        options: AgentTeamPlanOptions,
    ) -> AgentTeamPlanDraft | None:
        if self.settings is None:
            return None
        delegation = build_agent_delegation_plan(settings=self.settings, task_text=session.goal)
        if not delegation.enabled or not delegation.tasks:
            return None

        max_tasks = _max_tasks_for(options)
        decision_by_task_id = {
            str(decision.task_id): decision
            for decision in delegation.decisions
            if getattr(decision, "task_id", None)
        }
        included_task_ids = {task.task_id for task in delegation.tasks[:max_tasks]}
        tasks: list[AgentTeamTaskDraft] = []
        for sort_order, delegated in enumerate(delegation.tasks[:max_tasks], start=1):
            role = _team_role_for_agent_role(delegated.role)
            dependencies = [
                parent_id
                for parent_id in [delegated.parent_task_id]
                if parent_id and parent_id in included_task_ids
            ]
            decision = decision_by_task_id.get(delegated.task_id)
            rationale = (
                getattr(decision, "rationale", None)
                or _artifact_rationale_for(delegation, delegated.task_id)
                or "Role routing produced this task from the session goal."
            )
            task_goal = _focused_goal(str(delegated.goal), options)
            tasks.append(
                AgentTeamTaskDraft(
                    key=delegated.task_id,
                    title=_title_for(role, task_goal),
                    role=role,
                    goal=task_goal,
                    scope=list(delegated.allowed_tools),
                    dependencies=dependencies,
                    acceptance_criteria=list(delegated.acceptance_criteria)
                    or ["The task output is traceable to the session goal."],
                    context_refs=list(delegated.context_refs),
                    planning_rationale=str(rationale),
                    sort_order=sort_order,
                    task_type=_task_type_for(role),
                    plan_source="model",
                )
            )

        _validate_task_draft(tasks)
        planner_model_id = _planner_model_id(delegation)
        draft = AgentTeamPlanDraft(
            planning_source="model",
            planning_rationale=delegation.route_reason
            or "Delegation role routing produced a structured task plan.",
            planner_model_id=planner_model_id,
            plan_hash="",
            tasks=tasks,
        )
        return draft.model_copy(update={"plan_hash": _plan_hash(session, options, draft)})

    def _adaptive_model_plan(
        self,
        *,
        session: AgentTeamSession,
        options: AgentTeamPlanOptions,
        planning_note: str | None = None,
    ) -> AgentTeamPlanDraft:
        max_tasks = _max_tasks_for(options)
        profile = classify_mission(session.goal, options)
        _legacy_override("_adaptive_task_specs", _adaptive_task_specs)(
            profile.goal,
            focus=profile.focus,
            language=profile.language,
        )
        deliverables = plan_deliverables(profile)
        tasks = compile_mission_dag(
            profile,
            deliverables,
            max_tasks=max_tasks,
            plan_source="model",
            context_refs=_context_refs_for(session),
            sandbox_id=session.root_thread_id,
        )
        _validate_task_draft(tasks)
        draft = AgentTeamPlanDraft(
            planning_source="model",
            planning_rationale=_adaptive_plan_rationale(
                profile.goal,
                focus=profile.focus,
                task_count=len(tasks),
                language=profile.language,
                planning_note=planning_note,
            ),
            planner_model_id=_planner_model_id_for_settings(self.settings),
            plan_hash="",
            tasks=tasks,
        )
        return draft.model_copy(update={"plan_hash": _plan_hash(session, options, draft)})

    def _fallback_plan(
        self,
        *,
        session: AgentTeamSession,
        options: AgentTeamPlanOptions,
        planning_error: str,
    ) -> AgentTeamPlanDraft:
        max_tasks = _max_tasks_for(options)
        source = "fallback_heuristic"
        profile = classify_mission(session.goal, options)
        deliverables = plan_deliverables(profile)
        if profile.focus == "debugging":
            deliverables = _fallback_debug_deliverables(deliverables)
        candidates = compile_mission_dag(
            profile,
            deliverables,
            max_tasks=max_tasks,
            plan_source=source,
            context_refs=[],
            sandbox_id=session.root_thread_id,
        )
        _validate_task_draft(candidates)
        draft = AgentTeamPlanDraft(
            planning_source=source,
            planning_rationale=(
                f"Fallback heuristic classified the mission as {profile.focus} and produced an adaptive DAG."
            ),
            planning_error=planning_error,
            plan_hash="",
            tasks=candidates,
        )
        return draft.model_copy(update={"plan_hash": _plan_hash(session, options, draft)})


def _legacy_override(name: str, default: Any) -> Any:
    legacy_module = sys.modules.get("focus_agent.services.agent_team_planning")
    candidate = getattr(legacy_module, name, None) if legacy_module is not None else None
    return candidate if callable(candidate) and candidate is not default else default


def _fallback_task_specs(goal: str, *, focus: str) -> list[dict[str, Any]]:
    return _legacy_override("_fallback_task_specs", _dag_fallback_task_specs)(
        goal,
        focus=focus,
    )


__all__ = [
    "AgentTeamPlanDraft",
    "AgentTeamPlanOptions",
    "AgentTeamPlanningService",
    "AgentTeamTaskDraft",
    "MissionDeliverable",
    "MissionProfile",
    "classify_mission",
    "compile_mission_dag",
    "plan_deliverables",
    "_adaptive_task_specs",
    "_fallback_task_specs",
    *_planning_dag_all,
]
