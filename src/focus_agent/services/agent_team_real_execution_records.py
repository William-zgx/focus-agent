"""Persistence, redaction, and evidence projection for real Agent Team runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from focus_agent.core.agent_team import (
    AgentTeamEvidenceLevel,
    AgentTeamEvidenceVerdict,
    AgentTeamExecutionClass,
    AgentTeamTask,
    AgentTeamTaskStatus,
    EvidenceRecord,
    TaskCheckpoint,
    TaskRun,
    TaskRunEvent,
    ToolExecution,
)

from .agent_team_execution_runtime import TaskExecutionEvidence, TaskRunResult, TaskRunStatus
from .agent_team_real_execution_types import RealAgentTeamTaskExecution


def outcome_from_result(
    service: Any,
    *,
    task: AgentTeamTask,
    run: TaskRun,
    result: TaskRunResult,
    workspace_metadata: Mapping[str, Any],
    scheduler_wave: int,
) -> RealAgentTeamTaskExecution:
    """Persist a completed loop and project its evidence to task/output fields."""
    workspace_evidence = workspace_evidence_for_task(service, task, workspace_metadata)
    command_evidence = command_evidence_from_result(result.evidence)
    approval_metadata = approval_metadata_for_result(
        service,
        task=task,
        run=run,
        result=result,
    )
    verified = bool(command_evidence) and all(
        item.get("sandbox_backend") == "docker"
        and item.get("fallback_used") is False
        and item.get("exit_code") == 0
        for item in command_evidence
    )
    status_map = {
        TaskRunStatus.COMPLETED: AgentTeamTaskStatus.DONE,
        TaskRunStatus.CANCELLED: AgentTeamTaskStatus.CANCELLED,
        TaskRunStatus.PAUSED_FOR_APPROVAL: AgentTeamTaskStatus.BLOCKED,
        TaskRunStatus.FAILED: AgentTeamTaskStatus.FAILED,
        TaskRunStatus.MAX_ROUNDS_REACHED: AgentTeamTaskStatus.FAILED,
    }
    final_status = status_map[result.status]
    execution_class = (
        AgentTeamExecutionClass.SANDBOX_VERIFIED
        if verified and final_status == AgentTeamTaskStatus.DONE
        else AgentTeamExecutionClass.TOOL_AGENT
    )
    evidence_level = (
        AgentTeamEvidenceLevel.VERIFIED
        if execution_class == AgentTeamExecutionClass.SANDBOX_VERIFIED
        else AgentTeamEvidenceLevel.WORKTREE
    )
    evidence_verdict = (
        AgentTeamEvidenceVerdict.VERIFIED
        if execution_class == AgentTeamExecutionClass.SANDBOX_VERIFIED
        else AgentTeamEvidenceVerdict.INCONCLUSIVE
    )
    finished_at = now()
    summary = _result_summary(result)
    evidence_summary = _evidence_summary(verified, approval_metadata)
    final_run = run.model_copy(
        update={
            "status": final_status,
            "finished_at": finished_at,
            "last_error": result.error,
            "execution_class": execution_class,
            "evidence_level": evidence_level,
            "evidence_verdict": evidence_verdict,
            "evidence_summary": evidence_summary,
            "deliverable": execution_class == AgentTeamExecutionClass.SANDBOX_VERIFIED,
            "metadata": {
                **run.metadata,
                "workspace_evidence": workspace_evidence,
                "command_evidence": command_evidence,
                "rounds_completed": result.rounds_completed,
                **({"approval": approval_metadata} if approval_metadata else {}),
            },
            "updated_at": finished_at,
        }
    )
    service.repository.save_task_run(final_run)
    append_event(
        service,
        run=final_run,
        event_type=result.status.value,
        status=final_status.value,
        summary=summary,
        metadata={
            "verified": verified,
            **({"approval": approval_metadata} if approval_metadata else {}),
        },
    )
    append_evidence(
        service,
        run=final_run,
        source_type="worktree",
        summary="Worktree state captured after task tool-loop execution.",
        level=AgentTeamEvidenceLevel.WORKTREE,
        verdict=AgentTeamEvidenceVerdict.INCONCLUSIVE,
        metadata=workspace_evidence,
    )
    if approval_metadata:
        append_evidence(
            service,
            run=final_run,
            source_type="tool_approval",
            summary="A redacted write-tool approval request was queued without automatic resume.",
            level=AgentTeamEvidenceLevel.WORKTREE,
            verdict=AgentTeamEvidenceVerdict.INCONCLUSIVE,
            metadata=approval_metadata,
        )
    for item in command_evidence:
        command_verified = (
            item.get("sandbox_backend") == "docker"
            and item.get("fallback_used") is False
            and item.get("exit_code") == 0
        )
        append_evidence(
            service,
            run=final_run,
            source_type="sandbox_command",
            summary=str(item.get("command") or "sandbox command"),
            level=(
                AgentTeamEvidenceLevel.VERIFIED
                if command_verified
                else AgentTeamEvidenceLevel.SANDBOX
            ),
            verdict=(
                AgentTeamEvidenceVerdict.VERIFIED
                if command_verified
                else AgentTeamEvidenceVerdict.REJECTED
            ),
            metadata=item,
        )
    return _project_outcome(
        task=task,
        final_run=final_run,
        final_status=final_status,
        result=result,
        workspace_metadata=workspace_metadata,
        workspace_evidence=workspace_evidence,
        command_evidence=command_evidence,
        scheduler_wave=scheduler_wave,
        summary=summary,
        verified=verified,
        approval_metadata=approval_metadata,
    )


def persist_checkpoint(service: Any, *, run: TaskRun, checkpoint: Any) -> None:
    """Persist a task-loop checkpoint with tool arguments redacted."""
    service.repository.append_task_checkpoint(
        TaskCheckpoint(
            checkpoint_id=f"checkpoint-{uuid4().hex}",
            task_run_id=run.task_run_id,
            task_id=run.task_id,
            session_id=run.session_id,
            sequence=checkpoint.round_number,
            checkpoint_type=checkpoint.event.value,
            summary=str(checkpoint.payload.get("final_answer") or checkpoint.event.value),
            state=redacted_checkpoint_state(checkpoint),
            execution_profile="worktree_sandbox",
            execution_class=AgentTeamExecutionClass.TOOL_AGENT,
            evidence_level=AgentTeamEvidenceLevel.WORKTREE,
            evidence_verdict=AgentTeamEvidenceVerdict.INCONCLUSIVE,
            sandbox_id=run.sandbox_id,
            created_at=checkpoint.created_at,
        )
    )


def persist_runner_evidence(
    service: Any,
    *,
    run: TaskRun,
    evidence: TaskExecutionEvidence,
) -> None:
    """Persist tool-loop evidence while keeping approval payloads secret-safe."""
    metadata = {
        "value": redacted_approval_arguments(evidence.value),
        "round_number": evidence.round_number,
        "kind": evidence.kind,
        "tool_call_id": evidence.tool_call_id,
    }
    service.repository.append_tool_execution(
        ToolExecution(
            tool_execution_id=f"tool-execution-{uuid4().hex}",
            task_run_id=run.task_run_id,
            task_id=run.task_id,
            session_id=run.session_id,
            tool_name=evidence.tool_name or evidence.kind,
            status="awaiting_approval" if evidence.kind == "approval_request" else "completed",
            response=metadata,
            execution_profile="worktree_sandbox",
            execution_class=AgentTeamExecutionClass.TOOL_AGENT,
            evidence_level=AgentTeamEvidenceLevel.WORKTREE,
            evidence_verdict=AgentTeamEvidenceVerdict.INCONCLUSIVE,
            sandbox_id=run.sandbox_id,
            created_at=now(),
        )
    )


def workspace_evidence_for_task(
    service: Any,
    task: AgentTeamTask,
    workspace_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Capture worktree status and both path-specific and clean-diff hashes."""
    workspace_path = str(workspace_metadata.get("workspace_path") or task.workspace_path or "")
    if not workspace_path:
        raise RuntimeError("Real task execution requires workspace status capture.")
    status = service.workspace_service.collect_status(workspace_path)
    if status.workspace_status not in {"clean", "dirty"}:
        raise RuntimeError(
            f"Workspace status capture is not trustworthy: {status.workspace_status or 'unknown'}."
        )
    changed_files = list(status.changed_files)
    diff_summary = status.diff_summary
    worktree_hash = _hash_evidence(
        base_commit=workspace_metadata.get("base_commit"),
        changed_files=changed_files,
        diff_summary=diff_summary,
        workspace_path=workspace_path,
    )
    diff_hash = _hash_evidence(
        base_commit=workspace_metadata.get("base_commit"),
        changed_files=changed_files,
        diff_summary=diff_summary,
    )
    return {
        "base_commit": workspace_metadata.get("base_commit"),
        "workspace_branch": workspace_metadata.get("workspace_branch"),
        "workspace_path": workspace_path,
        "changed_files": changed_files,
        "diff_summary": diff_summary,
        "worktree_hash": worktree_hash,
        "diff_hash": diff_hash,
    }


def command_evidence_from_result(
    evidence: Sequence[TaskExecutionEvidence],
) -> list[dict[str, Any]]:
    """Select command evidence emitted by the task-scoped workspace command tool."""
    commands: list[dict[str, Any]] = []
    for item in evidence:
        if item.kind != "tool_result" or item.tool_name != "run_workspace_command":
            continue
        payload = item.value if isinstance(item.value, Mapping) else {}
        output = payload.get("output") if isinstance(payload, Mapping) else None
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except json.JSONDecodeError:
                output = {}
        if not isinstance(output, Mapping):
            continue
        raw_evidence = output.get("evidence")
        if not isinstance(raw_evidence, Mapping):
            continue
        commands.append(
            {
                "command": output.get("command"),
                "exit_code": raw_evidence.get("exit_code"),
                "sandbox_backend": raw_evidence.get("sandbox_backend"),
                "fallback_used": raw_evidence.get("fallback_used"),
                "sandbox_id": raw_evidence.get("sandbox_id"),
                "run_id": raw_evidence.get("run_id"),
                "timed_out": raw_evidence.get("timed_out"),
            }
        )
    return commands


def approval_metadata_for_result(
    service: Any,
    *,
    task: AgentTeamTask,
    run: TaskRun,
    result: TaskRunResult,
) -> dict[str, Any] | None:
    """Queue a redacted approval record; approvals never resume this loop."""
    if result.status != TaskRunStatus.PAUSED_FOR_APPROVAL:
        return None
    approval = result.pending_approval
    if approval is None:
        raise RuntimeError("Task paused for approval without a pending approval request.")
    queue = getattr(getattr(service, "coordination_backend", None), "approval_queue", None)
    submit_pending = getattr(queue, "submit_pending", None)
    if not callable(submit_pending):
        raise RuntimeError("Agent Team approval queue is unavailable for the paused task.")
    arguments = redacted_approval_arguments(approval.arguments)
    timeout_seconds = approval_timeout_seconds(getattr(service, "settings", None))
    submitted = submit_pending(
        request_id=approval.request_id,
        session_id=task.session_id,
        agent_id=f"{task.role.value}:{task.task_id}",
        tool_name=approval.tool_name,
        tool_args=arguments,
        risk_level=approval.risk_level,
        timeout_seconds=timeout_seconds,
    )
    return {
        "request_id": str(getattr(submitted, "request_id", approval.request_id)),
        "tool_call_id": approval.tool_call_id,
        "tool_name": approval.tool_name,
        "risk_level": approval.risk_level,
        "arguments": arguments,
        "timeout_seconds": timeout_seconds,
        "task_run_id": run.task_run_id,
        "resume_supported": False,
        "resume_reason": (
            "The real LangChain task loop does not persist raw tool arguments and replay-safe "
            "model state, so approval never executes the paused tool automatically."
        ),
    }


def redacted_checkpoint_state(checkpoint: Any) -> dict[str, Any]:
    """Redact sensitive nested tool arguments before persisting a checkpoint."""
    state = dict(checkpoint.payload)
    tool_calls = state.get("tool_calls")
    if not isinstance(tool_calls, list):
        return redacted_approval_arguments(state)
    redacted_calls = []
    for call in tool_calls:
        if not isinstance(call, Mapping):
            redacted_calls.append(call)
            continue
        redacted = dict(call)
        redacted["arguments"] = redacted_approval_arguments(
            call.get("arguments") if isinstance(call.get("arguments"), Mapping) else {}
        )
        redacted_calls.append(redacted)
    state["tool_calls"] = redacted_calls
    return redacted_approval_arguments(state)


def redacted_approval_arguments(value: Any) -> Any:
    """Recursively redact command, patch, and credential-like values."""
    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]"
                if _is_sensitive_approval_key(str(key))
                else redacted_approval_arguments(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redacted_approval_arguments(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redacted_approval_arguments(item) for item in value)
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


def append_event(
    service: Any,
    *,
    run: TaskRun,
    event_type: str,
    status: str,
    summary: str,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Append a task-run event using the run's current evidence classification."""
    service.repository.append_task_run_event(
        TaskRunEvent(
            event_id=f"task-event-{uuid4().hex}",
            task_run_id=run.task_run_id,
            task_id=run.task_id,
            session_id=run.session_id,
            event_type=event_type,
            status=status,
            summary=summary,
            metadata=dict(metadata or {}),
            execution_profile="worktree_sandbox",
            execution_class=run.execution_class,
            evidence_level=run.evidence_level,
            evidence_verdict=run.evidence_verdict,
            sandbox_id=run.sandbox_id,
            created_at=now(),
        )
    )


def append_evidence(
    service: Any,
    *,
    run: TaskRun,
    source_type: str,
    summary: str,
    level: AgentTeamEvidenceLevel,
    verdict: AgentTeamEvidenceVerdict,
    metadata: Mapping[str, Any],
) -> None:
    """Append a durable evidence record for the task run."""
    service.repository.append_evidence_record(
        EvidenceRecord(
            evidence_id=f"evidence-{uuid4().hex}",
            task_run_id=run.task_run_id,
            task_id=run.task_id,
            session_id=run.session_id,
            source_type=source_type,
            summary=summary,
            execution_profile="worktree_sandbox",
            execution_class=(
                AgentTeamExecutionClass.SANDBOX_VERIFIED
                if level == AgentTeamEvidenceLevel.VERIFIED
                else AgentTeamExecutionClass.TOOL_AGENT
            ),
            evidence_level=level,
            evidence_verdict=verdict,
            sandbox_id=run.sandbox_id,
            metadata=dict(metadata),
            created_at=now(),
        )
    )


def failed_outcome(
    task: AgentTeamTask,
    error: str,
    *,
    task_run_id: str | None = None,
    sandbox_id: str | None = None,
) -> RealAgentTeamTaskExecution:
    """Return a failed task projection when no successful result can be produced."""
    return RealAgentTeamTaskExecution(
        final_status=AgentTeamTaskStatus.FAILED,
        run_status="failed",
        execution_status="failed",
        task_updates={
            "task_run_id": task_run_id,
            "sandbox_id": sandbox_id,
            "execution_profile": "worktree_sandbox",
            "execution_class": AgentTeamExecutionClass.TOOL_AGENT,
            "evidence_level": AgentTeamEvidenceLevel.WORKTREE,
            "evidence_verdict": AgentTeamEvidenceVerdict.REJECTED,
            "evidence_summary": error,
            "deliverable": False,
            "finished_at": now(),
        },
        output=None,
        error=error,
    )


def finalize_failed_run(
    service: Any,
    *,
    task: AgentTeamTask,
    run: TaskRun,
    error: str,
    failure_stage: str,
) -> RealAgentTeamTaskExecution:
    """Persist a terminal failed run, event, and evidence record."""
    finished_at = now()
    failed_run = run.model_copy(
        update={
            "status": AgentTeamTaskStatus.FAILED,
            "finished_at": finished_at,
            "last_error": error,
            "execution_class": AgentTeamExecutionClass.TOOL_AGENT,
            "evidence_level": AgentTeamEvidenceLevel.WORKTREE,
            "evidence_verdict": AgentTeamEvidenceVerdict.REJECTED,
            "evidence_summary": error,
            "deliverable": False,
            "metadata": {
                **run.metadata,
                "failure_stage": failure_stage,
                "failure_error": error,
            },
            "updated_at": finished_at,
        }
    )
    service.repository.save_task_run(failed_run)
    append_event(
        service,
        run=failed_run,
        event_type="failed",
        status=AgentTeamTaskStatus.FAILED.value,
        summary=error,
        metadata={"failure_stage": failure_stage},
    )
    append_evidence(
        service,
        run=failed_run,
        source_type="execution_failure",
        summary=error,
        level=AgentTeamEvidenceLevel.WORKTREE,
        verdict=AgentTeamEvidenceVerdict.REJECTED,
        metadata={"failure_stage": failure_stage},
    )
    return failed_outcome(
        task,
        error,
        task_run_id=failed_run.task_run_id,
        sandbox_id=failed_run.sandbox_id,
    )


def approval_timeout_seconds(settings: Any | None) -> float:
    """Bound approval expiration even when settings are missing or malformed."""
    value = getattr(settings, "multi_agent_approval_timeout_seconds", 60.0)
    try:
        return max(1.0, min(float(value or 0.0), 86_400.0))
    except (TypeError, ValueError):
        return 60.0


def now() -> str:
    """Return UTC time in the repository's persisted ISO representation."""
    return datetime.now(UTC).isoformat()


def _project_outcome(
    *,
    task: AgentTeamTask,
    final_run: TaskRun,
    final_status: AgentTeamTaskStatus,
    result: TaskRunResult,
    workspace_metadata: Mapping[str, Any],
    workspace_evidence: Mapping[str, Any],
    command_evidence: Sequence[Mapping[str, Any]],
    scheduler_wave: int,
    summary: str,
    verified: bool,
    approval_metadata: Mapping[str, Any] | None,
) -> RealAgentTeamTaskExecution:
    output = None
    if final_status != AgentTeamTaskStatus.BLOCKED:
        output = {
            "kind": _artifact_kind(task),
            "summary": summary,
            "changed_files": list(workspace_evidence["changed_files"]),
            "test_evidence": _passed_commands(command_evidence),
            **dict(workspace_metadata),
            "risk_notes": _risk_notes(verified, approval_metadata),
            "task_run_id": final_run.task_run_id,
            "sandbox_id": final_run.sandbox_id,
            "execution_profile": final_run.execution_profile,
            "execution_class": final_run.execution_class,
            "evidence_level": final_run.evidence_level,
            "evidence_verdict": final_run.evidence_verdict,
            "evidence_summary": final_run.evidence_summary,
            "revision_id": final_run.revision_id,
            "row_version": final_run.row_version,
            "cancel_epoch": final_run.cancel_epoch,
            "deliverable": final_run.deliverable,
            "metadata": {
                "execution": {
                    "task_run_id": final_run.task_run_id,
                    "execution_profile": "worktree_sandbox",
                    "execution_class": final_run.execution_class.value,
                    "evidence_level": final_run.evidence_level.value,
                    "evidence_verdict": final_run.evidence_verdict.value,
                    "evidence_summary": final_run.evidence_summary,
                    "sandbox_id": final_run.sandbox_id,
                    "scheduler_wave": scheduler_wave,
                },
                "evidence": {
                    "execution_class": final_run.execution_class.value,
                    "evidence_level": final_run.evidence_level.value,
                    "evidence_verdict": final_run.evidence_verdict.value,
                    **dict(workspace_evidence),
                    "commands": list(command_evidence),
                },
            },
        }
    return RealAgentTeamTaskExecution(
        final_status=final_status,
        run_status=result.status.value,
        execution_status=(
            "awaiting_approval"
            if result.status == TaskRunStatus.PAUSED_FOR_APPROVAL
            else result.status.value
        ),
        task_updates={
            "task_run_id": final_run.task_run_id,
            "sandbox_id": final_run.sandbox_id,
            "execution_profile": "worktree_sandbox",
            "execution_class": final_run.execution_class,
            "evidence_level": final_run.evidence_level,
            "evidence_verdict": final_run.evidence_verdict,
            "evidence_summary": final_run.evidence_summary,
            "deliverable": final_run.deliverable,
            "changed_files": list(workspace_evidence["changed_files"]),
            "test_evidence": _passed_commands(command_evidence),
            **dict(workspace_metadata),
            "verification_summary": summary,
            "risk_notes": _task_update_risk_notes(verified, approval_metadata),
            "started_at": final_run.started_at,
            "finished_at": final_run.finished_at,
        },
        output=output,
        error=result.error or "",
    )


def _result_summary(result: TaskRunResult) -> str:
    if result.status == TaskRunStatus.PAUSED_FOR_APPROVAL:
        return (
            "Task is blocked pending explicit tool approval. Automatic resume is not supported; "
            "start a new controlled task run after the decision."
        )
    return result.final_answer or result.error or "Agent Team task finished without a final answer."


def _evidence_summary(verified: bool, approval_metadata: Mapping[str, Any] | None) -> str:
    if verified:
        return "Verified Docker sandbox command evidence and worktree diff were captured."
    if approval_metadata:
        return (
            "Task is paused for explicit approval. The pending request is redacted and "
            "automatic resume is unavailable."
        )
    return (
        "Task tool-loop evidence was captured but does not yet satisfy the verified delivery gate."
    )


def _risk_notes(
    verified: bool,
    approval_metadata: Mapping[str, Any] | None,
) -> list[str]:
    if verified:
        return []
    if approval_metadata:
        return ["Task is blocked pending explicit approval; automatic resume is not supported."]
    return ["Real tool-loop output lacks verified Docker command evidence."]


def _task_update_risk_notes(
    verified: bool,
    approval_metadata: Mapping[str, Any] | None,
) -> list[str]:
    if verified:
        return []
    if approval_metadata:
        return ["Task is blocked pending explicit approval; automatic resume is not supported."]
    return ["Verified delivery evidence remains incomplete."]


def _passed_commands(command_evidence: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(item.get("command")) for item in command_evidence if item.get("exit_code") == 0]


def _artifact_kind(task: AgentTeamTask) -> str:
    if task.role.value in {"test_engineer", "verifier"}:
        return "test_report"
    if task.role.value == "reviewer":
        return "review_report"
    if task.role.value in {"backend_executor", "frontend_executor"}:
        return "patch_summary"
    return "handoff"


def _hash_evidence(
    *,
    base_commit: Any,
    changed_files: Sequence[Any],
    diff_summary: Any,
    workspace_path: str | None = None,
) -> str:
    payload = {
        "base_commit": base_commit,
        "changed_files": list(changed_files),
        "diff_summary": diff_summary,
    }
    if workspace_path is not None:
        payload["workspace_path"] = workspace_path
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _is_sensitive_approval_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    if normalized in {"patch", "command"}:
        return True
    return any(
        marker in normalized
        for marker in ("token", "secret", "password", "api_key", "authorization", "credential")
    )
