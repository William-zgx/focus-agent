from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

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
    AgentTeamSessionStatus,
    AgentTeamTask,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
    agent_role_for_team_task_role,
)
from focus_agent.services.coordination import BackgroundJobSpec

from .agent_team_helpers import _dedupe, _now


_MAX_MISSION_SCHEDULER_WAVES = 16
_MAX_MISSION_SCHEDULER_TASKS = 64
_AGENT_TEAM_TASK_CLAIM_TTL_SECONDS = 300.0


@dataclass(frozen=True)
class _TaskExecutionResult:
    session_id: str
    final_status: AgentTeamTaskStatus
    run_status: str
    execution_status: str
    last_error: str
    task_updates: dict[str, Any]
    output: dict[str, Any] | None = None

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
    coordination_backend: Any | None
    background_work: Any | None

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
        self, *, session_id: str, user_id: str, task_ids: list[str] | None = None
    ) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
        return self.run_ready_tasks_once(session_id=session_id, user_id=user_id, task_ids=task_ids)

    def run_ready_tasks_once(
        self, *, session_id: str, user_id: str, task_ids: list[str] | None = None
    ) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
        session = self.get_session(session_id, user_id=user_id)
        if session.status == AgentTeamSessionStatus.CANCELLED:
            return session, self.list_tasks(session_id=session_id, user_id=user_id)
        max_parallel = _max_parallel_runs_for(self.settings)
        selected_task_ids = {task_id for task_id in task_ids or [] if task_id}
        with self._lock:
            tasks = self.repository.list_tasks(session_id=session_id)
            active_count = sum(
                1
                for task in tasks
                if task.status in {AgentTeamTaskStatus.QUEUED, AgentTeamTaskStatus.RUNNING}
            )
            remaining_capacity = max(0, max_parallel - active_count)
            if remaining_capacity <= 0:
                self._refresh_session_status(session_id)
                session = self.repository.get_session(session_id)
                return session, self.repository.list_tasks(session_id=session_id)
            runnable = self.repository.list_runnable_tasks(
                session_id=session_id,
                limit=_MAX_MISSION_SCHEDULER_TASKS,
            )
            if selected_task_ids:
                runnable = [task for task in runnable if task.task_id in selected_task_ids]
            runnable = runnable[: min(remaining_capacity, _MAX_MISSION_SCHEDULER_TASKS)]
            for task in runnable:
                queued = task.model_copy(
                    update={
                        "status": AgentTeamTaskStatus.QUEUED,
                        "run_status": "queued",
                        "execution_status": "queued",
                        "queued_at": task.queued_at or _now(),
                        "execution_mode": _agent_team_execution_mode(self.settings),
                        "last_error": "",
                        "updated_at": _now(),
                    }
                )
                self.repository.save_task(queued)
                self._enqueue_task_run(task_id=queued.task_id, user_id=user_id)
            if runnable:
                self._touch_session(session_id, status=AgentTeamSessionStatus.RUNNING)
            else:
                self._refresh_session_status(session_id)
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
        if task.status not in {
            AgentTeamTaskStatus.PENDING,
            AgentTeamTaskStatus.QUEUED,
            AgentTeamTaskStatus.RUNNING,
        }:
            return task
        if task.cancel_requested_at:
            return self.update_task(
                task_id=task_id,
                user_id=user_id,
                status=AgentTeamTaskStatus.CANCELLED,
                run_status="cancelled",
                execution_status="cancelled",
                finished_at=_now(),
                last_error="Task was cancelled before execution.",
            )

        queued = self.update_task(
            task_id=task_id,
            user_id=user_id,
            status=AgentTeamTaskStatus.QUEUED,
            run_status="queued",
            execution_status="queued",
            started_at=None,
            finished_at=None,
            last_error="",
        )
        queued = queued.model_copy(
            update={
                "queued_at": queued.queued_at or _now(),
                "execution_mode": _agent_team_execution_mode(self.settings),
                "updated_at": _now(),
            }
        )
        with self._lock:
            self.repository.save_task(queued)
            self._touch_session(queued.session_id, status=AgentTeamSessionStatus.RUNNING)
        self._enqueue_task_run(task_id=task_id, user_id=user_id)
        return self.get_task(task_id, user_id=user_id)

    def run_task_claimed(self, *, task_id: str, user_id: str) -> AgentTeamTask:
        owner = f"agent-team:{uuid4().hex}"
        with self._lock:
            claimed = self.repository.claim_task(
                task_id=task_id,
                owner=owner,
                ttl_seconds=_AGENT_TEAM_TASK_CLAIM_TTL_SECONDS,
            )
        if claimed is None:
            return self.get_task(task_id, user_id=user_id)
        try:
            result = self._execute_task_body(claimed, user_id=user_id)
        except Exception as exc:  # noqa: BLE001
            current = self.get_task(task_id, user_id=user_id)
            final_status = (
                AgentTeamTaskStatus.FAILED
                if current.attempt >= max(1, int(current.max_attempts or 1))
                else AgentTeamTaskStatus.QUEUED
            )
            with self._lock:
                task = self.repository.release_task_claim(
                    task_id=task_id,
                    claim_token=claimed.claim_token or "",
                    final_status=final_status,
                    error=str(exc),
                )
                if final_status == AgentTeamTaskStatus.QUEUED:
                    self._enqueue_task_run(task_id=task_id, user_id=user_id)
                self._refresh_session_status(task.session_id)
            return task

        latest = self.get_task(task_id, user_id=user_id)
        final_status = result.final_status
        if latest.cancel_requested_at:
            final_status = AgentTeamTaskStatus.CANCELLED
        with self._lock:
            claim_alive = self.repository.heartbeat_task_claim(
                task_id=task_id,
                claim_token=claimed.claim_token or "",
                ttl_seconds=_AGENT_TEAM_TASK_CLAIM_TTL_SECONDS,
            )
            if not claim_alive:
                current = self.get_task(task_id, user_id=user_id)
                stale_status = (
                    AgentTeamTaskStatus.FAILED
                    if current.attempt >= max(1, int(current.max_attempts or 1))
                    else AgentTeamTaskStatus.QUEUED
                )
                released = self.repository.release_task_claim(
                    task_id=task_id,
                    claim_token=claimed.claim_token or "",
                    final_status=stale_status,
                    error="Task claim was lost before completion could be committed.",
                )
                if released.claim_token is None and stale_status == AgentTeamTaskStatus.QUEUED:
                    self._enqueue_task_run(task_id=task_id, user_id=user_id)
                self._refresh_session_status(released.session_id)
                return self.get_task(task_id, user_id=user_id)
            if result.output is not None and final_status != AgentTeamTaskStatus.CANCELLED:
                self.record_task_output(task_id=task_id, user_id=user_id, **result.output)
            if final_status == AgentTeamTaskStatus.CANCELLED:
                latest = self.update_task(
                    task_id=task_id,
                    user_id=user_id,
                    status=AgentTeamTaskStatus.CANCELLED,
                    run_status="cancelled",
                    execution_status="cancelled",
                    finished_at=_now(),
                    last_error=latest.last_error or "Task was cancelled before completion.",
                )
            else:
                latest = self.update_task(
                    task_id=task_id,
                    user_id=user_id,
                    status=final_status,
                    run_status=result.run_status,
                    execution_status=result.execution_status,
                    last_error=result.last_error,
                    **result.task_updates,
                )
            released = self.repository.release_task_claim(
                task_id=task_id,
                claim_token=claimed.claim_token or "",
                final_status=final_status,
                error=latest.last_error,
            )
            self._refresh_session_status(released.session_id)
        if final_status == AgentTeamTaskStatus.DONE:
            self.maybe_schedule_next_wave(session_id=released.session_id, user_id=user_id)
        return released

    def maybe_schedule_next_wave(self, *, session_id: str, user_id: str) -> None:
        session = self.get_session(session_id, user_id=user_id)
        if session.status == AgentTeamSessionStatus.CANCELLED:
            return
        tasks = self.list_tasks(session_id=session_id, user_id=user_id)
        if any(task.status in {AgentTeamTaskStatus.QUEUED, AgentTeamTaskStatus.RUNNING} for task in tasks):
            return
        if any(_is_runnable_task(task) for task in tasks):
            self.run_ready_tasks_once(session_id=session_id, user_id=user_id)

    def cancel_session(self, *, session_id: str, user_id: str) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
        session = self.get_session(session_id, user_id=user_id)
        now = _now()
        with self._lock:
            for task in self.repository.list_tasks(session_id=session_id):
                if task.status in {
                    AgentTeamTaskStatus.PENDING,
                    AgentTeamTaskStatus.QUEUED,
                    AgentTeamTaskStatus.RUNNING,
                }:
                    self.repository.save_task(
                        task.model_copy(
                            update={
                                "status": AgentTeamTaskStatus.CANCELLED
                                if task.status != AgentTeamTaskStatus.RUNNING
                                else task.status,
                                "cancel_requested_at": task.cancel_requested_at or now,
                                "run_status": "cancelled"
                                if task.status != AgentTeamTaskStatus.RUNNING
                                else task.run_status,
                                "execution_status": "cancel_requested",
                                "updated_at": now,
                            }
                        )
                    )
            session = session.model_copy(
                update={"status": AgentTeamSessionStatus.CANCELLED, "updated_at": now}
            )
            self.repository.save_session(session)
        return session, self.list_tasks(session_id=session_id, user_id=user_id)

    def retry_task(self, *, task_id: str, user_id: str) -> AgentTeamTask:
        task = self.get_task(task_id, user_id=user_id)
        if task.status not in {
            AgentTeamTaskStatus.FAILED,
            AgentTeamTaskStatus.BLOCKED,
            AgentTeamTaskStatus.CANCELLED,
        }:
            return task
        tasks = self.list_tasks(session_id=task.session_id, user_id=user_id)
        done_ids = {item.task_id for item in tasks if item.status == AgentTeamTaskStatus.DONE}
        dependencies_satisfied = all(dependency in done_ids for dependency in task.dependencies)
        now = _now()
        status = AgentTeamTaskStatus.QUEUED if dependencies_satisfied else AgentTeamTaskStatus.PENDING
        with self._lock:
            reset = task.model_copy(
                update={
                    "status": status,
                    "run_status": "queued" if dependencies_satisfied else None,
                    "execution_status": "queued" if dependencies_satisfied else None,
                    "claim_token": None,
                    "claim_owner": None,
                    "claimed_until": None,
                    "queued_at": now if dependencies_satisfied else None,
                    "heartbeat_at": None,
                    "cancel_requested_at": None,
                    "agent_run_id": None,
                    "delegated_task_id": None,
                    "artifact_ids": [],
                    "changed_files": [],
                    "verification_summary": None,
                    "risk_notes": [],
                    "finished_at": None,
                    "last_error": "",
                    "updated_at": now,
                }
            )
            self.repository.save_task(reset)
            if dependencies_satisfied:
                self._touch_session(reset.session_id, status=AgentTeamSessionStatus.RUNNING)
            else:
                self._refresh_session_status(reset.session_id)
        if dependencies_satisfied:
            self._enqueue_task_run(task_id=task_id, user_id=user_id)
        return self.get_task(task_id, user_id=user_id)

    def cancel_task(self, *, task_id: str, user_id: str) -> AgentTeamTask:
        task = self.get_task(task_id, user_id=user_id)
        if task.status not in {
            AgentTeamTaskStatus.PENDING,
            AgentTeamTaskStatus.QUEUED,
            AgentTeamTaskStatus.RUNNING,
        }:
            return task
        now = _now()
        status = (
            AgentTeamTaskStatus.RUNNING
            if task.status == AgentTeamTaskStatus.RUNNING
            else AgentTeamTaskStatus.CANCELLED
        )
        with self._lock:
            updated = task.model_copy(
                update={
                    "status": status,
                    "cancel_requested_at": task.cancel_requested_at or now,
                    "run_status": "cancelled" if status == AgentTeamTaskStatus.CANCELLED else task.run_status,
                    "execution_status": "cancel_requested",
                    "finished_at": now if status == AgentTeamTaskStatus.CANCELLED else task.finished_at,
                    "updated_at": now,
                }
            )
            self.repository.save_task(updated)
            self._refresh_session_status(updated.session_id)
        return self.get_task(task_id, user_id=user_id)

    def _execute_task_body(
        self, task: AgentTeamTask, *, user_id: str, scheduler_wave: int | None = None
    ) -> _TaskExecutionResult:
        task = self.get_task(task.task_id, user_id=user_id)
        if scheduler_wave is None:
            scheduler_wave = _task_wave(task, self.list_tasks(session_id=task.session_id, user_id=user_id))
        if task.cancel_requested_at:
            return _TaskExecutionResult(
                session_id=task.session_id,
                final_status=AgentTeamTaskStatus.CANCELLED,
                run_status="cancelled",
                execution_status="cancelled",
                last_error="Task was cancelled before execution.",
                task_updates={"finished_at": _now()},
            )

        started_at = _now()
        task = self.update_task(
            task_id=task.task_id,
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
            return _TaskExecutionResult(
                session_id=task.session_id,
                final_status=AgentTeamTaskStatus.BLOCKED,
                run_status="skipped",
                execution_status="skipped",
                last_error="Delegated execution is disabled.",
                task_updates={"finished_at": finished_at},
            )

        run = result[0]
        artifact_ids = [artifact.artifact_id for artifact in run.artifacts]
        status = _team_status_for_run_status(run.status)
        changed_files = _changed_files_for_run(run)
        test_evidence = _test_evidence_for_run(run)
        risk_notes = _risk_notes_for_run(run)
        output = {
            "kind": _artifact_kind_for_task(task),
            "artifact_id": artifact_ids[0] if artifact_ids else None,
            "summary": run.summary,
            "changed_files": changed_files,
            "test_evidence": test_evidence,
            "risk_notes": risk_notes,
            "metadata": {
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
        }
        return _TaskExecutionResult(
            session_id=task.session_id,
            final_status=status,
            run_status=run.status,
            execution_status=run.status,
            last_error=run.error or "",
            task_updates={
                "agent_run_id": run.run_id,
                "delegated_task_id": run.task_id,
                "artifact_ids": artifact_ids,
                "changed_files": changed_files,
                "verification_summary": run.summary,
                "risk_notes": risk_notes,
                "started_at": run.started_at or started_at,
                "finished_at": run.finished_at or _now(),
            },
            output=output,
        )

    def _enqueue_task_run(self, *, task_id: str, user_id: str) -> bool:
        key = f"agent-team:task:{task_id}"
        payload = {"task_id": task_id, "user_id": user_id}
        if self._enqueue_durable_job(
            kind="agent_team_run_task",
            key=key,
            payload=payload,
            max_attempts=2,
            dedupe_policy="replace",
        ):
            return True
        submit = getattr(self.background_work, "submit", None)
        if callable(submit):
            return bool(
                submit(
                    key=key,
                    func=self.run_task_claimed,
                    task_id=task_id,
                    user_id=user_id,
                )
            )
        self.run_task_claimed(task_id=task_id, user_id=user_id)
        return True

    def _enqueue_durable_job(
        self,
        *,
        kind: str,
        key: str,
        payload: dict[str, Any],
        max_attempts: int = 1,
        dedupe_policy: str = "skip",
    ) -> bool:
        if _agent_team_execution_mode(self.settings).strip().lower() != "durable":
            return False
        backend = getattr(self.coordination_backend, "job_deduper", None)
        enqueue = getattr(backend, "enqueue_job", None)
        if not callable(enqueue):
            return False
        try:
            return bool(
                enqueue(
                    BackgroundJobSpec(
                        kind=kind,
                        key=key,
                        payload=payload,
                        max_attempts=max_attempts,
                        dedupe_policy=dedupe_policy,
                    )
                )
            )
        except Exception:  # noqa: BLE001
            return False

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
            "run": _run_metadata(tasks=tasks, settings=self.settings),
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


def _max_parallel_runs_for(settings: Any | None) -> int:
    return max(1, min(16, int(getattr(settings, "agent_role_max_parallel_runs", 2) or 2)))


def _agent_team_execution_mode(settings: Any | None) -> str:
    return str(getattr(settings, "background_job_execution", "best_effort") or "best_effort")


def _run_metadata(*, tasks: list[AgentTeamTask], settings: Any | None) -> dict[str, Any]:
    return {
        "execution_mode": _agent_team_execution_mode(settings),
        "scheduled_task_ids": [
            task.task_id
            for task in tasks
            if task.status in {AgentTeamTaskStatus.QUEUED, AgentTeamTaskStatus.RUNNING}
        ],
        "running_task_ids": [
            task.task_id for task in tasks if task.status == AgentTeamTaskStatus.RUNNING
        ],
        "max_parallel_runs": _max_parallel_runs_for(settings),
    }


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


def _task_wave(task: AgentTeamTask, tasks: list[AgentTeamTask]) -> int:
    by_id = {item.task_id: item for item in tasks}
    seen: set[str] = set()

    def depth(item: AgentTeamTask) -> int:
        if item.task_id in seen:
            return 1
        seen.add(item.task_id)
        parents = [by_id[dependency] for dependency in item.dependencies if dependency in by_id]
        if not parents:
            return 1
        return 1 + max(depth(parent) for parent in parents)

    return depth(task)


__all__ = ["AgentTeamRunMixin"]
