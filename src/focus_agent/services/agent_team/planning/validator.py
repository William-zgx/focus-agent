from __future__ import annotations

from typing import Any

from focus_agent.core.agent_team import AgentTeamSession, AgentTeamTask, AgentTeamTaskStatus

from ...agent_team_helpers import _now
from ...agent_team_planning_models import AgentTeamPlanDraft, AgentTeamPlanOptions
from ...agent_team_planning_rules import *  # noqa: F401,F403
from ...agent_team_planning_rules import __all__ as _rules_all
from ...agent_team_planning_support import _is_unstarted, _task_identity, _validate_task_draft
from .dag import AgentTeamPlanningService


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


__all__ = [*_rules_all, "AgentTeamPlanningMixin", "_validate_task_draft"]
