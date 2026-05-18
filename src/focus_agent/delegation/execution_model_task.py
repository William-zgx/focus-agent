from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Literal

from langchain.messages import HumanMessage, SystemMessage

from focus_agent.prompts import get_registry

from ..config import Settings
from .delegation_models import AgentArtifact, AgentTask
from .execution_modes import DelegationExecutionMode, ModelFactory
from .execution_types import SubagentConfig, SubagentRunResult
from .roles import AgentRole

_CWD_LOCK = RLock()
_MODEL_TASK_SYSTEM_PROMPT_ID = "delegation.model_task.system"


def execute_model_task(
    *,
    task: AgentTask,
    config: SubagentConfig,
    mode: DelegationExecutionMode,
    model: Any | None,
    model_factory: ModelFactory | None,
    settings: Settings | None,
    max_result_chars: int,
) -> SubagentRunResult:
    started = utc_now()
    try:
        runnable = _model_for_task(
            model=model, model_factory=model_factory, config=config, settings=settings
        )
        if hasattr(runnable, "with_config"):
            runnable = runnable.with_config(
                {"run_name": f"delegated-{task.role.value}", "tags": ["agent_delegation", mode]}
            )
        with _working_directory(config.workspace_path):
            response = runnable.invoke(_prompt_messages(task, config))
        raw_text = _message_text(response)[:max_result_chars]
        if not raw_text.strip():
            return failed_result(
                task, config, mode, "Delegated run produced an empty response.", started_at=started
            )
        parsed = _parse_json_object(raw_text)
        summary = str(parsed.get("summary") or raw_text).strip()[:max_result_chars]
        status, error = _status_from_output(task, parsed)
        artifact = AgentArtifact(
            artifact_id=f"artifact-{task.task_id}-{mode}-result",
            kind=artifact_kind(task.role),
            title=f"{task.role.value} {mode} delegated result",
            summary=summary,
            payload={
                "goal": task.goal,
                "acceptance_criteria": list(task.acceptance_criteria),
                "constraints": list(task.constraints),
                "allowed_tools": list(config.allowed_tools),
                "run_isolation_key": config.run_isolation_key,
                "workspace_id": config.workspace_id,
                "workspace_path": config.workspace_path,
                "workspace_branch": config.workspace_branch,
                "base_commit": config.base_commit,
                "context_refs": list(config.context_refs),
                "raw_text": raw_text,
                **({"parsed": parsed} if parsed else {}),
            },
        )
        return SubagentRunResult(
            run_id=f"run-{task.task_id}",
            task_id=task.task_id,
            role=task.role,
            status=status,
            summary=summary,
            artifacts=[artifact] if status != "failed" else [],
            error=error,
            tool_calls=0,
            cost=0.0,
            model_id=config.model_id,
            started_at=started,
            finished_at=utc_now(),
            execution_mode=mode,
            workspace_id=config.workspace_id,
            workspace_path=config.workspace_path,
            workspace_branch=config.workspace_branch,
            base_commit=config.base_commit,
        )
    except Exception as exc:  # noqa: BLE001
        return failed_result(task, config, mode, str(exc), started_at=started)


def failed_result(
    task: AgentTask,
    config: SubagentConfig,
    mode: DelegationExecutionMode,
    error: str,
    *,
    started_at: str,
) -> SubagentRunResult:
    return SubagentRunResult(
        run_id=f"run-{task.task_id}",
        task_id=task.task_id,
        role=task.role,
        status="failed",
        summary=error,
        error=error,
        model_id=config.model_id,
        started_at=started_at,
        finished_at=utc_now(),
        execution_mode=mode,
        workspace_id=config.workspace_id,
        workspace_path=config.workspace_path,
        workspace_branch=config.workspace_branch,
        base_commit=config.base_commit,
    )


def blocked_result_with_reason(
    task: AgentTask,
    config: SubagentConfig,
    mode: DelegationExecutionMode,
    reason: str,
) -> SubagentRunResult:
    now = utc_now()
    return SubagentRunResult(
        run_id=f"run-{task.task_id}",
        task_id=task.task_id,
        role=task.role,
        status="needs_review",
        summary=reason,
        error=reason,
        model_id=config.model_id,
        started_at=now,
        finished_at=now,
        execution_mode=mode,
        workspace_id=config.workspace_id,
        workspace_path=config.workspace_path,
        workspace_branch=config.workspace_branch,
        base_commit=config.base_commit,
    )


def artifact_kind(role: AgentRole) -> str:
    if role == AgentRole.PLANNER:
        return "plan"
    if role == AgentRole.CRITIC:
        return "critic_verdict"
    if role == AgentRole.MEMORY_CURATOR:
        return "memory_candidate"
    if role == AgentRole.SKILL_SCOUT:
        return "tool_route_evidence"
    if role == AgentRole.EXECUTOR:
        return "patch_summary"
    return "evidence"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _model_for_task(
    *,
    model: Any | None,
    model_factory: ModelFactory | None,
    config: SubagentConfig,
    settings: Settings | None,
) -> Any:
    if model is not None:
        return model
    factory = model_factory
    if factory is None:
        from ..model_registry import create_chat_model

        factory = create_chat_model
    return factory(
        config.model_id or getattr(settings, "model", ""), temperature=0.0, settings=settings
    )


def _prompt_messages(task: AgentTask, config: SubagentConfig) -> list[Any]:
    context_refs = json.dumps(config.context_refs[:8], ensure_ascii=False, default=str)
    payload = {
        "task_id": task.task_id,
        "role": task.role.value,
        "goal": task.goal,
        "constraints": list(task.constraints),
        "acceptance_criteria": list(task.acceptance_criteria),
        "allowed_tools": list(config.allowed_tools),
        "run_isolation_key": config.run_isolation_key,
        "workspace_id": config.workspace_id,
        "workspace_path": config.workspace_path,
        "workspace_branch": config.workspace_branch,
        "base_commit": config.base_commit,
        "context_refs": context_refs[:4000],
    }
    return [
        SystemMessage(
            content=get_registry().render(
                _MODEL_TASK_SYSTEM_PROMPT_ID,
                role=task.role.value,
            )
        ),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
    ]


@contextmanager
def _working_directory(path: str | None):
    if not path:
        yield
        return
    previous = os.getcwd()
    with _CWD_LOCK:
        os.chdir(path)
        try:
            yield
        finally:
            os.chdir(previous)


def _message_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _status_from_output(
    task: AgentTask, parsed: dict[str, Any]
) -> tuple[Literal["completed", "failed", "needs_review"], str | None]:
    verdict = str(parsed.get("verdict") or "").strip().lower()
    if verdict in {"needs_review", "needs-review"}:
        return "needs_review", "Delegated run requested review."
    if task.role == AgentRole.CRITIC and verdict in {
        "reject",
        "rejected",
        "retry",
        "fail",
        "failed",
    }:
        return "failed", f"Critic delegated run returned verdict={verdict}."
    return "completed", None


__all__ = [
    "artifact_kind",
    "blocked_result_with_reason",
    "execute_model_task",
    "failed_result",
    "utc_now",
]
