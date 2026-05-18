from __future__ import annotations

from threading import RLock

from focus_agent.repositories.agent_team_repository import (
    AgentTeamRepository,
    InMemoryAgentTeamRepository,
)
from focus_agent.services.branches import BranchService
from focus_agent.services.coordination import create_in_memory_coordination_backend

from .run import AgentTeamMergeMixin
from .planning import AgentTeamPlanningMixin
from .run import AgentTeamRunMixin


from collections.abc import Iterable
from datetime import UTC, datetime

from focus_agent.core.agent_team import (
    AgentTeamRecommendedAction,
    AgentTeamTaskRole,
)
from focus_agent.core.branching import BranchRole


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


_ROLE_TO_BRANCH_ROLE: dict[AgentTeamTaskRole, BranchRole] = {
    AgentTeamTaskRole.PLANNER: BranchRole.DEEP_DIVE,
    AgentTeamTaskRole.ARCHITECT: BranchRole.DEEP_DIVE,
    AgentTeamTaskRole.BACKEND_EXECUTOR: BranchRole.EXECUTE,
    AgentTeamTaskRole.FRONTEND_EXECUTOR: BranchRole.EXECUTE,
    AgentTeamTaskRole.TEST_ENGINEER: BranchRole.VERIFY,
    AgentTeamTaskRole.REVIEWER: BranchRole.VERIFY,
    AgentTeamTaskRole.VERIFIER: BranchRole.VERIFY,
    AgentTeamTaskRole.WRITER: BranchRole.WRITEUP,
}


class AgentTeamHelperMixin:
    @staticmethod
    def branch_role_for_task_role(role: AgentTeamTaskRole | str) -> BranchRole:
        return _ROLE_TO_BRANCH_ROLE[AgentTeamTaskRole(role)]

    @staticmethod
    def _default_branch_name(role: AgentTeamTaskRole) -> str:
        return role.value.replace("_", " ").title()

    @staticmethod
    def _merge_verification_summary(current: str | None, test_evidence: list[str]) -> str | None:
        evidence = _dedupe(test_evidence)
        if not evidence:
            return current
        if not current:
            return "\n".join(evidence)
        return "\n".join(_dedupe([current, *evidence]))

    @staticmethod
    def _compact_task_goal(goal: str, *, max_chars: int = 140) -> str:
        summary = goal.split("\n\nSession goal:", 1)[0].strip()
        summary = " ".join(summary.split())
        if len(summary) <= max_chars:
            return summary
        return f"{summary[: max_chars - 1].rstrip()}…"

    @staticmethod
    def _recommended_action(
        *,
        accepted_count: int,
        rejected_count: int,
        pending_count: int,
        blocked_count: int,
        risk_count: int,
    ) -> AgentTeamRecommendedAction:
        if accepted_count == 0 and rejected_count > 0 and pending_count == 0 and blocked_count == 0:
            return AgentTeamRecommendedAction.DISCARD
        if blocked_count or risk_count:
            return AgentTeamRecommendedAction.REQUEST_CHANGES
        if pending_count:
            return AgentTeamRecommendedAction.SPLIT_FOLLOWUP
        return AgentTeamRecommendedAction.MERGE


__all__ = ["AgentTeamHelperMixin", "_ROLE_TO_BRANCH_ROLE", "_dedupe", "_now"]


from focus_agent.core.agent_team import (
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)


_DEFAULT_DISPATCH_TASKS: tuple[
    tuple[AgentTeamTaskRole, str, tuple[str, ...], tuple[AgentTeamTaskRole, ...]], ...
] = (
    (
        AgentTeamTaskRole.PLANNER,
        "Plan the work, clarify boundaries, and produce the implementation checklist.",
        ("docs/**", "src/**", "apps/web/**", "frontend-sdk/**", "tests/**"),
        (),
    ),
    (
        AgentTeamTaskRole.BACKEND_EXECUTOR,
        "Implement the backend/API orchestration surface and keep contracts compatible.",
        ("src/focus_agent/**", "tests/**"),
        (AgentTeamTaskRole.PLANNER,),
    ),
    (
        AgentTeamTaskRole.FRONTEND_EXECUTOR,
        "Implement the SDK and Web workbench controls for the orchestration flow.",
        (
            "frontend-sdk/**",
            "apps/web/src/features/agent-team/**",
            "apps/web/src/pages/agent-team/**",
        ),
        (AgentTeamTaskRole.PLANNER,),
    ),
    (
        AgentTeamTaskRole.TEST_ENGINEER,
        "Add and run focused tests that prove the orchestration flow works.",
        ("tests/**", "frontend-sdk/**", "apps/web/**"),
        (AgentTeamTaskRole.BACKEND_EXECUTOR, AgentTeamTaskRole.FRONTEND_EXECUTOR),
    ),
    (
        AgentTeamTaskRole.REVIEWER,
        "Review the coordinated changes for regressions, risk, and missing evidence.",
        ("src/**", "frontend-sdk/**", "apps/web/**", "tests/**"),
        (AgentTeamTaskRole.TEST_ENGINEER,),
    ),
    (
        AgentTeamTaskRole.VERIFIER,
        "Collect final verification evidence and identify remaining release risks.",
        ("tests/**", "docs/**"),
        (AgentTeamTaskRole.REVIEWER,),
    ),
)


class AgentTeamDispatchMixin:
    def dispatch_default_tasks(
        self,
        *,
        session_id: str,
        user_id: str,
        create_branches: bool = True,
        parent_thread_id: str | None = None,
    ) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
        session = self.get_session(session_id, user_id=user_id)
        existing = self.list_tasks(session_id=session_id, user_id=user_id)
        by_role = {task.role: task for task in existing}
        created_by_role: dict[AgentTeamTaskRole, AgentTeamTask] = {}

        for role, goal_template, scope, dependency_roles in _DEFAULT_DISPATCH_TASKS:
            if role in by_role:
                created_by_role[role] = by_role[role]
                continue
            dependencies = [
                created_by_role[dependency_role].task_id
                for dependency_role in dependency_roles
                if dependency_role in created_by_role
            ]
            task = self.create_task(
                session_id=session_id,
                user_id=user_id,
                role=role,
                title=role.value.replace("_", " ").title(),
                goal=f"{goal_template}\n\nSession goal: {session.goal}",
                scope=list(scope),
                dependencies=dependencies,
                planning_rationale="Legacy dispatch template task retained for backwards compatibility.",
                sort_order=len(created_by_role) + 1,
                task_type="coordination" if role == AgentTeamTaskRole.PLANNER else "execution",
                plan_source="legacy_template",
                create_branch=create_branches,
                parent_thread_id=parent_thread_id or session.root_thread_id,
            )
            created_by_role[role] = task

        planner = created_by_role.get(AgentTeamTaskRole.PLANNER)
        if planner and planner.status == AgentTeamTaskStatus.PENDING:
            planner = self.update_task(
                task_id=planner.task_id,
                user_id=user_id,
                status=AgentTeamTaskStatus.RUNNING,
            )
            created_by_role[AgentTeamTaskRole.PLANNER] = planner

        tasks = self.list_tasks(session_id=session_id, user_id=user_id)
        session = self.get_session(session_id, user_id=user_id)
        with self._lock:
            session = session.model_copy(
                update={
                    "planning_source": session.planning_source or "legacy_template",
                    "planning_rationale": session.planning_rationale
                    or "Legacy dispatch template generated the fixed compatibility task set.",
                    "plan_generated_at": session.plan_generated_at or _now(),
                    "updated_at": _now(),
                }
            )
            self.repository.save_session(session)
        return session, tasks


__all__ = ["AgentTeamDispatchMixin", "_DEFAULT_DISPATCH_TASKS"]


from uuid import uuid4

from focus_agent.core.agent_team import (
    AgentTeamArtifactKind,
    AgentTeamSession,
    AgentTeamSessionStatus,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)



class AgentTeamSessionTaskMixin:
    def create_session(
        self,
        *,
        root_thread_id: str | None = None,
        user_id: str,
        title: str | None = None,
        goal: str,
    ) -> AgentTeamSession:
        now = _now()
        resolved_root_thread_id = root_thread_id.strip() if root_thread_id else ""
        if not resolved_root_thread_id:
            resolved_root_thread_id = f"agent-team-standalone-{uuid4()}"
        session = AgentTeamSession(
            session_id=str(uuid4()),
            root_thread_id=resolved_root_thread_id,
            user_id=user_id,
            title=(title or goal or "Agent Team Session").strip()[:120] or "Agent Team Session",
            goal=goal,
            status=AgentTeamSessionStatus.PLANNING,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self.repository.create_session(session)
        return session

    def list_sessions(
        self,
        *,
        user_id: str | None = None,
        root_thread_id: str | None = None,
        status: AgentTeamSessionStatus | str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AgentTeamSession]:
        with self._lock:
            sessions = self.repository.list_sessions(user_id=user_id)
        if root_thread_id is not None:
            sessions = [session for session in sessions if session.root_thread_id == root_thread_id]
        if status is not None:
            status_value = AgentTeamSessionStatus(status)
            sessions = [session for session in sessions if session.status == status_value]
        sessions = sorted(sessions, key=lambda item: item.created_at, reverse=True)
        start = max(0, int(offset or 0))
        if limit is None:
            return sessions[start:]
        return sessions[start : start + max(0, int(limit))]

    def get_session(self, session_id: str, *, user_id: str | None = None) -> AgentTeamSession:
        with self._lock:
            session = self.repository.get_session(session_id)
        if user_id is not None and session.user_id != user_id:
            raise PermissionError("Agent team session belongs to another user.")
        return session

    def create_task(
        self,
        *,
        session_id: str,
        user_id: str,
        role: AgentTeamTaskRole | str,
        goal: str,
        title: str | None = None,
        scope: list[str] | None = None,
        dependencies: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
        planning_rationale: str | None = None,
        sort_order: int | None = None,
        task_type: str | None = None,
        task_kind: str | None = None,
        plan_source: str | None = None,
        input_contract: dict | None = None,
        output_contract: dict | None = None,
        evidence_required: list[str] | None = None,
        capability_requirements: list[str] | None = None,
        risk_level: str | None = None,
        write_scope: list[str] | None = None,
        resource_claims: list[str] | None = None,
        replan_policy: dict | None = None,
        context_refs: list[dict] | None = None,
        active_skill_ids: list[str] | None = None,
        skill_resolution_events: list[dict] | None = None,
        create_branch: bool = True,
        branch_name: str | None = None,
        parent_thread_id: str | None = None,
    ) -> AgentTeamTask:
        role_value = AgentTeamTaskRole(role)
        with self._lock:
            session = self.get_session(session_id, user_id=user_id)
        branch_id = None
        child_thread_id = None
        if create_branch and self.branch_service is not None:
            branch_record = self.branch_service.fork_branch(
                parent_thread_id=parent_thread_id or session.root_thread_id,
                user_id=user_id,
                branch_name=branch_name,
                name_source=goal,
                branch_role=_ROLE_TO_BRANCH_ROLE[role_value],
            )
            branch_id = branch_record.branch_id
            child_thread_id = branch_record.child_thread_id

        now = _now()
        task = AgentTeamTask(
            task_id=str(uuid4()),
            session_id=session_id,
            branch_id=branch_id,
            child_thread_id=child_thread_id,
            role=role_value,
            title=title,
            goal=goal,
            scope=list(scope or []),
            dependencies=list(dependencies or []),
            acceptance_criteria=list(acceptance_criteria or []),
            planning_rationale=planning_rationale,
            sort_order=sort_order,
            task_type=task_type,
            task_kind=task_kind,
            plan_source=plan_source,
            input_contract=dict(input_contract) if isinstance(input_contract, dict) else None,
            output_contract=dict(output_contract) if isinstance(output_contract, dict) else None,
            evidence_required=list(evidence_required or []),
            capability_requirements=list(capability_requirements or []),
            risk_level=risk_level,
            write_scope=list(write_scope or []),
            resource_claims=list(resource_claims or []),
            replan_policy=dict(replan_policy) if isinstance(replan_policy, dict) else None,
            context_refs=[dict(item) for item in context_refs or [] if isinstance(item, dict)],
            active_skill_ids=list(active_skill_ids or []),
            skill_resolution_events=[
                dict(item) for item in skill_resolution_events or [] if isinstance(item, dict)
            ],
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self.repository.create_task(task)
            self._touch_session(session_id, status=AgentTeamSessionStatus.RUNNING)
        return task

    def list_tasks(self, *, session_id: str, user_id: str | None = None) -> list[AgentTeamTask]:
        self.get_session(session_id, user_id=user_id)
        with self._lock:
            tasks = self.repository.list_tasks(session_id=session_id)
        return sorted(
            tasks,
            key=lambda item: (
                item.sort_order is None,
                item.sort_order if item.sort_order is not None else 0,
                item.created_at,
            ),
        )

    def get_task(self, task_id: str, *, user_id: str | None = None) -> AgentTeamTask:
        with self._lock:
            task = self.repository.get_task(task_id)
        self.get_session(task.session_id, user_id=user_id)
        return task

    def update_task(
        self,
        *,
        task_id: str,
        user_id: str,
        status: AgentTeamTaskStatus | str | None = None,
        changed_files: list[str] | None = None,
        verification_summary: str | None = None,
        risk_notes: list[str] | None = None,
        acceptance_criteria: list[str] | None = None,
        context_refs: list[dict] | None = None,
        scope: list[str] | None = None,
        dependencies: list[str] | None = None,
        input_contract: dict | None = None,
        output_contract: dict | None = None,
        evidence_required: list[str] | None = None,
        capability_requirements: list[str] | None = None,
        risk_level: str | None = None,
        write_scope: list[str] | None = None,
        resource_claims: list[str] | None = None,
        replan_policy: dict | None = None,
        active_skill_ids: list[str] | None = None,
        skill_resolution_events: list[dict] | None = None,
        agent_run_id: str | None = None,
        delegated_task_id: str | None = None,
        artifact_ids: list[str] | None = None,
        execution_status: str | None = None,
        workspace_id: str | None = None,
        workspace_branch: str | None = None,
        workspace_path: str | None = None,
        base_commit: str | None = None,
        diff_summary: str | None = None,
        test_evidence: list[str] | None = None,
        workspace_status: str | None = None,
        run_status: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        last_error: str | None = None,
    ) -> AgentTeamTask:
        with self._lock:
            task = self.get_task(task_id, user_id=user_id)
            updates: dict[str, object] = {"updated_at": _now()}
            if status is not None:
                updates["status"] = AgentTeamTaskStatus(status)
            if changed_files is not None:
                updates["changed_files"] = _dedupe([*task.changed_files, *changed_files])
            if verification_summary is not None:
                updates["verification_summary"] = verification_summary
            if risk_notes is not None:
                updates["risk_notes"] = _dedupe([*task.risk_notes, *risk_notes])
            if acceptance_criteria is not None:
                updates["acceptance_criteria"] = list(acceptance_criteria)
            if context_refs is not None:
                updates["context_refs"] = [
                    dict(item) for item in context_refs if isinstance(item, dict)
                ]
            if dependencies is not None:
                updates["dependencies"] = list(dependencies)
            if scope is not None:
                updates["scope"] = list(scope)
            if input_contract is not None:
                updates["input_contract"] = dict(input_contract)
            if output_contract is not None:
                updates["output_contract"] = dict(output_contract)
            if evidence_required is not None:
                updates["evidence_required"] = list(evidence_required)
            if capability_requirements is not None:
                updates["capability_requirements"] = list(capability_requirements)
            if risk_level is not None:
                updates["risk_level"] = risk_level
            if write_scope is not None:
                updates["write_scope"] = list(write_scope)
            if resource_claims is not None:
                updates["resource_claims"] = list(resource_claims)
            if replan_policy is not None:
                updates["replan_policy"] = dict(replan_policy)
            if active_skill_ids is not None:
                updates["active_skill_ids"] = list(active_skill_ids)
            if skill_resolution_events is not None:
                updates["skill_resolution_events"] = [
                    dict(item) for item in skill_resolution_events if isinstance(item, dict)
                ]
            if agent_run_id is not None:
                updates["agent_run_id"] = agent_run_id
            if delegated_task_id is not None:
                updates["delegated_task_id"] = delegated_task_id
            if artifact_ids is not None:
                updates["artifact_ids"] = _dedupe([*task.artifact_ids, *artifact_ids])
            if execution_status is not None:
                updates["execution_status"] = execution_status
            if workspace_id is not None:
                updates["workspace_id"] = workspace_id
            if workspace_branch is not None:
                updates["workspace_branch"] = workspace_branch
            if workspace_path is not None:
                updates["workspace_path"] = workspace_path
            if base_commit is not None:
                updates["base_commit"] = base_commit
            if diff_summary is not None:
                updates["diff_summary"] = diff_summary
            if test_evidence is not None:
                updates["test_evidence"] = _dedupe([*task.test_evidence, *test_evidence])
            if workspace_status is not None:
                updates["workspace_status"] = workspace_status
            if run_status is not None:
                updates["run_status"] = run_status
            if started_at is not None:
                updates["started_at"] = started_at
            if finished_at is not None:
                updates["finished_at"] = finished_at
            if last_error is not None:
                updates["last_error"] = last_error
            updated = task.model_copy(update=updates)
            self.repository.save_task(updated)
            self._refresh_session_status(updated.session_id)
        return updated

    def record_task_output(
        self,
        *,
        task_id: str,
        user_id: str,
        kind: AgentTeamArtifactKind | str = AgentTeamArtifactKind.HANDOFF,
        artifact_id: str | None = None,
        summary: str = "",
        changed_files: list[str] | None = None,
        test_evidence: list[str] | None = None,
        workspace_id: str | None = None,
        workspace_branch: str | None = None,
        workspace_path: str | None = None,
        base_commit: str | None = None,
        diff_summary: str | None = None,
        workspace_status: str | None = None,
        risk_notes: list[str] | None = None,
        metadata: dict | None = None,
    ) -> AgentTeamTaskOutput:
        with self._lock:
            task = self.get_task(task_id, user_id=user_id)
            output = AgentTeamTaskOutput(
                output_id=str(uuid4()),
                task_id=task_id,
                kind=AgentTeamArtifactKind(kind),
                artifact_id=artifact_id,
                summary=summary,
                changed_files=list(changed_files or []),
                test_evidence=list(test_evidence or []),
                workspace_id=workspace_id,
                workspace_branch=workspace_branch,
                workspace_path=workspace_path,
                base_commit=base_commit,
                diff_summary=diff_summary,
                workspace_status=workspace_status,
                risk_notes=list(risk_notes or []),
                metadata=dict(metadata or {}),
                created_at=_now(),
            )
            self.repository.add_task_output(output)
            artifact_ids = [*task.output_artifact_ids]
            if artifact_id:
                artifact_ids.append(artifact_id)
            updated = task.model_copy(
                update={
                    "output_artifact_ids": _dedupe(artifact_ids),
                    "changed_files": _dedupe([*task.changed_files, *(changed_files or [])]),
                    "test_evidence": _dedupe([*task.test_evidence, *(test_evidence or [])]),
                    "workspace_id": workspace_id or task.workspace_id,
                    "workspace_branch": workspace_branch or task.workspace_branch,
                    "workspace_path": workspace_path or task.workspace_path,
                    "base_commit": base_commit or task.base_commit,
                    "diff_summary": diff_summary or task.diff_summary,
                    "workspace_status": workspace_status or task.workspace_status,
                    "risk_notes": _dedupe([*task.risk_notes, *(risk_notes or [])]),
                    "verification_summary": self._merge_verification_summary(
                        task.verification_summary,
                        test_evidence or [],
                    ),
                    "updated_at": _now(),
                }
            )
            self.repository.save_task(updated)
            self._touch_session(updated.session_id)
        return output

    def list_task_outputs(
        self, *, task_id: str, user_id: str | None = None
    ) -> list[AgentTeamTaskOutput]:
        self.get_task(task_id, user_id=user_id)
        with self._lock:
            return self.repository.list_task_outputs(task_id=task_id)

    def _touch_session(
        self, session_id: str, *, status: AgentTeamSessionStatus | None = None
    ) -> None:
        session = self.repository.get_session(session_id)
        self.repository.save_session(
            session.model_copy(update={"status": status or session.status, "updated_at": _now()})
        )

    def _refresh_session_status(self, session_id: str) -> None:
        session = self.repository.get_session(session_id)
        if session.status == AgentTeamSessionStatus.CANCELLED:
            self._touch_session(session_id, status=AgentTeamSessionStatus.CANCELLED)
            return
        tasks = self.repository.list_tasks(session_id=session_id)
        if not tasks:
            self._touch_session(session_id)
            return
        if any(task.status in {AgentTeamTaskStatus.QUEUED, AgentTeamTaskStatus.RUNNING} for task in tasks):
            self._touch_session(session_id, status=AgentTeamSessionStatus.RUNNING)
        elif any(task.status == AgentTeamTaskStatus.FAILED for task in tasks):
            self._touch_session(session_id, status=AgentTeamSessionStatus.FAILED)
        elif all(
            task.status in {AgentTeamTaskStatus.DONE, AgentTeamTaskStatus.CANCELLED}
            for task in tasks
        ):
            self._touch_session(session_id, status=AgentTeamSessionStatus.AWAITING_REVIEW)
        else:
            self._touch_session(session_id)


__all__ = ["AgentTeamSessionTaskMixin"]


from threading import RLock

from focus_agent.repositories.agent_team_repository import (
    AgentTeamRepository,
    InMemoryAgentTeamRepository,
)
from focus_agent.services.branches import BranchService
from focus_agent.services.coordination import create_in_memory_coordination_backend

from ..agent_team_workspace import AgentTeamWorkspaceService


class AgentTeamService(
    AgentTeamSessionTaskMixin,
    AgentTeamDispatchMixin,
    AgentTeamPlanningMixin,
    AgentTeamRunMixin,
    AgentTeamMergeMixin,
    AgentTeamHelperMixin,
):
    """Coordinator facade for Agent Team Workbench sessions."""

    def __init__(
        self,
        *,
        branch_service: BranchService | None = None,
        repository: AgentTeamRepository | None = None,
        settings: object | None = None,
        model_factory: object | None = None,
        executor: object | None = None,
        coordination_backend: object | None = None,
        background_work: object | None = None,
        workspace_service: AgentTeamWorkspaceService | None = None,
    ):
        self.branch_service = branch_service
        self.repository = repository or InMemoryAgentTeamRepository()
        self.settings = settings
        self.model_factory = model_factory
        self.executor = executor
        self.coordination_backend = coordination_backend or create_in_memory_coordination_backend()
        self.background_work = background_work
        self.workspace_service = workspace_service or AgentTeamWorkspaceService()
        self._lock = RLock()


__all__ = [
    "AgentTeamService",
    "AgentTeamWorkspaceService",
    "_DEFAULT_DISPATCH_TASKS",
    "_ROLE_TO_BRANCH_ROLE",
    "_dedupe",
    "_now",
]

__all__ = [
    "AgentTeamService",
    "AgentTeamWorkspaceService",
    "_DEFAULT_DISPATCH_TASKS",
    "_ROLE_TO_BRANCH_ROLE",
    "_dedupe",
    "_now",
]
