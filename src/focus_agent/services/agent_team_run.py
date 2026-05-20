from __future__ import annotations

from typing import Any
from uuid import uuid4

from focus_agent.core.agent_team import (
    AgentTeamSession,
    AgentTeamSessionStatus,
    AgentTeamTask,
    AgentTeamTaskStatus,
)
from focus_agent.delegation.delegation import (
    AgentDelegationPlan,
    AgentTask,
)
from focus_agent.delegation.execution import DelegatedRunExecutor
from focus_agent.multi_agent.contracts import (
    DAGTaskNode,
    FailureStrategy,
    ResourceClaim,
)
from focus_agent.multi_agent.dag_scheduler import DAGScheduler
from focus_agent.multi_agent.errors import DAGValidationError
from focus_agent.multi_agent.failure_handler import FailureHandler

from .agent_team_helpers import _now
from .agent_team_run_execution import (
    _failure_strategy_for_exception,
    _multi_agent_dag_scheduler_enabled,
    _multi_agent_failure_handler_enabled,
    _multi_agent_resource_lock_enabled,
    _TaskExecutionResult,
)
from .agent_team_run_execution import (
    _multi_agent_v2_enabled as _multi_agent_v2_enabled,
)
from .agent_team_run_execution import (
    _pending_tool_approvals_for_session as _pending_tool_approvals_for_session,
)
from .agent_team_run_execution import (
    _tool_approval_payload as _tool_approval_payload,
)
from .agent_team_run_execution import (
    acquire_task_resource_claims as _run_acquire_task_resource_claims,
)
from .agent_team_run_execution import (
    build_delegation_plan as _run_build_delegation_plan,
)
from .agent_team_run_execution import (
    cleanup_task_workspace as _run_cleanup_task_workspace,
)
from .agent_team_run_execution import (
    delegated_executor as _run_delegated_executor,
)
from .agent_team_run_execution import (
    enqueue_durable_job as _run_enqueue_durable_job,
)
from .agent_team_run_execution import (
    enqueue_task_run as _run_enqueue_task_run,
)
from .agent_team_run_execution import (
    execute_task_body as _run_execute_task_body,
)
from .agent_team_run_execution import (
    get_session_view as _run_get_session_view,
)
from .agent_team_run_execution import (
    publish_agent_team_progress as _run_publish_agent_team_progress,
)
from .agent_team_run_execution import (
    release_task_resource_claims as _run_release_task_resource_claims,
)
from .agent_team_run_execution import (
    to_delegated_task as _run_to_delegated_task,
)
from .agent_team_run_helpers import (
    _AGENT_TEAM_TASK_CLAIM_TTL_SECONDS,
    _MAX_MISSION_SCHEDULER_TASKS,
    _agent_team_execution_mode,
    _artifact_kind_for_task,
    _is_runnable_task,
    _max_parallel_runs_for,
    _task_identity,
    _team_role_for_agent_role,
)
from .agent_team_workspace import AgentTeamWorkspaceService


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
        return _run_execute_task_body(
            self, task, user_id=user_id, scheduler_wave=scheduler_wave
        )

    def _publish_agent_team_progress(
        self,
        *,
        task: AgentTeamTask,
        event: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        _run_publish_agent_team_progress(self, task=task, event=event, payload=payload)

    def _acquire_task_resource_claims(self, task: AgentTeamTask) -> list[ResourceClaim]:
        return _run_acquire_task_resource_claims(self, task)

    def _release_task_resource_claims(self, claims: list[ResourceClaim]) -> None:
        _run_release_task_resource_claims(self, claims)

    def _enqueue_task_run(self, *, task_id: str, user_id: str) -> bool:
        return _run_enqueue_task_run(self, task_id=task_id, user_id=user_id)

    def _enqueue_durable_job(
        self,
        *,
        kind: str,
        key: str,
        payload: dict[str, Any],
        max_attempts: int = 1,
        dedupe_policy: str = "skip",
    ) -> bool:
        return _run_enqueue_durable_job(
            self,
            kind=kind,
            key=key,
            payload=payload,
            max_attempts=max_attempts,
            dedupe_policy=dedupe_policy,
        )

    def get_session_view(self, *, session_id: str, user_id: str) -> dict[str, Any]:
        return _run_get_session_view(self, session_id=session_id, user_id=user_id)

    def _build_delegation_plan(self, session: AgentTeamSession) -> AgentDelegationPlan | None:
        return _run_build_delegation_plan(self, session)

    def _to_delegated_task(self, task: AgentTeamTask, *, user_id: str) -> AgentTask:
        return _run_to_delegated_task(self, task, user_id=user_id)

    def cleanup_task_workspace(
        self,
        *,
        session_id: str,
        user_id: str,
        task_id: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        return _run_cleanup_task_workspace(
            self,
            session_id=session_id,
            user_id=user_id,
            task_id=task_id,
            force=force,
        )

    def _delegated_executor(self) -> DelegatedRunExecutor | None:
        return _run_delegated_executor(self)

__all__ = ["AgentTeamRunMixin"]
