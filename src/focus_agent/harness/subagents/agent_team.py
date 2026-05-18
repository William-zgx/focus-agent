from __future__ import annotations

import asyncio
import uuid
from typing import Any

from focus_agent.config import Settings
from focus_agent.delegation.delegation_models import AgentTask
from focus_agent.delegation.execution import (
    DelegatedRunExecutor,
    SubagentRegistry,
    executor_for_mode,
    normalize_delegation_execution_mode,
    run_delegated_tasks,
)
from focus_agent.delegation.roles import AgentRole, normalize_agent_role

from ..runtime import RunRecord
from .executor import SubagentTaskRequest, SubagentTaskResult


class AgentTeamSubagentRunner:
    """Bridge harness task-tool calls into the existing delegated-agent runtime."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        model_factory: Any | None = None,
        executor: DelegatedRunExecutor | None = None,
    ) -> None:
        self._settings = settings or Settings()
        self._model_factory = model_factory
        self._executor = executor

    async def run(
        self,
        request: SubagentTaskRequest,
        *,
        run_record: RunRecord,
    ) -> SubagentTaskResult:
        return await asyncio.to_thread(self._run_sync, request, run_record)

    def _run_sync(
        self,
        request: SubagentTaskRequest,
        run_record: RunRecord,
    ) -> SubagentTaskResult:
        task = _task_from_request(request, run_record=run_record)
        results = run_delegated_tasks(
            tasks=[task],
            registry=SubagentRegistry.from_settings(
                self._settings,
                context_refs=list(task.context_refs),
            ),
            executor=self._executor_for_settings(),
            max_parallel_runs=1,
        )
        if not results:
            return SubagentTaskResult(
                content="Delegated execution is disabled by configuration.",
                metadata={
                    "execution_status": "skipped",
                    "execution_mode": "observe",
                    "role": task.role.value,
                    "delegated_task_id": task.task_id,
                },
                artifact={"runs": []},
            )

        result = results[0]
        return SubagentTaskResult(
            content=result.summary or result.error or f"{result.role.value} run {result.status}.",
            metadata={
                "execution_status": result.status,
                "execution_mode": result.execution_mode,
                "agent_run_id": result.run_id,
                "delegated_task_id": result.task_id,
                "role": result.role.value,
                "model_id": result.model_id,
                "tool_calls": result.tool_calls,
                "cost": result.cost,
                "error": result.error,
                "workspace_id": result.workspace_id,
                "workspace_path": result.workspace_path,
                "workspace_branch": result.workspace_branch,
                "base_commit": result.base_commit,
                "changed_files": list(result.changed_files),
                "diff_summary": result.diff_summary,
                "test_evidence": list(result.test_evidence),
                "workspace_status": result.workspace_status,
            },
            artifact={
                "run": result.model_dump(mode="json"),
                "artifacts": [artifact.model_dump(mode="json") for artifact in result.artifacts],
            },
        )

    def _executor_for_settings(self) -> DelegatedRunExecutor | None:
        if self._executor is not None:
            return self._executor
        mode = normalize_delegation_execution_mode(
            getattr(self._settings, "agent_delegation_execution_mode", "observe")
        )
        return executor_for_mode(
            mode,
            model_factory=self._model_factory,
            settings=self._settings,
            max_workers=getattr(self._settings, "agent_role_max_parallel_runs", None),
        )


def _task_from_request(request: SubagentTaskRequest, *, run_record: RunRecord) -> AgentTask:
    role = _role_from_mapping(request.input) or _role_from_mapping(request.metadata)
    context_refs = _list_of_dicts(
        request.input.get("context_refs") or request.metadata.get("context_refs") or []
    )
    task_id = str(
        request.input.get("task_id")
        or request.metadata.get("task_id")
        or f"harness-task-{uuid.uuid4().hex}"
    )
    return AgentTask(
        task_id=task_id,
        role=role or AgentRole.EXECUTOR,
        goal=request.instruction,
        constraints=_str_list(
            request.input.get("constraints") or request.metadata.get("constraints")
        ),
        allowed_tools=_str_list(
            request.input.get("allowed_tools") or request.metadata.get("allowed_tools")
        ),
        acceptance_criteria=_str_list(
            request.input.get("acceptance_criteria") or request.metadata.get("acceptance_criteria")
        ),
        max_turns=_positive_int(
            request.input.get("max_turns") or request.metadata.get("max_turns"),
            default=1,
        ),
        timeout_seconds=_positive_int(
            request.input.get("timeout_seconds") or request.metadata.get("timeout_seconds"),
            default=30,
        ),
        max_depth=_non_negative_int(
            request.input.get("max_depth") or request.metadata.get("max_depth"),
            default=1,
        ),
        requires_workspace_write=_bool_value(
            request.input.get("requires_workspace_write")
            or request.metadata.get("requires_workspace_write")
        ),
        requires_network=_bool_value(
            request.input.get("requires_network") or request.metadata.get("requires_network")
        ),
        context_refs=context_refs,
        run_isolation_key=str(
            request.input.get("run_isolation_key")
            or request.metadata.get("run_isolation_key")
            or f"harness:{run_record.run_id}"
        ),
        workspace_id=_optional_str(
            request.input.get("workspace_id") or request.metadata.get("workspace_id")
        ),
        workspace_path=_optional_str(
            request.input.get("workspace_path") or request.metadata.get("workspace_path")
        ),
        workspace_branch=_optional_str(
            request.input.get("workspace_branch") or request.metadata.get("workspace_branch")
        ),
        base_commit=_optional_str(
            request.input.get("base_commit") or request.metadata.get("base_commit")
        ),
    )


def _role_from_mapping(mapping: dict[str, Any]) -> AgentRole | None:
    value = mapping.get("role")
    if not value:
        return None
    try:
        return normalize_agent_role(str(value))
    except (ValueError, TypeError):
        return AgentRole.EXECUTOR


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _non_negative_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = ["AgentTeamSubagentRunner"]
