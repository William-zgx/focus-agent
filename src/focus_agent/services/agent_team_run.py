from __future__ import annotations

from typing import Any

from focus_agent.agent_delegation import AgentDelegationPlan, AgentTask, build_agent_delegation_plan
from focus_agent.agent_execution import (
    DelegatedRunExecutor,
    FakeDelegatedRunExecutor,
    SubagentRegistry,
    executor_for_mode,
    normalize_delegation_execution_mode,
    run_delegated_tasks,
)
from focus_agent.agent_roles import AgentRole
from focus_agent.config import Settings
from focus_agent.core.agent_team import (
    AgentTeamArtifactKind,
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
    agent_role_for_team_task_role,
)

from .agent_team_helpers import _dedupe, _now


_MAX_MISSION_SCHEDULER_WAVES = 16
_MAX_MISSION_SCHEDULER_TASKS = 64

_AGENT_ROLE_TO_TEAM_ROLE: dict[AgentRole, AgentTeamTaskRole] = {
    AgentRole.ORCHESTRATOR: AgentTeamTaskRole.ARCHITECT,
    AgentRole.PLANNER: AgentTeamTaskRole.PLANNER,
    AgentRole.EXECUTOR: AgentTeamTaskRole.BACKEND_EXECUTOR,
    AgentRole.CRITIC: AgentTeamTaskRole.REVIEWER,
    AgentRole.MEMORY_CURATOR: AgentTeamTaskRole.PLANNER,
    AgentRole.SKILL_SCOUT: AgentTeamTaskRole.PLANNER,
}


class AgentTeamRunMixin:
    settings: Any | None
    model_factory: Any | None
    executor: DelegatedRunExecutor | None

    def plan_session(
        self,
        *,
        session_id: str,
        user_id: str,
        create_branches: bool = True,
        parent_thread_id: str | None = None,
    ) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
        session = self.get_session(session_id, user_id=user_id)
        plan = self._build_delegation_plan(session)
        if plan is None or not plan.enabled or not plan.tasks:
            return self.dispatch_default_tasks(
                session_id=session_id,
                user_id=user_id,
                create_branches=create_branches,
                parent_thread_id=parent_thread_id,
            )

        existing = self.list_tasks(session_id=session_id, user_id=user_id)
        existing_by_key = {_task_identity(task): task for task in existing}
        created_by_delegated_id: dict[str, AgentTeamTask] = {}

        for delegated in plan.tasks:
            role = _team_role_for_agent_role(delegated.role)
            key = (role, delegated.goal.strip())
            existing_task = existing_by_key.get(key)
            if existing_task is not None:
                created_by_delegated_id[delegated.task_id] = existing_task
                continue

            dependency_ids = [
                created_by_delegated_id[parent_id].task_id
                for parent_id in [delegated.parent_task_id]
                if parent_id and parent_id in created_by_delegated_id
            ]
            task = self.create_task(
                session_id=session_id,
                user_id=user_id,
                role=role,
                goal=delegated.goal,
                scope=list(delegated.allowed_tools),
                dependencies=dependency_ids,
                acceptance_criteria=list(delegated.acceptance_criteria),
                context_refs=list(delegated.context_refs),
                create_branch=create_branches,
                parent_thread_id=parent_thread_id or session.root_thread_id,
            )
            created_by_delegated_id[delegated.task_id] = task
            existing_by_key[key] = task

        session = self.get_session(session_id, user_id=user_id)
        tasks = self.list_tasks(session_id=session_id, user_id=user_id)
        return session, tasks

    def run_ready_tasks(
        self, *, session_id: str, user_id: str
    ) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
        self.get_session(session_id, user_id=user_id)
        waves = 0
        started = 0

        while waves < _MAX_MISSION_SCHEDULER_WAVES and started < _MAX_MISSION_SCHEDULER_TASKS:
            tasks = self.list_tasks(session_id=session_id, user_id=user_id)
            if any(_is_terminal_blocker(task) for task in tasks):
                break

            done_ids = {task.task_id for task in tasks if task.status == AgentTeamTaskStatus.DONE}
            runnable = [
                task
                for task in tasks
                if _is_runnable_task(task)
                and all(dependency in done_ids for dependency in task.dependencies)
            ]
            if not runnable:
                break

            remaining = _MAX_MISSION_SCHEDULER_TASKS - started
            wave = runnable[:remaining]
            waves += 1
            before = {task.task_id: task.status for task in wave}
            results = [
                self.run_task(task_id=task.task_id, user_id=user_id, scheduler_wave=waves)
                for task in wave
            ]
            started += len(wave)
            if any(_is_terminal_blocker(task) for task in results):
                break
            if all(before.get(task.task_id) == task.status for task in results):
                break

        session = self.get_session(session_id, user_id=user_id)
        return session, self.list_tasks(session_id=session_id, user_id=user_id)

    def run_task(
        self, *, task_id: str, user_id: str, scheduler_wave: int | None = None
    ) -> AgentTeamTask:
        task = self.get_task(task_id, user_id=user_id)
        tasks = self.list_tasks(session_id=task.session_id, user_id=user_id)
        task_by_id = {item.task_id: item for item in tasks}
        unfinished = [
            dependency
            for dependency in task.dependencies
            if task_by_id.get(dependency) is None
            or task_by_id[dependency].status != AgentTeamTaskStatus.DONE
        ]
        if unfinished:
            return task
        if task.status not in {AgentTeamTaskStatus.PENDING, AgentTeamTaskStatus.RUNNING}:
            return task

        started_at = _now()
        task = self.update_task(
            task_id=task_id,
            user_id=user_id,
            status=AgentTeamTaskStatus.RUNNING,
            run_status="running",
            started_at=started_at,
            last_error="",
        )
        delegated = self._to_delegated_task(task)
        result = run_delegated_tasks(
            tasks=[delegated],
            registry=SubagentRegistry.from_settings(
                self.settings or Settings(),
                context_refs=task.context_refs,
            ),
            executor=self._delegated_executor(),
            max_parallel_runs=1,
        )
        if not result:
            finished_at = _now()
            return self.update_task(
                task_id=task_id,
                user_id=user_id,
                status=AgentTeamTaskStatus.BLOCKED,
                run_status="skipped",
                execution_status="skipped",
                finished_at=finished_at,
                last_error="Delegated execution is disabled.",
            )

        run = result[0]
        artifact_ids = [artifact.artifact_id for artifact in run.artifacts]
        status = _team_status_for_run_status(run.status)
        changed_files = _changed_files_for_run(run)
        test_evidence = _test_evidence_for_run(run)
        risk_notes = _risk_notes_for_run(run)
        self.record_task_output(
            task_id=task_id,
            user_id=user_id,
            kind=_artifact_kind_for_task(task),
            artifact_id=artifact_ids[0] if artifact_ids else None,
            summary=run.summary,
            changed_files=changed_files,
            test_evidence=test_evidence,
            risk_notes=risk_notes,
            metadata={
                "execution": {
                    "agent_run_id": run.run_id,
                    "delegated_task_id": run.task_id,
                    "artifact_ids": artifact_ids,
                    "execution_status": run.status,
                    "execution_mode": run.execution_mode,
                    "started_at": run.started_at,
                    "finished_at": run.finished_at,
                    "model_id": run.model_id,
                },
                "scheduler": {
                    "wave": scheduler_wave,
                    "max_waves": _MAX_MISSION_SCHEDULER_WAVES,
                    "max_tasks": _MAX_MISSION_SCHEDULER_TASKS,
                },
                "artifacts": [artifact.model_dump(mode="json") for artifact in run.artifacts],
                "run": run.model_dump(mode="json"),
            },
        )
        return self.update_task(
            task_id=task_id,
            user_id=user_id,
            status=status,
            run_status=run.status,
            agent_run_id=run.run_id,
            delegated_task_id=run.task_id,
            artifact_ids=artifact_ids,
            execution_status=run.status,
            changed_files=changed_files,
            verification_summary=run.summary,
            risk_notes=risk_notes,
            started_at=run.started_at or started_at,
            finished_at=run.finished_at or _now(),
            last_error=run.error or "",
        )

    def get_session_view(self, *, session_id: str, user_id: str) -> dict[str, Any]:
        session = self.get_session(session_id, user_id=user_id)
        tasks = self.list_tasks(session_id=session_id, user_id=user_id)
        outputs = [
            output
            for task in tasks
            for output in self.repository.list_task_outputs(task_id=task.task_id)
        ]
        artifacts = [
            artifact
            for output in outputs
            for artifact in output.metadata.get("artifacts", [])
            if isinstance(artifact, dict)
        ]
        merge_bundle = session.latest_merge_bundle
        return {
            "session": session.model_dump(mode="json"),
            "tasks": [task.model_dump(mode="json") for task in tasks],
            "items": [task.model_dump(mode="json") for task in tasks],
            "count": len(tasks),
            "outputs": [output.model_dump(mode="json") for output in outputs],
            "artifacts": artifacts,
            "merge_bundle": merge_bundle,
            "planning": {
                "source": session.planning_source,
                "rationale": session.planning_rationale,
                "planner_model_id": session.planner_model_id,
                "generated_at": session.plan_generated_at,
                "plan_hash": session.plan_hash,
                "error": session.planning_error,
                "task_count": len(tasks),
            },
            "scheduler": _scheduler_state(tasks),
        }

    def _build_delegation_plan(self, session: AgentTeamSession) -> AgentDelegationPlan | None:
        if self.settings is None:
            return None
        return build_agent_delegation_plan(settings=self.settings, task_text=session.goal)

    def _to_delegated_task(self, task: AgentTeamTask) -> AgentTask:
        return AgentTask(
            task_id=task.task_id,
            role=agent_role_for_team_task_role(task.role),
            goal=task.goal,
            constraints=[f"Scope: {item}" for item in task.scope],
            acceptance_criteria=list(task.acceptance_criteria),
            context_refs=list(task.context_refs),
            run_isolation_key=f"agent-team:{task.session_id}:{task.task_id}",
        )

    def _delegated_executor(self) -> DelegatedRunExecutor | None:
        if self.executor is not None:
            return self.executor
        if self.settings is None:
            return FakeDelegatedRunExecutor()
        mode = normalize_delegation_execution_mode(
            getattr(self.settings, "agent_delegation_execution_mode", "observe")
        )
        return executor_for_mode(mode, model_factory=self.model_factory, settings=self.settings)


def _task_identity(task: AgentTeamTask) -> tuple[AgentTeamTaskRole, str]:
    return (task.role, task.goal.strip())


def _team_role_for_agent_role(role: AgentRole) -> AgentTeamTaskRole:
    return _AGENT_ROLE_TO_TEAM_ROLE.get(role, AgentTeamTaskRole.BACKEND_EXECUTOR)


def _is_runnable_task(task: AgentTeamTask) -> bool:
    if task.status == AgentTeamTaskStatus.PENDING:
        return True
    return (
        task.status == AgentTeamTaskStatus.RUNNING
        and not task.run_status
        and not task.execution_status
        and not task.agent_run_id
    )


def _is_terminal_blocker(task: AgentTeamTask) -> bool:
    return task.status in {
        AgentTeamTaskStatus.BLOCKED,
        AgentTeamTaskStatus.FAILED,
        AgentTeamTaskStatus.CANCELLED,
    }


def _team_status_for_run_status(status: str) -> AgentTeamTaskStatus:
    if status == "completed":
        return AgentTeamTaskStatus.DONE
    if status == "failed":
        return AgentTeamTaskStatus.FAILED
    return AgentTeamTaskStatus.BLOCKED


def _artifact_kind_for_task(task: AgentTeamTask) -> AgentTeamArtifactKind:
    if task.role == AgentTeamTaskRole.PLANNER:
        return AgentTeamArtifactKind.PLAN
    if task.role in {AgentTeamTaskRole.TEST_ENGINEER, AgentTeamTaskRole.VERIFIER}:
        return AgentTeamArtifactKind.TEST_REPORT
    if task.role == AgentTeamTaskRole.REVIEWER:
        return AgentTeamArtifactKind.REVIEW_REPORT
    if task.role in {AgentTeamTaskRole.BACKEND_EXECUTOR, AgentTeamTaskRole.FRONTEND_EXECUTOR}:
        return AgentTeamArtifactKind.PATCH_SUMMARY
    return AgentTeamArtifactKind.HANDOFF


def _test_evidence_for_run(run: Any) -> list[str]:
    items = [f"delegated {run.execution_mode} run {run.run_id}: {run.status}"]
    items.extend(_metadata_list_values(run, "test_evidence", "verification_evidence", "tests"))
    return _dedupe(items)


def _changed_files_for_run(run: Any) -> list[str]:
    return _dedupe(_metadata_list_values(run, "changed_files", "modified_files", "files"))


def _risk_notes_for_run(run: Any) -> list[str]:
    items = [run.error] if getattr(run, "error", None) else []
    items.extend(_metadata_list_values(run, "risk_notes", "risk_items", "risks"))
    return _dedupe(items)


def _metadata_list_values(run: Any, *keys: str) -> list[str]:
    values: list[str] = []
    payloads: list[Any] = [run.model_dump(mode="json") if hasattr(run, "model_dump") else {}]
    payloads.extend(
        getattr(artifact, "payload", None) for artifact in getattr(run, "artifacts", []) or []
    )
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key in keys:
            raw = payload.get(key)
            if isinstance(raw, str):
                values.append(raw)
            elif isinstance(raw, list):
                values.extend(str(item) for item in raw if item)
    return values


def _scheduler_state(tasks: list[AgentTeamTask]) -> dict[str, object]:
    done_ids = {task.task_id for task in tasks if task.status == AgentTeamTaskStatus.DONE}
    blocked_ids = [task.task_id for task in tasks if _is_terminal_blocker(task)]
    ready_ids = [
        task.task_id
        for task in tasks
        if _is_runnable_task(task)
        and all(dependency in done_ids for dependency in task.dependencies)
    ]
    waiting_ids = [
        task.task_id
        for task in tasks
        if _is_runnable_task(task)
        and any(dependency not in done_ids for dependency in task.dependencies)
    ]
    return {
        "ready_task_ids": ready_ids,
        "waiting_task_ids": waiting_ids,
        "blocked_task_ids": blocked_ids,
        "max_waves": _MAX_MISSION_SCHEDULER_WAVES,
        "max_tasks": _MAX_MISSION_SCHEDULER_TASKS,
    }


__all__ = ["AgentTeamRunMixin"]
