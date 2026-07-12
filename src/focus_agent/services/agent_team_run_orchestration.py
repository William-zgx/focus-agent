from __future__ import annotations

from collections.abc import Callable
from typing import Any

from focus_agent.core.agent_team import (
    AgentTeamSession,
    AgentTeamSessionStatus,
    AgentTeamTask,
    AgentTeamTaskStatus,
)
from focus_agent.multi_agent.contracts import (
    DAGTaskNode,
    FailureStrategy,
)


def plan_session(
    service: Any,
    *,
    session_id: str,
    user_id: str,
    create_branches: bool,
    parent_thread_id: str | None,
    task_identity: Callable[[AgentTeamTask], tuple[Any, str]],
    team_role_for_agent_role: Callable[[Any], Any],
) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
    session = service.get_session(session_id, user_id=user_id)
    plan = service._build_delegation_plan(session)
    if plan is None or not plan.enabled or not plan.tasks:
        return service.dispatch_default_tasks(
            session_id=session_id,
            user_id=user_id,
            create_branches=create_branches,
            parent_thread_id=parent_thread_id,
        )

    existing = service.list_tasks(session_id=session_id, user_id=user_id)
    existing_by_key = {task_identity(task): task for task in existing}
    created_by_delegated_id: dict[str, AgentTeamTask] = {}

    for delegated in plan.tasks:
        role = team_role_for_agent_role(delegated.role)
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
        task = service.create_task(
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

    session = service.get_session(session_id, user_id=user_id)
    tasks = service.list_tasks(session_id=session_id, user_id=user_id)
    return session, tasks


def run_ready_tasks_once(
    service: Any,
    *,
    session_id: str,
    user_id: str,
    task_ids: list[str] | None,
    max_parallel_runs_for: Callable[[Any | None], int],
    max_scheduler_tasks: int,
    dag_scheduler_enabled: Callable[[Any | None], bool],
    dag_validation_error_type: type[Exception],
    now: Callable[[], str],
    execution_mode: Callable[[Any | None], str],
) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
    session = service.get_session(session_id, user_id=user_id)
    if session.status == AgentTeamSessionStatus.CANCELLED:
        return session, service.list_tasks(session_id=session_id, user_id=user_id)
    max_parallel = max_parallel_runs_for(service.settings)
    selected_task_ids = {task_id for task_id in task_ids or [] if task_id}
    with service._scheduler_lock(session_id):
        tasks = service.repository.list_tasks(session_id=session_id)
        active_count = sum(
            1
            for task in tasks
            if task.status in {AgentTeamTaskStatus.QUEUED, AgentTeamTaskStatus.RUNNING}
        )
        remaining_capacity = max(0, max_parallel - active_count)
        if remaining_capacity <= 0:
            service._refresh_session_status(session_id)
            session = service.repository.get_session(session_id)
            return session, service.repository.list_tasks(session_id=session_id)
        runnable = service.repository.list_runnable_tasks(
            session_id=session_id,
            limit=max_scheduler_tasks,
        )
        if dag_scheduler_enabled(service.settings):
            try:
                runnable = service._compute_dag_runnable_tasks(
                    tasks=tasks,
                    max_parallel=remaining_capacity,
                )
            except dag_validation_error_type as exc:
                service._block_dag_scheduler_error(
                    tasks=tasks,
                    error=str(exc),
                    selected_task_ids=selected_task_ids,
                )
                service._refresh_session_status(session_id)
                session = service.repository.get_session(session_id)
                return session, service.repository.list_tasks(session_id=session_id)
        if selected_task_ids:
            runnable = [task for task in runnable if task.task_id in selected_task_ids]
        runnable = runnable[: min(remaining_capacity, max_scheduler_tasks)]
        queued_tasks = [
            task.model_copy(
                update={
                    "status": AgentTeamTaskStatus.QUEUED,
                    "run_status": "queued",
                    "execution_status": "queued",
                    "queued_at": task.queued_at or now(),
                    "execution_mode": execution_mode(service.settings),
                    "last_error": "",
                    "updated_at": now(),
                }
            )
            for task in runnable
        ]
        service.repository.save_tasks_bulk(queued_tasks)
        for queued in queued_tasks:
            try:
                enqueued = service._enqueue_task_run(task_id=queued.task_id, user_id=user_id)
            except Exception as exc:  # noqa: BLE001
                enqueued = False
                error = f"Failed to enqueue agent team task: {exc}"
            else:
                error = "Failed to enqueue agent team task."
            if enqueued:
                continue
            service._mark_task_enqueue_failed(queued.task_id, error=error)
        service._refresh_session_status(session_id)
    session = service.get_session(session_id, user_id=user_id)
    return session, service.list_tasks(session_id=session_id, user_id=user_id)


def compute_dag_runnable_tasks(
    *,
    tasks: list[AgentTeamTask],
    max_parallel: int,
    max_scheduler_tasks: int,
    scheduler_factory: Callable[..., Any],
) -> list[AgentTeamTask]:
    task_by_id = {task.task_id: task for task in tasks}
    nodes = [
        DAGTaskNode(
            task_id=task.task_id,
            role=task.role.value,
            dependencies=tuple(task.dependencies),
            resource_claims=tuple(task.resource_claims),
            priority=int(task.sort_order or max_scheduler_tasks),
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
    wave = scheduler_factory(nodes, max_parallel_runs=max_parallel).compute_next_wave(
        completed=completed,
        failed=failed,
        in_progress=in_progress,
    )
    return [
        task_by_id[node.task_id]
        for node in wave
        if task_by_id[node.task_id].status == AgentTeamTaskStatus.PENDING
    ]


def block_dag_scheduler_error(
    service: Any,
    *,
    tasks: list[AgentTeamTask],
    error: str,
    selected_task_ids: set[str],
    now: Callable[[], str],
) -> None:
    timestamp = now()
    selected = {task_id for task_id in selected_task_ids if task_id}
    blocked: list[AgentTeamTask] = []
    for task in tasks:
        if selected and task.task_id not in selected:
            continue
        if task.status != AgentTeamTaskStatus.PENDING:
            continue
        blocked.append(
            task.model_copy(
                update={
                    "status": AgentTeamTaskStatus.BLOCKED,
                    "run_status": "blocked",
                    "execution_status": "scheduler_blocked",
                    "last_error": f"DAG scheduler validation failed: {error}",
                    "finished_at": task.finished_at or timestamp,
                    "claim_token": None,
                    "claim_owner": None,
                    "claimed_until": None,
                    "queued_at": None,
                    "updated_at": timestamp,
                }
            )
        )
    if blocked:
        service.repository.save_tasks_bulk(blocked)


def run_task(
    service: Any,
    *,
    task_id: str,
    user_id: str,
    now: Callable[[], str],
    execution_mode: Callable[[Any | None], str],
) -> AgentTeamTask:
    task = service.get_task(task_id, user_id=user_id)
    tasks = service.list_tasks(session_id=task.session_id, user_id=user_id)
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
        return service.update_task(
            task_id=task_id,
            user_id=user_id,
            status=AgentTeamTaskStatus.CANCELLED,
            run_status="cancelled",
            execution_status="cancelled",
            finished_at=now(),
            last_error="Task was cancelled before execution.",
        )

    queued = service.update_task(
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
            "queued_at": queued.queued_at or now(),
            "execution_mode": execution_mode(service.settings),
            "updated_at": now(),
        }
    )
    with service._scheduler_lock(queued.session_id):
        service.repository.save_task(queued)
        service._touch_session(queued.session_id, status=AgentTeamSessionStatus.RUNNING)
    try:
        enqueued = service._enqueue_task_run(task_id=task_id, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        enqueued = False
        error = f"Failed to enqueue agent team task: {exc}"
    else:
        error = "Failed to enqueue agent team task."
    if not enqueued:
        with service._scheduler_lock(queued.session_id):
            service._mark_task_enqueue_failed(task_id, error=error)
            service._refresh_session_status(queued.session_id)
    return service.get_task(task_id, user_id=user_id)


def mark_task_enqueue_failed(
    service: Any,
    task_id: str,
    *,
    error: str,
    now: Callable[[], str],
) -> AgentTeamTask:
    current = service.repository.get_task(task_id)
    failed = current.model_copy(
        update={
            "status": AgentTeamTaskStatus.PENDING,
            "run_status": None,
            "execution_status": "enqueue_failed",
            "last_error": error,
            "claim_token": None,
            "claim_owner": None,
            "claimed_until": None,
            "queued_at": None,
            "updated_at": now(),
        }
    )
    service.repository.save_task(failed)
    return failed


def run_task_claimed(
    service: Any,
    *,
    task_id: str,
    user_id: str,
    owner_factory: Callable[[], str],
    task_claim_ttl_seconds: float,
    resource_lock_enabled: Callable[[Any | None], bool],
    lease_heartbeat_factory: Callable[..., Any],
    failure_strategy_for_exception: Callable[..., FailureStrategy | None],
    failure_handler_enabled: Callable[[Any | None], bool],
    failure_handler_factory: Callable[[], Any],
    task_execution_result_factory: Callable[..., Any],
    artifact_kind_for_task: Callable[[AgentTeamTask], Any],
    now: Callable[[], str],
) -> AgentTeamTask:
    owner = owner_factory()
    task = service.get_task(task_id, user_id=user_id)
    with service._scheduler_lock(task.session_id):
        claimed = service.repository.claim_task(
            task_id=task_id,
            owner=owner,
            ttl_seconds=task_claim_ttl_seconds,
        )
    if claimed is None:
        return service.get_task(task_id, user_id=user_id)
    resource_locks_required = bool(
        resource_lock_enabled(service.settings)
        and getattr(service.coordination_backend, "resource_locks", None) is not None
    )
    resource_claims = service._acquire_task_resource_claims(claimed)
    if resource_locks_required and claimed.resource_claims and not resource_claims:
        with service._scheduler_lock(claimed.session_id):
            task = service.repository.release_task_claim(
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
                    "updated_at": now(),
                }
            )
            service.repository.save_task(task)
            service._refresh_session_status(task.session_id)
        return task
    heartbeat = lease_heartbeat_factory(service, task=claimed, resource_claims=resource_claims)
    heartbeat.start()
    try:
        result = service._execute_task_body(claimed, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        heartbeat.stop()
        current = service.get_task(task_id, user_id=user_id)
        final_status = (
            AgentTeamTaskStatus.FAILED
            if current.attempt >= max(1, int(current.max_attempts or 1))
            else AgentTeamTaskStatus.QUEUED
        )
        failure_strategy = failure_strategy_for_exception(
            settings=service.settings,
            task_id=task_id,
            exc=exc,
            attempt=max(1, int(current.attempt or 1)),
        )
        if failure_strategy in {FailureStrategy.RETRY, FailureStrategy.REASSIGN}:
            final_status = AgentTeamTaskStatus.QUEUED
        elif failure_strategy == FailureStrategy.DEGRADE:
            final_status = AgentTeamTaskStatus.DONE
            service.record_task_output(
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
        with service._scheduler_lock(claimed.session_id):
            task = service.repository.release_task_claim(
                task_id=task_id,
                claim_token=claimed.claim_token or "",
                final_status=final_status,
                error=str(exc),
            )
            service._release_task_resource_claims(resource_claims)
            resource_claims = []
            if final_status == AgentTeamTaskStatus.QUEUED:
                service._enqueue_task_run(task_id=task_id, user_id=user_id)
            service._refresh_session_status(task.session_id)
        return task
    heartbeat.stop()

    latest = service.get_task(task_id, user_id=user_id)
    final_status = result.final_status
    if latest.cancel_requested_at:
        final_status = AgentTeamTaskStatus.CANCELLED
    elif final_status == AgentTeamTaskStatus.FAILED:
        failure_strategy = (
            failure_handler_factory().decide(
                task_id=task_id,
                error_category="execution_error",
                attempt=max(1, int(latest.attempt or 1)),
            )
            if failure_handler_enabled(service.settings)
            else None
        )
        if failure_strategy in {FailureStrategy.RETRY, FailureStrategy.REASSIGN}:
            final_status = AgentTeamTaskStatus.QUEUED
        elif failure_strategy == FailureStrategy.DEGRADE:
            final_status = AgentTeamTaskStatus.DONE
            result = task_execution_result_factory(
                session_id=result.session_id,
                final_status=AgentTeamTaskStatus.DONE,
                run_status="degraded",
                execution_status="degraded",
                last_error="",
                task_updates={
                    **result.task_updates,
                    "finished_at": result.task_updates.get("finished_at") or now(),
                },
                output={
                    "kind": artifact_kind_for_task(latest),
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
    with service._scheduler_lock(claimed.session_id):
        claim_alive = service.repository.heartbeat_task_claim(
            task_id=task_id,
            claim_token=claimed.claim_token or "",
            ttl_seconds=task_claim_ttl_seconds,
        )
        if not claim_alive:
            current = service.get_task(task_id, user_id=user_id)
            stale_status = (
                AgentTeamTaskStatus.FAILED
                if current.attempt >= max(1, int(current.max_attempts or 1))
                else AgentTeamTaskStatus.QUEUED
            )
            released = service.repository.release_task_claim(
                task_id=task_id,
                claim_token=claimed.claim_token or "",
                final_status=stale_status,
                error="Task claim was lost before completion could be committed.",
            )
            if released.claim_token is None and stale_status == AgentTeamTaskStatus.QUEUED:
                service._enqueue_task_run(task_id=task_id, user_id=user_id)
            service._refresh_session_status(released.session_id)
            service._release_task_resource_claims(resource_claims)
            return service.get_task(task_id, user_id=user_id)
        if result.output is not None and final_status not in {
            AgentTeamTaskStatus.CANCELLED,
            AgentTeamTaskStatus.QUEUED,
        }:
            service.record_task_output(task_id=task_id, user_id=user_id, **result.output)
        if final_status == AgentTeamTaskStatus.CANCELLED:
            latest = service.update_task(
                task_id=task_id,
                user_id=user_id,
                status=AgentTeamTaskStatus.CANCELLED,
                run_status="cancelled",
                execution_status="cancelled",
                finished_at=now(),
                last_error=latest.last_error or "Task was cancelled before completion.",
            )
        else:
            latest = service.update_task(
                task_id=task_id,
                user_id=user_id,
                status=final_status,
                run_status=result.run_status,
                execution_status=result.execution_status,
                last_error=result.last_error,
                **result.task_updates,
            )
        released = service.repository.release_task_claim(
            task_id=task_id,
            claim_token=claimed.claim_token or "",
            final_status=final_status,
            error=latest.last_error,
        )
        service._refresh_session_status(released.session_id)
    service._release_task_resource_claims(resource_claims)
    if final_status == AgentTeamTaskStatus.DONE:
        service.maybe_schedule_next_wave(session_id=released.session_id, user_id=user_id)
    elif final_status == AgentTeamTaskStatus.QUEUED:
        service._enqueue_task_run(task_id=task_id, user_id=user_id)
    return released


def maybe_schedule_next_wave(
    service: Any,
    *,
    session_id: str,
    user_id: str,
    is_runnable_task: Callable[[AgentTeamTask], bool],
) -> None:
    session = service.get_session(session_id, user_id=user_id)
    if session.status == AgentTeamSessionStatus.CANCELLED:
        return
    tasks = service.list_tasks(session_id=session_id, user_id=user_id)
    if any(
        task.status in {AgentTeamTaskStatus.QUEUED, AgentTeamTaskStatus.RUNNING} for task in tasks
    ):
        return
    if any(is_runnable_task(task) for task in tasks):
        service.run_ready_tasks_once(session_id=session_id, user_id=user_id)


def cancel_session(
    service: Any,
    *,
    session_id: str,
    user_id: str,
    now: Callable[[], str],
) -> tuple[AgentTeamSession, list[AgentTeamTask]]:
    session = service.get_session(session_id, user_id=user_id)
    timestamp = now()
    with service._scheduler_lock(session_id):
        for task in service.repository.list_tasks(session_id=session_id):
            if task.status not in {
                AgentTeamTaskStatus.PENDING,
                AgentTeamTaskStatus.QUEUED,
                AgentTeamTaskStatus.RUNNING,
            }:
                continue
            service.repository.save_task(
                task.model_copy(
                    update={
                        "status": AgentTeamTaskStatus.CANCELLED
                        if task.status != AgentTeamTaskStatus.RUNNING
                        else task.status,
                        "cancel_requested_at": task.cancel_requested_at or timestamp,
                        "run_status": "cancelled"
                        if task.status != AgentTeamTaskStatus.RUNNING
                        else task.run_status,
                        "execution_status": "cancel_requested",
                        "updated_at": timestamp,
                    }
                )
            )
        session = session.model_copy(
            update={"status": AgentTeamSessionStatus.CANCELLED, "updated_at": timestamp}
        )
        service.repository.save_session(session)
    return session, service.list_tasks(session_id=session_id, user_id=user_id)


def retry_task(
    service: Any,
    *,
    task_id: str,
    user_id: str,
    now: Callable[[], str],
) -> AgentTeamTask:
    task = service.get_task(task_id, user_id=user_id)
    if task.status not in {
        AgentTeamTaskStatus.FAILED,
        AgentTeamTaskStatus.BLOCKED,
        AgentTeamTaskStatus.CANCELLED,
    }:
        return task
    tasks = service.list_tasks(session_id=task.session_id, user_id=user_id)
    done_ids = {item.task_id for item in tasks if item.status == AgentTeamTaskStatus.DONE}
    dependencies_satisfied = all(dependency in done_ids for dependency in task.dependencies)
    timestamp = now()
    status = AgentTeamTaskStatus.QUEUED if dependencies_satisfied else AgentTeamTaskStatus.PENDING
    with service._scheduler_lock(task.session_id):
        reset = task.model_copy(
            update={
                "status": status,
                "run_status": "queued" if dependencies_satisfied else None,
                "execution_status": "queued" if dependencies_satisfied else None,
                "claim_token": None,
                "claim_owner": None,
                "claimed_until": None,
                "queued_at": timestamp if dependencies_satisfied else None,
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
                "updated_at": timestamp,
            }
        )
        service.repository.save_task(reset)
        if dependencies_satisfied:
            service._touch_session(reset.session_id, status=AgentTeamSessionStatus.RUNNING)
        else:
            service._refresh_session_status(reset.session_id)
    if dependencies_satisfied:
        service._enqueue_task_run(task_id=task_id, user_id=user_id)
    return service.get_task(task_id, user_id=user_id)


def cancel_task(
    service: Any,
    *,
    task_id: str,
    user_id: str,
    now: Callable[[], str],
) -> AgentTeamTask:
    task = service.get_task(task_id, user_id=user_id)
    if task.status not in {
        AgentTeamTaskStatus.PENDING,
        AgentTeamTaskStatus.QUEUED,
        AgentTeamTaskStatus.RUNNING,
    }:
        return task
    timestamp = now()
    status = (
        AgentTeamTaskStatus.RUNNING
        if task.status == AgentTeamTaskStatus.RUNNING
        else AgentTeamTaskStatus.CANCELLED
    )
    with service._scheduler_lock(task.session_id):
        updated = task.model_copy(
            update={
                "status": status,
                "cancel_requested_at": task.cancel_requested_at or timestamp,
                "run_status": "cancelled"
                if status == AgentTeamTaskStatus.CANCELLED
                else task.run_status,
                "execution_status": "cancel_requested",
                "finished_at": timestamp
                if status == AgentTeamTaskStatus.CANCELLED
                else task.finished_at,
                "updated_at": timestamp,
            }
        )
        service.repository.save_task(updated)
        service._refresh_session_status(updated.session_id)
    return service.get_task(task_id, user_id=user_id)


__all__ = [
    "block_dag_scheduler_error",
    "cancel_session",
    "cancel_task",
    "compute_dag_runnable_tasks",
    "mark_task_enqueue_failed",
    "maybe_schedule_next_wave",
    "plan_session",
    "retry_task",
    "run_ready_tasks_once",
    "run_task",
    "run_task_claimed",
]
