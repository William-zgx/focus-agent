from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Iterable
from uuid import uuid4

from focus_agent.core.agent_team import (
    AgentTeamArtifactKind,
    AgentTeamMergeBundle,
    AgentTeamMergeDecision,
    AgentTeamRecommendedAction,
    AgentTeamSession,
    AgentTeamSessionStatus,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)
from focus_agent.core.branching import BranchRole
from focus_agent.repositories.agent_team_repository import AgentTeamRepository, InMemoryAgentTeamRepository
from focus_agent.services.branches import BranchService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

_DEFAULT_DISPATCH_TASKS: tuple[tuple[AgentTeamTaskRole, str, tuple[str, ...], tuple[AgentTeamTaskRole, ...]], ...] = (
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
        ("frontend-sdk/**", "apps/web/src/features/agent-team/**", "apps/web/src/pages/agent-team/**"),
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


class AgentTeamService:
    """Coordinator for Agent Team Workbench sessions."""

    def __init__(
        self,
        *,
        branch_service: BranchService | None = None,
        repository: AgentTeamRepository | None = None,
    ):
        self.branch_service = branch_service
        self.repository = repository or InMemoryAgentTeamRepository()
        self._lock = RLock()

    def create_session(
        self,
        *,
        root_thread_id: str,
        user_id: str,
        title: str | None = None,
        goal: str,
    ) -> AgentTeamSession:
        now = _now()
        session = AgentTeamSession(
            session_id=str(uuid4()),
            root_thread_id=root_thread_id,
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

    def list_sessions(self, *, user_id: str | None = None) -> list[AgentTeamSession]:
        with self._lock:
            sessions = self.repository.list_sessions(user_id=user_id)
        return sorted(sessions, key=lambda item: item.created_at, reverse=True)

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
        scope: list[str] | None = None,
        dependencies: list[str] | None = None,
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
                branch_name=branch_name or self._default_branch_name(role_value),
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
            goal=goal,
            scope=list(scope or []),
            dependencies=list(dependencies or []),
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
        return sorted(tasks, key=lambda item: item.created_at)

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

    def list_task_outputs(self, *, task_id: str, user_id: str | None = None) -> list[AgentTeamTaskOutput]:
        self.get_task(task_id, user_id=user_id)
        with self._lock:
            return self.repository.list_task_outputs(task_id=task_id)

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
                goal=f"{goal_template}\n\nSession goal: {session.goal}",
                scope=list(scope),
                dependencies=dependencies,
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
        return session, tasks

    def prepare_merge_bundle(self, *, session_id: str, user_id: str) -> AgentTeamMergeBundle:
        session = self.get_session(session_id, user_id=user_id)
        tasks = self.list_tasks(session_id=session_id, user_id=user_id)
        outputs = [output for task in tasks for output in self.repository.list_task_outputs(task_id=task.task_id)]
        accepted = [task.task_id for task in tasks if task.status == AgentTeamTaskStatus.DONE]
        rejected = [
            task.task_id
            for task in tasks
            if task.status in {AgentTeamTaskStatus.FAILED, AgentTeamTaskStatus.CANCELLED}
        ]
        blocked = [task for task in tasks if task.status == AgentTeamTaskStatus.BLOCKED]
        pending = [
            task
            for task in tasks
            if task.status in {AgentTeamTaskStatus.PENDING, AgentTeamTaskStatus.RUNNING}
        ]
        risk_items = _dedupe([note for task in tasks for note in task.risk_notes] + [note for output in outputs for note in output.risk_notes])
        test_evidence = _dedupe(
            [task.verification_summary or "" for task in tasks]
            + [evidence for output in outputs for evidence in output.test_evidence]
        )
        key_findings = _dedupe(output.summary for output in outputs if output.summary)
        changed_files = _dedupe([path for task in tasks for path in task.changed_files] + [path for output in outputs for path in output.changed_files])
        open_questions = _dedupe(
            [f"{task.role.value}: {self._compact_task_goal(task.goal)}" for task in blocked]
            + [f"Pending {task.role.value}: {self._compact_task_goal(task.goal)}" for task in pending]
        )
        recommended = self._recommended_action(
            accepted_count=len(accepted),
            rejected_count=len(rejected),
            pending_count=len(pending),
            blocked_count=len(blocked),
            risk_count=len(risk_items),
        )
        bundle = AgentTeamMergeBundle(
            session_id=session_id,
            summary=self._bundle_summary(session=session, tasks=tasks, key_findings=key_findings),
            accepted_tasks=accepted,
            rejected_tasks=rejected,
            key_findings=key_findings,
            changed_files=changed_files,
            test_evidence=test_evidence,
            open_questions=open_questions,
            risk_items=risk_items,
            recommended_next_action=recommended,
        )
        with self._lock:
            self.repository.save_session(
                session.model_copy(
                    update={
                        "status": AgentTeamSessionStatus.AWAITING_REVIEW,
                        "latest_merge_bundle": bundle.model_dump(mode="json"),
                        "updated_at": _now(),
                    }
                )
            )
        return bundle

    def apply_merge_decision(
        self,
        *,
        session_id: str,
        user_id: str,
        approved: bool,
        action: AgentTeamRecommendedAction | str | None = None,
        rationale: str | None = None,
        accepted_tasks: list[str] | None = None,
        rejected_tasks: list[str] | None = None,
    ) -> AgentTeamMergeDecision:
        session = self.get_session(session_id, user_id=user_id)
        bundle_payload = dict(session.latest_merge_bundle or {})
        resolved_action = AgentTeamRecommendedAction(
            action or bundle_payload.get("recommended_next_action") or AgentTeamRecommendedAction.MERGE
        )
        decision = AgentTeamMergeDecision(
            decision_id=str(uuid4()),
            session_id=session_id,
            approved=approved,
            action=resolved_action,
            rationale=rationale,
            accepted_tasks=list(accepted_tasks if accepted_tasks is not None else bundle_payload.get("accepted_tasks") or []),
            rejected_tasks=list(rejected_tasks if rejected_tasks is not None else bundle_payload.get("rejected_tasks") or []),
            created_at=_now(),
        )
        next_status = AgentTeamSessionStatus.COMPLETED if approved and resolved_action == AgentTeamRecommendedAction.MERGE else AgentTeamSessionStatus.AWAITING_REVIEW
        if resolved_action == AgentTeamRecommendedAction.DISCARD:
            next_status = AgentTeamSessionStatus.CANCELLED
        with self._lock:
            self.repository.save_session(
                session.model_copy(
                    update={
                        "status": next_status,
                        "merge_decision": decision.model_dump(mode="json"),
                        "updated_at": _now(),
                    }
                )
            )
        return decision

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

    @staticmethod
    def _bundle_summary(*, session: AgentTeamSession, tasks: list[AgentTeamTask], key_findings: list[str]) -> str:
        done = len([task for task in tasks if task.status == AgentTeamTaskStatus.DONE])
        total = len(tasks)
        headline = f"{session.title}: {done}/{total} tasks ready for merge."
        if key_findings:
            return f"{headline} Top finding: {key_findings[0]}"
        return headline

    def _touch_session(self, session_id: str, *, status: AgentTeamSessionStatus | None = None) -> None:
        session = self.repository.get_session(session_id)
        self.repository.save_session(
            session.model_copy(update={"status": status or session.status, "updated_at": _now()})
        )

    def _refresh_session_status(self, session_id: str) -> None:
        tasks = self.repository.list_tasks(session_id=session_id)
        if not tasks:
            self._touch_session(session_id)
            return
        if any(task.status == AgentTeamTaskStatus.RUNNING for task in tasks):
            self._touch_session(session_id, status=AgentTeamSessionStatus.RUNNING)
        elif any(task.status == AgentTeamTaskStatus.FAILED for task in tasks):
            self._touch_session(session_id, status=AgentTeamSessionStatus.FAILED)
        elif all(task.status in {AgentTeamTaskStatus.DONE, AgentTeamTaskStatus.CANCELLED} for task in tasks):
            self._touch_session(session_id, status=AgentTeamSessionStatus.AWAITING_REVIEW)
        else:
            self._touch_session(session_id)


__all__ = ["AgentTeamService"]
