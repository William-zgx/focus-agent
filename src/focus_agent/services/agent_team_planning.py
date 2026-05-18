from __future__ import annotations

from typing import Any

from focus_agent.delegation.delegation import build_agent_delegation_plan
from focus_agent.core.agent_team import (
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskStatus,
)
from focus_agent.skills import SkillRegistry

from .agent_team_helpers import _now
from .agent_team_planning_dag import (
    _adaptive_task_specs as _dag_adaptive_task_specs,
)
from .agent_team_planning_dag import (
    _fallback_debug_deliverables,
    classify_mission,
    compile_mission_dag,
    plan_deliverables,
)
from .agent_team_planning_dag import (
    _fallback_task_specs as _dag_fallback_task_specs,
)
from .agent_team_planning_models import (
    AgentTeamPlanDraft,
    AgentTeamPlanOptions,
    AgentTeamTaskDraft,
    MissionDeliverable,
    MissionProfile,
)
from .agent_team_planning_rules import (
    focused_goal as _focused_goal,
)
from .agent_team_planning_rules import (
    max_tasks_for_options as _max_tasks_for,
)
from .agent_team_planning_support import (
    _adaptive_plan_rationale,
    _artifact_rationale_for,
    _context_refs_for,
    _is_unstarted,
    _plan_hash,
    _planner_model_id,
    _planner_model_id_for_settings,
    _should_prefer_adaptive_model_plan,
    _task_identity,
    _task_type_for,
    _team_role_for_agent_role,
    _title_for,
    _validate_task_draft,
)


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
            dict(item)
            for item in skill_plan.get("resolution_events", [])
            if isinstance(item, dict)
        ]
        skill_refs = [
            dict(item)
            for item in skill_plan.get("context_refs", [])
            if isinstance(item, dict)
        ]
        recommended_tools = _dedupe_values(
            str(tool)
            for tool in skill_plan.get("recommended_tools", [])
            if str(tool).strip()
        )
        capability_requirements = _dedupe_values(
            str(item)
            for item in skill_plan.get("capability_requirements", [])
            if str(item).strip()
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
            rationale = (
                f"{rationale} Skill preflight selected {', '.join(active_skill_ids)}."
            )
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
        # Keep the old adaptive spec seam active so patched tests and external callers
        # still force fallback when the model-planning step fails.
        _adaptive_task_specs(profile.goal, focus=profile.focus, language=profile.language)
        deliverables = plan_deliverables(profile)
        tasks = compile_mission_dag(
            profile,
            deliverables,
            max_tasks=max_tasks,
            plan_source="model",
            context_refs=_context_refs_for(session),
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


def _skill_plan_for_session(settings: Any | None, session: AgentTeamSession) -> dict[str, Any]:
    if settings is None or not bool(getattr(settings, "agent_team_skill_scout_enabled", True)):
        return {}

    registry = SkillRegistry.from_settings(settings)
    selection = registry.select_for_message(session.goal)
    candidates = registry.search_skills(session.goal, scope="installed", limit=5)
    selected_skills = [
        skill
        for skill_id in selection.skill_ids
        for skill in [registry.resolve(skill_id)]
        if skill is not None
    ]
    recommended_tools = _dedupe_values(
        tool
        for skill in selected_skills
        for tool in skill.recommended_tools
        if str(tool).strip()
    )
    capability_requirements = _dedupe_values(
        requirement
        for skill in selected_skills
        for requirement in skill.capability_requirements
        if str(requirement).strip()
    )
    context_refs = [
        {
            "kind": "skill",
            "type": "skill",
            "skill_id": skill.skill_id,
            "source_id": skill.source_id,
            "source_type": skill.source_type,
            "trust_level": skill.trust_level,
            "recommended_tools": list(skill.recommended_tools),
            "capability_requirements": list(skill.capability_requirements),
            "path": str(skill.path),
        }
        for skill in selected_skills
    ]
    resolution_event = {
        "source": selection.selection_source,
        "selected_skill_ids": list(selection.skill_ids),
        "matched_triggers": list(selection.matched_triggers),
        "confidence": selection.confidence,
        "rationale": selection.rationale,
    }
    return {
        "enabled": True,
        "automation_level": str(getattr(settings, "agent_team_automation_level", "assisted")),
        "selected_skill_ids": list(selection.skill_ids),
        "recommended_tools": recommended_tools,
        "capability_requirements": capability_requirements,
        "context_refs": context_refs,
        "resolution_events": [resolution_event],
        "candidates": [
            {
                "skill_id": candidate.skill_id,
                "description": candidate.description,
                "source_id": candidate.source_id,
                "source_type": candidate.source_type,
                "installed": candidate.installed,
                "trust_level": candidate.trust_level,
                "score": candidate.score,
                "rationale": candidate.rationale,
                "recommended_tools": list(candidate.recommended_tools),
                "capability_requirements": list(candidate.capability_requirements),
            }
            for candidate in candidates
        ],
    }


def _dedupe_values(values: Any) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _merge_context_refs(
    base_refs: list[dict[str, Any]],
    extra_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ref in [*base_refs, *extra_refs]:
        if not isinstance(ref, dict):
            continue
        kind = str(ref.get("kind") or ref.get("type") or "").strip()
        ref_id = str(ref.get("id") or ref.get("skill_id") or ref.get("path") or "").strip()
        identity = (kind, ref_id)
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(dict(ref))
    return merged


# Backwards-compatible seams for tests and callers that patch the old module.
def _adaptive_task_specs(goal: str, *, focus: str, language: str) -> list[dict[str, Any]]:
    return _dag_adaptive_task_specs(goal, focus=focus, language=language)


def _fallback_task_specs(goal: str, *, focus: str) -> list[dict[str, Any]]:
    return _dag_fallback_task_specs(goal, focus=focus)


class AgentTeamPlanningMixin:
    settings: Any | None

    def plan_session(
        self,
        *,
        session_id: str,
        user_id: str,
        create_branches: bool = True,
        parent_thread_id: str | None = None,
        replace_existing: bool = False,
        granularity: str | None = None,
        focus: str | None = None,
        max_tasks: int | None = None,
    ) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
        session = self.get_session(session_id, user_id=user_id)
        options = AgentTeamPlanOptions(
            replace_existing=replace_existing,
            granularity=granularity,
            focus=focus,
            max_tasks=max_tasks,
        )
        draft = AgentTeamPlanningService(settings=self.settings).build_plan(
            session=session,
            options=options,
        )

        existing = self.list_tasks(session_id=session_id, user_id=user_id)
        active_existing = [
            task for task in existing if task.status != AgentTeamTaskStatus.CANCELLED
        ]
        if (
            active_existing
            and not options.replace_existing
            and session.plan_hash == draft.plan_hash
        ):
            session = self._save_planning_metadata(session, draft)
            return session, active_existing

        if active_existing and options.replace_existing:
            self._cancel_unstarted_tasks(tasks=active_existing, user_id=user_id)
            active_existing = [
                task
                for task in self.list_tasks(session_id=session_id, user_id=user_id)
                if task.status != AgentTeamTaskStatus.CANCELLED
            ]

        created_by_key: dict[str, AgentTeamTask] = {}
        existing_by_identity = {_task_identity(task): task for task in active_existing}
        for task_draft in draft.tasks:
            key = (task_draft.role, task_draft.goal.strip())
            existing_task = existing_by_identity.get(key)
            if existing_task is not None:
                created_by_key[task_draft.key] = existing_task
                continue

            dependencies = [
                created_by_key[dependency].task_id
                for dependency in task_draft.dependencies
                if dependency in created_by_key
            ]
            task = self.create_task(
                session_id=session_id,
                user_id=user_id,
                role=task_draft.role,
                title=task_draft.title,
                goal=task_draft.goal,
                scope=task_draft.scope,
                dependencies=dependencies,
                acceptance_criteria=task_draft.acceptance_criteria,
                planning_rationale=task_draft.planning_rationale,
                sort_order=task_draft.sort_order,
                task_type=task_draft.task_type,
                task_kind=task_draft.task_kind,
                input_contract=task_draft.input_contract,
                output_contract=task_draft.output_contract,
                evidence_required=task_draft.evidence_required,
                capability_requirements=task_draft.capability_requirements,
                risk_level=task_draft.risk_level,
                write_scope=task_draft.write_scope,
                resource_claims=task_draft.resource_claims,
                replan_policy=task_draft.replan_policy,
                plan_source=task_draft.plan_source,
                context_refs=task_draft.context_refs,
                active_skill_ids=task_draft.active_skill_ids,
                skill_resolution_events=task_draft.skill_resolution_events,
                create_branch=create_branches,
                parent_thread_id=parent_thread_id or session.root_thread_id,
            )
            created_by_key[task_draft.key] = task
            existing_by_identity[key] = task

        session = self._save_planning_metadata(self.get_session(session_id, user_id=user_id), draft)
        tasks = [
            task
            for task in self.list_tasks(session_id=session_id, user_id=user_id)
            if task.status != AgentTeamTaskStatus.CANCELLED
        ]
        return session, tasks

    def _save_planning_metadata(
        self,
        session: AgentTeamSession,
        draft: AgentTeamPlanDraft,
    ) -> AgentTeamSession:
        updated = session.model_copy(
            update={
                "planning_source": draft.planning_source,
                "planning_rationale": draft.planning_rationale,
                "planner_model_id": draft.planner_model_id,
                "plan_generated_at": _now(),
                "plan_hash": draft.plan_hash,
                "planning_error": draft.planning_error,
                "skill_plan": draft.skill_plan,
                "updated_at": _now(),
            }
        )
        self.repository.save_session(updated)
        return updated

    def _cancel_unstarted_tasks(self, *, tasks: list[AgentTeamTask], user_id: str) -> None:
        for task in tasks:
            if not _is_unstarted(task):
                continue
            self.update_task(
                task_id=task.task_id,
                user_id=user_id,
                status=AgentTeamTaskStatus.CANCELLED,
                last_error="Replaced by a regenerated Agent Team plan.",
            )


__all__ = [
    "AgentTeamPlanDraft",
    "AgentTeamPlanOptions",
    "AgentTeamPlanningMixin",
    "AgentTeamPlanningService",
    "AgentTeamTaskDraft",
    "MissionDeliverable",
    "MissionProfile",
    "classify_mission",
    "plan_deliverables",
    "compile_mission_dag",
]
