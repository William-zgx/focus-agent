from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from focus_agent.config import Settings
from focus_agent.core.agent_team import (
    AgentTeamSession,
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
    FailureStrategy,
    LockMode,
    ResourceClaim,
)
from focus_agent.multi_agent.failure_handler import FailureHandler
from focus_agent.services.coordination import BackgroundJobSpec

from .agent_team_helpers import _dedupe, _now
from .agent_team_real_execution import (
    execute_real_agent_team_task,
    is_real_agent_team_execution_enabled,
    is_real_agent_team_execution_requested,
)
from .agent_team_run_helpers import (
    _MAX_MISSION_SCHEDULER_TASKS,
    _MAX_MISSION_SCHEDULER_WAVES,
    _agent_team_execution_mode,
    _allowed_tools_for_task,
    _artifact_kind_for_task,
    _changed_files_for_run,
    _is_writable_team_task,
    _risk_notes_for_run,
    _run_metadata,
    _scheduler_state,
    _should_use_task_workspace,
    _task_wave,
    _team_status_for_run_status,
    _test_evidence_for_run,
    _workspace_metadata_for_run,
)
from .agent_team_workspace import AgentTeamWorkspace, AgentTeamWorkspaceStatus


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


def _agent_team_cross_session_fencing_enabled(settings: Any | None) -> bool:
    return bool(
        settings is not None
        and getattr(settings, "agent_team_fencing_enabled", False)
        and getattr(settings, "agent_team_cross_session_locks_enabled", False)
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


def execute_task_body(
    service: Any, task: AgentTeamTask, *, user_id: str, scheduler_wave: int | None = None
) -> _TaskExecutionResult:
    task = service.get_task(task.task_id, user_id=user_id)
    if scheduler_wave is None:
        scheduler_wave = _task_wave(
            task, service.list_tasks(session_id=task.session_id, user_id=user_id)
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
    task = service.update_task(
        task_id=task.task_id,
        user_id=user_id,
        status=AgentTeamTaskStatus.RUNNING,
        run_status="running",
        started_at=started_at,
        last_error="",
    )
    service._publish_agent_team_progress(
        task=task,
        event="started",
        payload={"scheduler_wave": scheduler_wave},
    )
    real_execution_requested = is_real_agent_team_execution_requested(service.settings)
    real_execution = is_real_agent_team_execution_enabled(service.settings, service=service)
    if real_execution_requested and not real_execution:
        return _TaskExecutionResult(
            session_id=task.session_id,
            final_status=AgentTeamTaskStatus.BLOCKED,
            run_status="blocked",
            execution_status="readiness_blocked",
            last_error=(
                "Real Agent Team execution is blocked because runtime readiness is not ready."
            ),
            task_updates={"finished_at": _now()},
        )
    executor = service._delegated_executor()
    workspace: AgentTeamWorkspace | None = None
    workspace_status: AgentTeamWorkspaceStatus | None = None
    if real_execution or _should_use_task_workspace(task, executor):
        try:
            workspace = service.workspace_service.ensure_workspace(
                session=service.get_session(task.session_id, user_id=user_id),
                task=task,
            )
            task = service.update_task(
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
    if real_execution:
        if workspace is None:
            return _TaskExecutionResult(
                session_id=task.session_id,
                final_status=AgentTeamTaskStatus.FAILED,
                run_status="failed",
                execution_status="workspace_required",
                last_error="Real Agent Team execution requires an isolated task worktree.",
                task_updates={"finished_at": _now()},
            )
        real_result = execute_real_agent_team_task(
            service,
            task=task,
            user_id=user_id,
            workspace_metadata=workspace.as_metadata(),
            scheduler_wave=scheduler_wave,
        )
        try:
            workspace_status = service.workspace_service.collect_status(workspace.workspace_path)
        except Exception as exc:  # noqa: BLE001
            workspace_status = AgentTeamWorkspaceStatus(
                changed_files=[],
                diff_summary="",
                workspace_status="status_failed",
                porcelain=[str(exc)],
            )
        workspace_metadata = _workspace_metadata_for_run(
            type(
                "_RealWorkspaceRun",
                (),
                {
                    **workspace.as_metadata(),
                    "workspace_status": workspace_status.workspace_status,
                    "diff_summary": workspace_status.diff_summary,
                },
            )(),
            workspace_status,
        )
        task_updates = {
            "agent_run_id": real_result.task_updates.get("task_run_id"),
            "delegated_task_id": task.task_id,
            "changed_files": _dedupe(
                [
                    *list(real_result.task_updates.get("changed_files") or []),
                    *workspace_status.changed_files,
                ]
            ),
            **workspace_metadata,
            **real_result.task_updates,
        }
        output = dict(real_result.output or {}) if real_result.output is not None else None
        if output is not None:
            output["changed_files"] = _dedupe(
                [
                    *list(output.get("changed_files") or []),
                    *workspace_status.changed_files,
                ]
            )
            output.update(workspace_metadata)
            metadata = dict(output.get("metadata") or {})
            metadata["workspace"] = workspace_status.as_metadata()
            output["metadata"] = metadata
        service._publish_agent_team_progress(
            task=task,
            event="finished",
            payload={
                "status": real_result.final_status.value,
                "run_status": real_result.run_status,
                "execution_profile": "worktree_sandbox",
            },
        )
        return _TaskExecutionResult(
            session_id=task.session_id,
            final_status=real_result.final_status,
            run_status=real_result.run_status,
            execution_status=real_result.execution_status,
            last_error=real_result.error,
            task_updates=task_updates,
            output=output,
        )
    delegated = service._to_delegated_task(task, user_id=user_id)
    result = run_delegated_tasks(
        tasks=[delegated],
        registry=SubagentRegistry.from_settings(
            service.settings or Settings(),
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
            workspace_status = service.workspace_service.collect_status(workspace.workspace_path)
            run = run.model_copy(
                update={
                    "workspace_id": workspace.workspace_id,
                    "workspace_path": workspace.workspace_path,
                    "workspace_branch": workspace.workspace_branch,
                    "base_commit": workspace.base_commit,
                    "changed_files": _dedupe([*run.changed_files, *workspace_status.changed_files]),
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
    service._publish_agent_team_progress(
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


def publish_agent_team_progress(
    service: Any,
    *,
    task: AgentTeamTask,
    event: str,
    payload: dict[str, Any] | None = None,
) -> None:
    if not (
        _multi_agent_v2_enabled(service.settings)
        and bool(getattr(service.settings, "multi_agent_message_bus_enabled", False))
    ):
        return
    message_bus = getattr(service.coordination_backend, "message_bus", None)
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


def acquire_task_resource_claims(service: Any, task: AgentTeamTask) -> list[ResourceClaim]:
    if not task.resource_claims:
        return []
    if not _multi_agent_resource_lock_enabled(service.settings):
        return []
    lock_backend = getattr(service.coordination_backend, "resource_locks", None)
    if lock_backend is None:
        return []
    acquired: list[ResourceClaim] = []
    ttl = float(getattr(service.settings, "multi_agent_resource_lock_ttl_seconds", 60.0) or 60.0)
    agent_id = f"{task.role.value}:{task.task_id}"
    cross_session_scope = (
        _task_cross_session_lock_scope(service, task)
        if _agent_team_cross_session_fencing_enabled(service.settings)
        else None
    )
    for resource_id in task.resource_claims:
        acquire_kwargs: dict[str, Any] = {
            "resource_id": resource_id,
            "agent_id": agent_id,
            "session_id": task.session_id,
            "mode": LockMode.EXCLUSIVE,
            "ttl_seconds": ttl,
        }
        if cross_session_scope is not None:
            acquire_kwargs.update(cross_session_scope)
        claim = lock_backend.try_acquire(
            **acquire_kwargs,
        )
        if claim is None:
            service._release_task_resource_claims(acquired)
            return []
        acquired.append(claim)
    return acquired


def _task_cross_session_lock_scope(service: Any, task: AgentTeamTask) -> dict[str, str]:
    tenant_id = _first_scope_value(
        (
            task,
            getattr(service, "resource_lock_context", None),
            getattr(service, "tenant_context", None),
            getattr(service, "tenant_id", None),
            getattr(getattr(service, "settings", None), "tenant_id", None),
            *list(getattr(task, "context_refs", ()) or ()),
        ),
        keys=("tenant_id", "tenant"),
    )
    if tenant_id is None:
        tenant_id = "tenant:default"

    resource_namespace = _first_scope_value(
        (
            task,
            getattr(service, "resource_lock_context", None),
            getattr(service, "resource_namespace", None),
            *list(getattr(task, "context_refs", ()) or ()),
        ),
        keys=("resource_namespace", "repository_id", "repo_id", "repository", "repo"),
    )
    if resource_namespace is None:
        repo_root = getattr(getattr(service, "workspace_service", None), "repo_root", None)
        resource_namespace = _repo_namespace_from_root(repo_root)
    return {
        "tenant_id": tenant_id,
        "resource_namespace": resource_namespace or f"session:{task.session_id}",
    }


def _first_scope_value(sources: tuple[Any, ...], *, keys: tuple[str, ...]) -> str | None:
    for source in sources:
        if isinstance(source, dict):
            values = (source.get(key) for key in keys)
        elif isinstance(source, str):
            values = (source,)
        else:
            values = (getattr(source, key, None) for key in keys)
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
    return None


def _repo_namespace_from_root(repo_root: Any) -> str | None:
    if repo_root is None:
        return None
    try:
        return f"repo:{Path(repo_root).expanduser().resolve()}"
    except (OSError, TypeError, ValueError):
        text = str(repo_root).strip()
        return f"repo:{text}" if text else None


def release_task_resource_claims(service: Any, claims: list[ResourceClaim]) -> None:
    if not claims:
        return
    lock_backend = getattr(service.coordination_backend, "resource_locks", None)
    if lock_backend is None:
        return
    for claim in claims:
        try:
            lock_backend.release(claim)
        except Exception:
            continue


def enqueue_task_run(service: Any, *, task_id: str, user_id: str) -> bool:
    key = f"agent-team:task:{task_id}"
    payload = {"task_id": task_id, "user_id": user_id}
    if service._enqueue_durable_job(
        kind="agent_team_run_task",
        key=key,
        payload=payload,
        max_attempts=2,
        dedupe_policy="replace",
    ):
        return True
    if has_repo_method(service.background_work, "submit"):
        return bool(
            service.background_work.submit(
                key=key,
                func=service.run_task_claimed,
                task_id=task_id,
                user_id=user_id,
            )
        )
    service.run_task_claimed(task_id=task_id, user_id=user_id)
    return True


def enqueue_durable_job(
    service: Any,
    *,
    kind: str,
    key: str,
    payload: dict[str, Any],
    max_attempts: int = 1,
    dedupe_policy: str = "skip",
) -> bool:
    if _agent_team_execution_mode(service.settings).strip().lower() != "durable":
        return False
    backend = getattr(service.coordination_backend, "job_deduper", None)
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


def get_session_view(service: Any, *, session_id: str, user_id: str) -> dict[str, Any]:
    session = service.get_session(session_id, user_id=user_id)
    tasks = service.list_tasks(session_id=session_id, user_id=user_id)
    outputs = [
        output
        for task in tasks
        for output in service.repository.list_task_outputs(task_id=task.task_id)
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
        "run": _run_metadata(tasks=tasks, settings=service.settings),
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
            service.coordination_backend,
            session=session,
        ),
    }


def build_delegation_plan(service: Any, session: AgentTeamSession) -> AgentDelegationPlan | None:
    if service.settings is None:
        return None
    return build_agent_delegation_plan(settings=service.settings, task_text=session.goal)


def to_delegated_task(service: Any, task: AgentTeamTask, *, user_id: str) -> AgentTask:
    session = service.get_session(task.session_id, user_id=user_id)
    upstream_outputs = [
        output.model_dump(mode="json")
        for dependency_id in task.dependencies
        for output in service.repository.list_task_outputs(task_id=dependency_id)
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
    service: Any,
    *,
    session_id: str,
    user_id: str,
    task_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    service.get_session(session_id, user_id=user_id)
    if task_id is not None:
        task = service.get_task(task_id, user_id=user_id)
        if task.session_id != session_id:
            raise PermissionError("Agent team task belongs to another session.")
    return service.workspace_service.cleanup_workspace(
        session_id=session_id,
        task_id=task_id,
        force=force,
    )


def delegated_executor(service: Any) -> DelegatedRunExecutor | None:
    if service.executor is not None:
        return service.executor
    if service.settings is None:
        return FakeDelegatedRunExecutor()
    mode = normalize_delegation_execution_mode(
        getattr(service.settings, "agent_delegation_execution_mode", "observe")
    )
    return executor_for_mode(mode, model_factory=service.model_factory, settings=service.settings)


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


__all__ = [
    "_TaskExecutionResult",
    "_failure_strategy_for_exception",
    "_agent_team_cross_session_fencing_enabled",
    "_multi_agent_dag_scheduler_enabled",
    "_multi_agent_failure_handler_enabled",
    "_multi_agent_resource_lock_enabled",
    "_multi_agent_v2_enabled",
    "_pending_tool_approvals_for_session",
    "_tool_approval_payload",
    "acquire_task_resource_claims",
    "build_delegation_plan",
    "cleanup_task_workspace",
    "delegated_executor",
    "enqueue_durable_job",
    "enqueue_task_run",
    "execute_task_body",
    "get_session_view",
    "publish_agent_team_progress",
    "release_task_resource_claims",
    "to_delegated_task",
]
