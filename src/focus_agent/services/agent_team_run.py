from __future__ import annotations

from typing import Any
from uuid import uuid4

from focus_agent.core.agent_team import (
    AgentTeamSession,
    AgentTeamTask,
)
from focus_agent.delegation.delegation import (
    AgentDelegationPlan,
    AgentTask,
)
from focus_agent.delegation.execution import DelegatedRunExecutor
from focus_agent.multi_agent.contracts import ResourceClaim
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
from .agent_team_run_lease import _AgentTeamLeaseHeartbeat
from .agent_team_run_orchestration import (
    block_dag_scheduler_error as _run_block_dag_scheduler_error,
)
from .agent_team_run_orchestration import cancel_session as _run_cancel_session
from .agent_team_run_orchestration import cancel_task as _run_cancel_task
from .agent_team_run_orchestration import (
    compute_dag_runnable_tasks as _run_compute_dag_runnable_tasks,
)
from .agent_team_run_orchestration import (
    mark_task_enqueue_failed as _run_mark_task_enqueue_failed,
)
from .agent_team_run_orchestration import (
    maybe_schedule_next_wave as _run_maybe_schedule_next_wave,
)
from .agent_team_run_orchestration import plan_session as _run_plan_session
from .agent_team_run_orchestration import retry_task as _run_retry_task
from .agent_team_run_orchestration import (
    run_ready_tasks_once as _run_ready_tasks_once,
)
from .agent_team_run_orchestration import run_task as _run_task
from .agent_team_run_orchestration import run_task_claimed as _run_task_claimed
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
        return _run_plan_session(
            self,
            session_id=session_id,
            user_id=user_id,
            create_branches=create_branches,
            parent_thread_id=parent_thread_id,
            task_identity=_task_identity,
            team_role_for_agent_role=_team_role_for_agent_role,
        )

    def run_ready_tasks(
        self, *, session_id: str, user_id: str, task_ids: list[str] | None = None
    ) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
        return self.run_ready_tasks_once(session_id=session_id, user_id=user_id, task_ids=task_ids)

    def run_ready_tasks_once(
        self, *, session_id: str, user_id: str, task_ids: list[str] | None = None
    ) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
        return _run_ready_tasks_once(
            self,
            session_id=session_id,
            user_id=user_id,
            task_ids=task_ids,
            max_parallel_runs_for=_max_parallel_runs_for,
            max_scheduler_tasks=_MAX_MISSION_SCHEDULER_TASKS,
            dag_scheduler_enabled=_multi_agent_dag_scheduler_enabled,
            dag_validation_error_type=DAGValidationError,
            now=_now,
            execution_mode=_agent_team_execution_mode,
        )

    def _compute_dag_runnable_tasks(
        self,
        *,
        tasks: list[AgentTeamTask],
        max_parallel: int,
    ) -> list[AgentTeamTask]:
        return _run_compute_dag_runnable_tasks(
            tasks=tasks,
            max_parallel=max_parallel,
            max_scheduler_tasks=_MAX_MISSION_SCHEDULER_TASKS,
            scheduler_factory=DAGScheduler,
        )

    def _block_dag_scheduler_error(
        self,
        *,
        tasks: list[AgentTeamTask],
        error: str,
        selected_task_ids: set[str],
    ) -> None:
        _run_block_dag_scheduler_error(
            self,
            tasks=tasks,
            error=error,
            selected_task_ids=selected_task_ids,
            now=_now,
        )

    def run_task(
        self, *, task_id: str, user_id: str, scheduler_wave: int | None = None
    ) -> AgentTeamTask:
        return _run_task(
            self,
            task_id=task_id,
            user_id=user_id,
            now=_now,
            execution_mode=_agent_team_execution_mode,
        )

    def _mark_task_enqueue_failed(self, task_id: str, *, error: str) -> AgentTeamTask:
        return _run_mark_task_enqueue_failed(self, task_id, error=error, now=_now)

    def run_task_claimed(self, *, task_id: str, user_id: str) -> AgentTeamTask:
        return _run_task_claimed(
            self,
            task_id=task_id,
            user_id=user_id,
            owner_factory=lambda: f"agent-team:{uuid4().hex}",
            task_claim_ttl_seconds=_AGENT_TEAM_TASK_CLAIM_TTL_SECONDS,
            resource_lock_enabled=_multi_agent_resource_lock_enabled,
            lease_heartbeat_factory=_AgentTeamLeaseHeartbeat,
            failure_strategy_for_exception=_failure_strategy_for_exception,
            failure_handler_enabled=_multi_agent_failure_handler_enabled,
            failure_handler_factory=FailureHandler,
            task_execution_result_factory=_TaskExecutionResult,
            artifact_kind_for_task=_artifact_kind_for_task,
            now=_now,
        )

    def maybe_schedule_next_wave(self, *, session_id: str, user_id: str) -> None:
        _run_maybe_schedule_next_wave(
            self,
            session_id=session_id,
            user_id=user_id,
            is_runnable_task=_is_runnable_task,
        )

    def cancel_session(
        self, *, session_id: str, user_id: str
    ) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
        return _run_cancel_session(
            self,
            session_id=session_id,
            user_id=user_id,
            now=_now,
        )

    def retry_task(self, *, task_id: str, user_id: str) -> AgentTeamTask:
        return _run_retry_task(self, task_id=task_id, user_id=user_id, now=_now)

    def cancel_task(self, *, task_id: str, user_id: str) -> AgentTeamTask:
        return _run_cancel_task(self, task_id=task_id, user_id=user_id, now=_now)

    def _execute_task_body(
        self, task: AgentTeamTask, *, user_id: str, scheduler_wave: int | None = None
    ) -> _TaskExecutionResult:
        return _run_execute_task_body(self, task, user_id=user_id, scheduler_wave=scheduler_wave)

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
