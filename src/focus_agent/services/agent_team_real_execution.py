"""Guarded real execution orchestration for Agent Team worktree tasks.

This public scheduler entry point delegates model adaptation and durable
evidence projection to focused modules.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from focus_agent.core.agent_team import (
    AgentTeamEvidenceLevel,
    AgentTeamEvidenceVerdict,
    AgentTeamExecutionClass,
    AgentTeamTask,
    AgentTeamTaskStatus,
    TaskRun,
)

from .agent_team_execution_runtime import CancellationToken, TaskAgentRunner, TaskExecutionScope
from .agent_team_real_execution_adapters import (
    allowed_scoped_tool_names,
    sandbox_runner_for_service,
    task_model_for_service,
    task_prompt,
    task_scoped_tools,
)
from .agent_team_real_execution_records import (
    append_event,
    failed_outcome,
    finalize_failed_run,
    now,
    outcome_from_result,
    persist_checkpoint,
    persist_runner_evidence,
)
from .agent_team_real_execution_types import RealAgentTeamTaskExecution
from .agent_team_scoped_tools import build_agent_team_scoped_tools

_outcome_from_result = outcome_from_result
_task_scoped_tools = task_scoped_tools


def is_real_agent_team_execution_enabled(
    settings: Any | None,
    *,
    service: Any | None = None,
) -> bool:
    """Return true only after the explicit real-execution readiness assessment passes."""
    if not is_real_agent_team_execution_requested(settings):
        return False
    runtime = _readiness_runtime_for_service(service)
    if runtime is None:
        return False
    try:
        from .agent_team_readiness import build_agent_team_readiness

        readiness = build_agent_team_readiness(settings, runtime=runtime)
    except Exception:  # noqa: BLE001
        return False
    return readiness.get("phase") == "ready"


def is_real_agent_team_execution_requested(settings: Any | None) -> bool:
    """Return whether the explicit worktree+sandbox execution mode was requested."""
    return bool(
        settings is not None
        and str(getattr(settings, "agent_team_execution_mode", "disabled") or "").lower()
        == "worktree_sandbox"
    )


def execute_real_agent_team_task(
    service: Any,
    *,
    task: AgentTeamTask,
    user_id: str,
    workspace_metadata: Mapping[str, Any],
    scheduler_wave: int,
    cancellation_token: CancellationToken | None = None,
) -> RealAgentTeamTaskExecution:
    """Execute one task through the isolated model-to-tool loop."""
    if not is_real_agent_team_execution_enabled(service.settings, service=service):
        return failed_outcome(
            task,
            "Real Agent Team execution is blocked because readiness is not ready.",
        )
    workspace_path = str(workspace_metadata.get("workspace_path") or task.workspace_path or "")
    if not workspace_path:
        return failed_outcome(task, "Real task execution requires an isolated worktree.")

    task_run_id = f"task-run-{uuid4().hex}"
    run = _create_task_run(
        task=task,
        task_run_id=task_run_id,
        workspace_metadata=workspace_metadata,
        scheduler_wave=scheduler_wave,
    )
    service.repository.create_task_run(run)
    try:
        append_event(
            service,
            run=run,
            event_type="started",
            status="running",
            summary="Agent Team real tool-loop task started.",
        )
    except Exception as exc:  # noqa: BLE001
        return finalize_failed_run(
            service,
            task=task,
            run=run,
            error=f"Real Agent Team task-run initialization failed: {exc}",
            failure_stage="start_event",
        )

    try:
        result = _run_task_loop(
            service,
            task=task,
            run=run,
            user_id=user_id,
            workspace_path=workspace_path,
            workspace_metadata=workspace_metadata,
            cancellation_token=cancellation_token,
        )
        return outcome_from_result(
            service,
            task=task,
            run=run,
            result=result,
            workspace_metadata=workspace_metadata,
            scheduler_wave=scheduler_wave,
        )
    except Exception as exc:  # noqa: BLE001
        return finalize_failed_run(
            service,
            task=task,
            run=run,
            error=f"Real Agent Team tool-loop setup failed: {exc}",
            failure_stage="setup",
        )


def _create_task_run(
    *,
    task: AgentTeamTask,
    task_run_id: str,
    workspace_metadata: Mapping[str, Any],
    scheduler_wave: int,
) -> TaskRun:
    started_at = now()
    return TaskRun(
        task_run_id=task_run_id,
        task_id=task.task_id,
        session_id=task.session_id,
        status=AgentTeamTaskStatus.RUNNING,
        attempt=max(1, int(task.attempt or 0)),
        started_at=started_at,
        execution_profile="worktree_sandbox",
        execution_class=AgentTeamExecutionClass.TOOL_AGENT,
        evidence_level=AgentTeamEvidenceLevel.WORKTREE,
        evidence_verdict=AgentTeamEvidenceVerdict.INCONCLUSIVE,
        sandbox_id=f"agent-team:{task.session_id}:{task.task_id}:{task_run_id}",
        revision_id=task.revision_id,
        row_version=task.row_version,
        cancel_epoch=task.cancel_epoch,
        metadata={"scheduler_wave": scheduler_wave, "workspace": dict(workspace_metadata)},
        created_at=started_at,
        updated_at=started_at,
    )


def _run_task_loop(
    service: Any,
    *,
    task: AgentTeamTask,
    run: TaskRun,
    user_id: str,
    workspace_path: str,
    workspace_metadata: Mapping[str, Any],
    cancellation_token: CancellationToken | None,
) -> Any:
    command_config = getattr(
        getattr(getattr(service, "settings", None), "tool_catalog", None),
        "run_workspace_command",
        None,
    )
    scoped_tools = build_agent_team_scoped_tools(
        workspace_root=workspace_path,
        write_scope=task.write_scope,
        sandbox_runner=sandbox_runner_for_service(service),
        task_id=task.task_id,
        require_docker=True,
        allow_fallback=False,
        allowed_commands=getattr(command_config, "allowed_commands", ())
        or (
            "cargo",
            "go",
            "make",
            "mypy",
            "npm",
            "pnpm",
            "pytest",
            "ruff",
            "uv",
        ),
        emit_tool_event=lambda **payload: append_event(
            service,
            run=run,
            event_type=f"tool_{payload.get('stage', 'event')}",
            status=str(payload.get("stage") or "event"),
            summary=str(payload.get("tool_name") or "tool"),
            metadata=payload,
        ),
    )
    allowed_names = allowed_scoped_tool_names(task)
    model = task_model_for_service(
        service,
        task=task,
        langchain_tools=[scoped_tools[name] for name in allowed_names if name in scoped_tools],
        settings=service.settings,
    )
    runner = TaskAgentRunner(
        model=model,
        tools=task_scoped_tools(scoped_tools, allowed_names),
        max_rounds=_max_rounds(service.settings),
        checkpoint_sink=lambda checkpoint: persist_checkpoint(
            service, run=run, checkpoint=checkpoint
        ),
        evidence_sink=lambda evidence: persist_runner_evidence(service, run=run, evidence=evidence),
    )
    return runner.run(
        scope=TaskExecutionScope(
            task_id=task.task_id,
            session_id=task.session_id,
            user_id=user_id,
            workspace_path=workspace_path,
            allowed_tool_names=frozenset(allowed_names),
            write_scope=tuple(task.write_scope),
            metadata={
                "role": task.role.value,
                "goal": task.goal,
                "workspace_branch": workspace_metadata.get("workspace_branch"),
                "base_commit": workspace_metadata.get("base_commit"),
                "sandbox_id": run.sandbox_id,
            },
        ),
        prompt=task_prompt(service, task, user_id=user_id),
        cancellation_token=cancellation_token,
        run_id=run.task_run_id,
    )


def _max_rounds(settings: Any) -> int:
    return max(1, min(12, int(getattr(settings, "agent_subagent_max_turns", 8) or 8)))


def _readiness_runtime_for_service(service: Any | None) -> Any | None:
    return getattr(service, "_agent_team_runtime", None) if service is not None else None
