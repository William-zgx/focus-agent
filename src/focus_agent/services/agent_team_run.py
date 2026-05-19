from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from focus_agent.config import Settings
from focus_agent.core.agent_team import (
    AgentTeamSession,
    AgentTeamSessionStatus,
    AgentTeamTask,
    AgentTeamTaskStatus,
    agent_role_for_team_task_role,
)
from focus_agent.core.repo_call import has_repo_method
from focus_agent.delegation.delegation import (
    AgentDelegationPlan,
    AgentTask,
    build_agent_delegation_plan,
)
from focus_agent.delegation.execution import (
    DelegatedRunExecutor,
    FakeDelegatedRunExecutor,
    SubagentRegistry,
    executor_for_mode,
    normalize_delegation_execution_mode,
    run_delegated_tasks,
)
from focus_agent.multi_agent.contracts import (
    AgentMessageType,
    DAGTaskNode,
    FailureStrategy,
    LockMode,
    ResourceClaim,
)
from focus_agent.multi_agent.dag_scheduler import DAGScheduler
from focus_agent.multi_agent.errors import DAGValidationError
from focus_agent.multi_agent.failure_handler import FailureHandler
from focus_agent.services.coordination import BackgroundJobSpec

from .agent_team_helpers import _dedupe, _now
from .agent_team_run_helpers import (
    _AGENT_TEAM_TASK_CLAIM_TTL_SECONDS,
    _MAX_MISSION_SCHEDULER_TASKS,
    _MAX_MISSION_SCHEDULER_WAVES,
    _agent_team_execution_mode,
    _allowed_tools_for_task,
    _artifact_kind_for_task,
    _changed_files_for_run,
    _is_runnable_task,
    _is_writable_team_task,
    _max_parallel_runs_for,
    _risk_notes_for_run,
    _run_metadata,
    _scheduler_state,
    _should_use_task_workspace,
    _task_identity,
    _task_wave,
    _team_role_for_agent_role,
    _team_status_for_run_status,
    _test_evidence_for_run,
    _workspace_metadata_for_run,
)
from .agent_team_workspace import (
    AgentTeamWorkspace,
    AgentTeamWorkspaceService,
    AgentTeamWorkspaceStatus,
)


@dataclass(frozen=True)
class _TaskExecutionResult:
    session_id: str
    final_status: AgentTeamTaskStatus
    run_status: str
    execution_status: str
    last_error: str
    task_updates: dict[str, Any]
    output: dict[str, Any] | None = None


def _multi_agent_v2_enabled(settings: Any | None) -> bool:
    return bool(settings is not None and getattr(settings, "multi_agent_v2_enabled", False))


def _multi_agent_dag_scheduler_enabled(settings: Any | None) -> bool:
    return _multi_agent_v2_enabled(settings) and bool(
        getattr(settings, "multi_agent_dag_scheduler_enabled", False)
    )


def _multi_agent_failure_handler_enabled(settings: Any | None) -> bool:
    return _multi_agent_v2_enabled(settings) and bool(
        getattr(settings, "multi_agent_failure_handler_enabled", False)
    )


def _multi_agent_resource_lock_enabled(settings: Any | None) -> bool:
    return _multi_agent_v2_enabled(settings) and bool(
        getattr(settings, "multi_agent_resource_lock_enabled", False)
    )


def _failure_strategy_for_exception(
    *,
    settings: Any | None,
    task_id: str,
    exc: Exception,
    attempt: int,
) -> FailureStrategy | None:
    if not _multi_agent_failure_handler_enabled(settings):
        return None
    return FailureHandler().decide(
        task_id=task_id,
        error_category=type(exc).__name__,
        attempt=attempt,
    )


class AgentTeamRunMixin:
    settings: Any | None
    model_factory: Any | None
    executor: DelegatedRunExecutor | None
    coordination_backend: Any | None
    background_work: Any | None
    workspace_service: AgentTeamWorkspaceService

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
        with self._scheduler_lock(session_id):
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
            if _multi_agent_dag_scheduler_enabled(self.settings):
                runnable = self._compute_dag_runnable_tasks(
                    tasks=tasks,
                    max_parallel=remaining_capacity,
                )
            if selected_task_ids:
                runnable = [task for task in runnable if task.task_id in selected_task_ids]
            runnable = runnable[: min(remaining_capacity, _MAX_MISSION_SCHEDULER_TASKS)]
            queued_tasks = [
                task.model_copy(
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
                for task in runnable
            ]
            self.repository.save_tasks_bulk(queued_tasks)
            for queued in queued_tasks:
                self._enqueue_task_run(task_id=queued.task_id, user_id=user_id)
            if runnable:
                self._touch_session(session_id, status=AgentTeamSessionStatus.RUNNING)
            else:
                self._refresh_session_status(session_id)
        session = self.get_session(session_id, user_id=user_id)
        return session, self.list_tasks(session_id=session_id, user_id=user_id)

    def _compute_dag_runnable_tasks(
        self,
        *,
        tasks: list[AgentTeamTask],
        max_parallel: int,
    ) -> list[AgentTeamTask]:
        task_by_id = {task.task_id: task for task in tasks}
        nodes = [
            DAGTaskNode(
                task_id=task.task_id,
                role=task.role.value,
                dependencies=tuple(task.dependencies),
                resource_claims=tuple(task.resource_claims),
                priority=int(task.sort_order or _MAX_MISSION_SCHEDULER_TASKS),
                timeout_seconds=0.0,
                max_retries=max(1, int(task.max_attempts or 1)),
            )
            for task in tasks
        ]
        completed = {task.task_id for task in tasks if task.status == AgentTeamTaskStatus.DONE}
        failed = {
            task.task_id
            for task in tasks
            if task.status in {AgentTeamTaskStatus.FAILED, AgentTeamTaskStatus.CANCELLED}
        }
        in_progress = {
            task.task_id
            for task in tasks
            if task.status in {AgentTeamTaskStatus.QUEUED, AgentTeamTaskStatus.RUNNING}
        }
        try:
            wave = DAGScheduler(nodes, max_parallel_runs=max_parallel).compute_next_wave(
                completed=completed,
                failed=failed,
                in_progress=in_progress,
            )
        except DAGValidationError:
            return []
        return [
            task_by_id[node.task_id]
            for node in wave
            if task_by_id[node.task_id].status == AgentTeamTaskStatus.PENDING
        ]

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
        with self._scheduler_lock(queued.session_id):
            self.repository.save_task(queued)
            self._touch_session(queued.session_id, status=AgentTeamSessionStatus.RUNNING)
        self._enqueue_task_run(task_id=task_id, user_id=user_id)
        return self.get_task(task_id, user_id=user_id)

    def run_task_claimed(self, *, task_id: str, user_id: str) -> AgentTeamTask:
        owner = f"agent-team:{uuid4().hex}"
        task = self.get_task(task_id, user_id=user_id)
        with self._scheduler_lock(task.session_id):
            claimed = self.repository.claim_task(
                task_id=task_id,
                owner=owner,
                ttl_seconds=_AGENT_TEAM_TASK_CLAIM_TTL_SECONDS,
            )
        if claimed is None:
            return self.get_task(task_id, user_id=user_id)
        resource_locks_required = bool(
            _multi_agent_resource_lock_enabled(self.settings)
            and getattr(self.coordination_backend, "resource_locks", None) is not None
        )
        resource_claims = self._acquire_task_resource_claims(claimed)
        if resource_locks_required and claimed.resource_claims and not resource_claims:
            with self._scheduler_lock(claimed.session_id):
                task = self.repository.release_task_claim(
                    task_id=task_id,
                    claim_token=claimed.claim_token or "",
                    final_status=AgentTeamTaskStatus.PENDING,
                    error="Required multi-agent resource lock is unavailable.",
                )
                task = task.model_copy(
                    update={
                        "run_status": None,
                        "execution_status": "waiting_resource_lock",
                        "queued_at": None,
                        "updated_at": _now(),
                    }
                )
                self.repository.save_task(task)
                self._refresh_session_status(task.session_id)
            return task
        try:
            result = self._execute_task_body(claimed, user_id=user_id)
        except Exception as exc:  # noqa: BLE001
            current = self.get_task(task_id, user_id=user_id)
            final_status = (
                AgentTeamTaskStatus.FAILED
                if current.attempt >= max(1, int(current.max_attempts or 1))
                else AgentTeamTaskStatus.QUEUED
            )
            failure_strategy = _failure_strategy_for_exception(
                settings=self.settings,
                task_id=task_id,
                exc=exc,
                attempt=max(1, int(current.attempt or 1)),
            )
            if failure_strategy in {FailureStrategy.RETRY, FailureStrategy.REASSIGN}:
                final_status = AgentTeamTaskStatus.QUEUED
            elif failure_strategy == FailureStrategy.DEGRADE:
                final_status = AgentTeamTaskStatus.DONE
                self.record_task_output(
                    task_id=task_id,
                    user_id=user_id,
                    summary=f"[DEGRADED] Task failed with {type(exc).__name__}: {exc}",
                    risk_notes=["Task output was generated by the multi-agent degradation path."],
                    metadata={
                        "multi_agent": {
                            "degraded": True,
                            "failure_strategy": failure_strategy.value,
                            "error_category": type(exc).__name__,
                        }
                    },
                )
            elif failure_strategy == FailureStrategy.ESCALATE:
                final_status = AgentTeamTaskStatus.BLOCKED
            with self._scheduler_lock(claimed.session_id):
                task = self.repository.release_task_claim(
                    task_id=task_id,
                    claim_token=claimed.claim_token or "",
                    final_status=final_status,
                    error=str(exc),
                )
                self._release_task_resource_claims(resource_claims)
                resource_claims = []
                if final_status == AgentTeamTaskStatus.QUEUED:
                    self._enqueue_task_run(task_id=task_id, user_id=user_id)
                self._refresh_session_status(task.session_id)
            return task

        latest = self.get_task(task_id, user_id=user_id)
        final_status = result.final_status
        if latest.cancel_requested_at:
            final_status = AgentTeamTaskStatus.CANCELLED
        elif final_status == AgentTeamTaskStatus.FAILED:
            failure_strategy = (
                FailureHandler().decide(
                    task_id=task_id,
                    error_category="execution_error",
                    attempt=max(1, int(latest.attempt or 1)),
                )
                if _multi_agent_failure_handler_enabled(self.settings)
                else None
            )
            if failure_strategy in {FailureStrategy.RETRY, FailureStrategy.REASSIGN}:
                final_status = AgentTeamTaskStatus.QUEUED
            elif failure_strategy == FailureStrategy.DEGRADE:
                final_status = AgentTeamTaskStatus.DONE
                result = _TaskExecutionResult(
                    session_id=result.session_id,
                    final_status=AgentTeamTaskStatus.DONE,
                    run_status="degraded",
                    execution_status="degraded",
                    last_error="",
                    task_updates={
                        **result.task_updates,
                        "finished_at": result.task_updates.get("finished_at") or _now(),
                    },
                    output={
                        "kind": _artifact_kind_for_task(latest),
                        "artifact_id": None,
                        "summary": f"[DEGRADED] Task failed after retries: {result.last_error}",
                        "changed_files": [],
                        "test_evidence": [],
                        "risk_notes": [
                            "Task output was generated by the multi-agent degradation path."
                        ],
                        "metadata": {
                            "multi_agent": {
                                "degraded": True,
                                "failure_strategy": failure_strategy.value,
                                "error_category": "run_failed",
                            }
                        },
                    },
                )
            elif failure_strategy == FailureStrategy.ESCALATE:
                final_status = AgentTeamTaskStatus.BLOCKED
        with self._scheduler_lock(claimed.session_id):
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
                self._release_task_resource_claims(resource_claims)
                return self.get_task(task_id, user_id=user_id)
            if result.output is not None and final_status not in {
                AgentTeamTaskStatus.CANCELLED,
                AgentTeamTaskStatus.QUEUED,
            }:
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
        self._release_task_resource_claims(resource_claims)
        if final_status == AgentTeamTaskStatus.DONE:
            self.maybe_schedule_next_wave(session_id=released.session_id, user_id=user_id)
        elif final_status == AgentTeamTaskStatus.QUEUED:
            self._enqueue_task_run(task_id=task_id, user_id=user_id)
        return released

    def maybe_schedule_next_wave(self, *, session_id: str, user_id: str) -> None:
        session = self.get_session(session_id, user_id=user_id)
        if session.status == AgentTeamSessionStatus.CANCELLED:
            return
        tasks = self.list_tasks(session_id=session_id, user_id=user_id)
        if any(
            task.status in {AgentTeamTaskStatus.QUEUED, AgentTeamTaskStatus.RUNNING}
            for task in tasks
        ):
            return
        if any(_is_runnable_task(task) for task in tasks):
            self.run_ready_tasks_once(session_id=session_id, user_id=user_id)

    def cancel_session(
        self, *, session_id: str, user_id: str
    ) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
        session = self.get_session(session_id, user_id=user_id)
        now = _now()
        with self._scheduler_lock(session_id):
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
        status = (
            AgentTeamTaskStatus.QUEUED if dependencies_satisfied else AgentTeamTaskStatus.PENDING
        )
        with self._scheduler_lock(task.session_id):
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
        with self._scheduler_lock(task.session_id):
            updated = task.model_copy(
                update={
                    "status": status,
                    "cancel_requested_at": task.cancel_requested_at or now,
                    "run_status": "cancelled"
                    if status == AgentTeamTaskStatus.CANCELLED
                    else task.run_status,
                    "execution_status": "cancel_requested",
                    "finished_at": now
                    if status == AgentTeamTaskStatus.CANCELLED
                    else task.finished_at,
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
            scheduler_wave = _task_wave(
                task, self.list_tasks(session_id=task.session_id, user_id=user_id)
            )
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
        self._publish_agent_team_progress(
            task=task,
            event="started",
            payload={"scheduler_wave": scheduler_wave},
        )
        executor = self._delegated_executor()
        workspace: AgentTeamWorkspace | None = None
        workspace_status: AgentTeamWorkspaceStatus | None = None
        if _should_use_task_workspace(task, executor):
            try:
                workspace = self.workspace_service.ensure_workspace(
                    session=self.get_session(task.session_id, user_id=user_id),
                    task=task,
                )
                task = self.update_task(
                    task_id=task.task_id,
                    user_id=user_id,
                    workspace_id=workspace.workspace_id,
                    workspace_branch=workspace.workspace_branch,
                    workspace_path=workspace.workspace_path,
                    base_commit=workspace.base_commit,
                    workspace_status="created",
                )
            except Exception as exc:  # noqa: BLE001
                finished_at = _now()
                return _TaskExecutionResult(
                    session_id=task.session_id,
                    final_status=AgentTeamTaskStatus.FAILED,
                    run_status="failed",
                    execution_status="workspace_failed",
                    last_error=f"Failed to prepare task workspace: {exc}",
                    task_updates={"finished_at": finished_at},
                )
        delegated = self._to_delegated_task(task, user_id=user_id)
        result = run_delegated_tasks(
            tasks=[delegated],
            registry=SubagentRegistry.from_settings(
                self.settings or Settings(),
                context_refs=task.context_refs,
            ),
            executor=executor,
            max_parallel_runs=1,
        )
        if not result:
            finished_at = _now()
            return _TaskExecutionResult(
                session_id=task.session_id,
                final_status=AgentTeamTaskStatus.BLOCKED,
                run_status="skipped",
                execution_status="skipped",
                last_error="Automatic task execution is not enabled in this environment.",
                task_updates={"finished_at": finished_at},
            )

        run = result[0]
        if workspace is not None:
            try:
                workspace_status = self.workspace_service.collect_status(workspace.workspace_path)
                run = run.model_copy(
                    update={
                        "workspace_id": workspace.workspace_id,
                        "workspace_path": workspace.workspace_path,
                        "workspace_branch": workspace.workspace_branch,
                        "base_commit": workspace.base_commit,
                        "changed_files": _dedupe(
                            [*run.changed_files, *workspace_status.changed_files]
                        ),
                        "diff_summary": workspace_status.diff_summary,
                        "workspace_status": workspace_status.workspace_status,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                run = run.model_copy(
                    update={
                        "workspace_id": workspace.workspace_id,
                        "workspace_path": workspace.workspace_path,
                        "workspace_branch": workspace.workspace_branch,
                        "base_commit": workspace.base_commit,
                        "workspace_status": "status_failed",
                    }
                )
                workspace_status = AgentTeamWorkspaceStatus(
                    changed_files=[],
                    diff_summary="",
                    workspace_status="status_failed",
                    porcelain=[str(exc)],
                )
        artifact_ids = [artifact.artifact_id for artifact in run.artifacts]
        status = _team_status_for_run_status(run.status)
        changed_files = _changed_files_for_run(run)
        test_evidence = _test_evidence_for_run(run)
        risk_notes = _risk_notes_for_run(run)
        workspace_metadata = _workspace_metadata_for_run(run, workspace_status)
        output = {
            "kind": _artifact_kind_for_task(task),
            "artifact_id": artifact_ids[0] if artifact_ids else None,
            "summary": run.summary,
            "changed_files": changed_files,
            "test_evidence": test_evidence,
            **workspace_metadata,
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
                    **workspace_metadata,
                },
                "scheduler": {
                    "wave": scheduler_wave,
                    "max_waves": _MAX_MISSION_SCHEDULER_WAVES,
                    "max_tasks": _MAX_MISSION_SCHEDULER_TASKS,
                },
                "artifacts": [artifact.model_dump(mode="json") for artifact in run.artifacts],
                "run": run.model_dump(mode="json"),
                **({"workspace": workspace_status.as_metadata()} if workspace_status else {}),
            },
        }
        self._publish_agent_team_progress(
            task=task,
            event="finished",
            payload={"status": status.value, "run_status": run.status},
        )
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
                "test_evidence": test_evidence,
                **workspace_metadata,
                "verification_summary": run.summary,
                "risk_notes": risk_notes,
                "started_at": run.started_at or started_at,
                "finished_at": run.finished_at or _now(),
            },
            output=output,
        )

    def _publish_agent_team_progress(
        self,
        *,
        task: AgentTeamTask,
        event: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not (
            _multi_agent_v2_enabled(self.settings)
            and bool(getattr(self.settings, "multi_agent_message_bus_enabled", False))
        ):
            return
        message_bus = getattr(self.coordination_backend, "message_bus", None)
        if message_bus is None:
            return
        message_bus.publish(
            session_id=task.session_id,
            source_agent=f"{task.role.value}:{task.task_id}",
            target_agent=None,
            message_type=AgentMessageType.PROGRESS,
            payload={
                "task_id": task.task_id,
                "role": task.role.value,
                "event": event,
                **dict(payload or {}),
            },
        )

    def _acquire_task_resource_claims(self, task: AgentTeamTask) -> list[ResourceClaim]:
        if not task.resource_claims:
            return []
        if not _multi_agent_resource_lock_enabled(self.settings):
            return []
        lock_backend = getattr(self.coordination_backend, "resource_locks", None)
        if lock_backend is None:
            return []
        acquired: list[ResourceClaim] = []
        ttl = float(getattr(self.settings, "multi_agent_resource_lock_ttl_seconds", 60.0) or 60.0)
        agent_id = f"{task.role.value}:{task.task_id}"
        for resource_id in task.resource_claims:
            claim = lock_backend.try_acquire(
                resource_id=resource_id,
                agent_id=agent_id,
                session_id=task.session_id,
                mode=LockMode.EXCLUSIVE,
                ttl_seconds=ttl,
            )
            if claim is None:
                self._release_task_resource_claims(acquired)
                return []
            acquired.append(claim)
        return acquired

    def _release_task_resource_claims(self, claims: list[ResourceClaim]) -> None:
        if not claims:
            return
        lock_backend = getattr(self.coordination_backend, "resource_locks", None)
        if lock_backend is None:
            return
        for claim in claims:
            try:
                lock_backend.release(claim)
            except Exception:
                continue

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
        if has_repo_method(self.background_work, "submit"):
            return bool(
                self.background_work.submit(
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
        if not has_repo_method(backend, "enqueue_job"):
            return False
        try:
            return bool(
                backend.enqueue_job(
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
            "pending_tool_approvals": _pending_tool_approvals_for_session(
                self.coordination_backend,
                session=session,
            ),
        }

    def _build_delegation_plan(self, session: AgentTeamSession) -> AgentDelegationPlan | None:
        if self.settings is None:
            return None
        return build_agent_delegation_plan(settings=self.settings, task_text=session.goal)

    def _to_delegated_task(self, task: AgentTeamTask, *, user_id: str) -> AgentTask:
        session = self.get_session(task.session_id, user_id=user_id)
        upstream_outputs = [
            output.model_dump(mode="json")
            for dependency_id in task.dependencies
            for output in self.repository.list_task_outputs(task_id=dependency_id)
        ]
        context_refs = [
            *task.context_refs,
            {
                "type": "agent_team_session",
                "session_id": session.session_id,
                "root_thread_id": session.root_thread_id,
                "mission_goal": session.goal,
                "planning_source": session.planning_source,
                "planning_rationale": session.planning_rationale,
            },
            {
                "type": "agent_team_task_contract",
                "task_id": task.task_id,
                "title": task.title,
                "task_type": task.task_type,
                "task_kind": task.task_kind,
                "input_contract": task.input_contract,
                "output_contract": task.output_contract,
                "evidence_required": task.evidence_required,
                "capability_requirements": task.capability_requirements,
                "risk_level": task.risk_level,
                "write_scope": task.write_scope,
                "resource_claims": task.resource_claims,
                "replan_policy": task.replan_policy,
            },
            {
                "type": "agent_team_dependency_outputs",
                "dependency_task_ids": list(task.dependencies),
                "outputs": upstream_outputs,
            },
        ]
        constraints = [f"Scope: {item}" for item in task.scope]
        if task.input_contract:
            constraints.append(f"Input contract: {task.input_contract}")
        if task.output_contract:
            constraints.append(f"Output contract: {task.output_contract}")
        if task.evidence_required:
            constraints.append(f"Required evidence: {', '.join(task.evidence_required)}")
        if task.write_scope:
            constraints.append(f"Write scope: {', '.join(task.write_scope)}")
        if task.resource_claims:
            constraints.append(f"Resource claims: {', '.join(task.resource_claims)}")
        return AgentTask(
            task_id=task.task_id,
            role=agent_role_for_team_task_role(task.role),
            goal=task.goal,
            constraints=constraints,
            allowed_tools=_allowed_tools_for_task(task),
            acceptance_criteria=list(task.acceptance_criteria),
            requires_workspace_write=_is_writable_team_task(task),
            context_refs=context_refs,
            run_isolation_key=f"agent-team:{task.session_id}:{task.task_id}",
            workspace_id=task.workspace_id,
            workspace_path=task.workspace_path,
            workspace_branch=task.workspace_branch,
            base_commit=task.base_commit,
        )

    def cleanup_task_workspace(
        self,
        *,
        session_id: str,
        user_id: str,
        task_id: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        self.get_session(session_id, user_id=user_id)
        if task_id is not None:
            task = self.get_task(task_id, user_id=user_id)
            if task.session_id != session_id:
                raise PermissionError("Agent team task belongs to another session.")
        return self.workspace_service.cleanup_workspace(
            session_id=session_id,
            task_id=task_id,
            force=force,
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


def _pending_tool_approvals_for_session(
    coordination_backend: Any | None,
    *,
    session: AgentTeamSession,
) -> list[dict[str, Any]]:
    approval_queue = getattr(coordination_backend, "approval_queue", None)
    if not has_repo_method(approval_queue, "list_pending"):
        return []
    session_ids = {session.session_id, session.root_thread_id}
    approvals = []
    for request in approval_queue.list_pending():
        if str(request.session_id) not in session_ids:
            continue
        approvals.append(_tool_approval_payload(request))
    return approvals


def _tool_approval_payload(request: Any) -> dict[str, Any]:
    status = getattr(request, "status", "pending")
    status_value = getattr(status, "value", status)
    return {
        "request_id": str(getattr(request, "request_id", "")),
        "session_id": str(getattr(request, "session_id", "")),
        "agent_id": str(getattr(request, "agent_id", "")),
        "tool_name": str(getattr(request, "tool_name", "")),
        "tool_args": dict(getattr(request, "tool_args", {}) or {}),
        "risk_level": str(getattr(request, "risk_level", "low") or "low"),
        "status": str(status_value or "pending"),
        "submitted_at": float(getattr(request, "submitted_at", 0.0) or 0.0),
        "timeout_at": float(getattr(request, "timeout_at", 0.0) or 0.0),
        "decided_by": getattr(request, "decided_by", None),
    }


__all__ = ["AgentTeamRunMixin"]
