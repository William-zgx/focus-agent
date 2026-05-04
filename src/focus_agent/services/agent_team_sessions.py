from __future__ import annotations

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

from .agent_team_helpers import _ROLE_TO_BRANCH_ROLE, _dedupe, _now


class AgentTeamSessionTaskMixin:
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
        agent_run_id: str | None = None,
        delegated_task_id: str | None = None,
        artifact_ids: list[str] | None = None,
        execution_status: str | None = None,
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
            if agent_run_id is not None:
                updates["agent_run_id"] = agent_run_id
            if delegated_task_id is not None:
                updates["delegated_task_id"] = delegated_task_id
            if artifact_ids is not None:
                updates["artifact_ids"] = _dedupe([*task.artifact_ids, *artifact_ids])
            if execution_status is not None:
                updates["execution_status"] = execution_status
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
        tasks = self.repository.list_tasks(session_id=session_id)
        if not tasks:
            self._touch_session(session_id)
            return
        if any(task.status == AgentTeamTaskStatus.RUNNING for task in tasks):
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
