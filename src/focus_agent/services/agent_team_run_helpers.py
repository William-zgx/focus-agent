from __future__ import annotations

from typing import Any

from focus_agent.core.agent_team import (
    AgentTeamArtifactKind,
    AgentTeamTask,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)
from focus_agent.delegation.execution import DelegatedRunExecutor
from focus_agent.delegation.roles import AgentRole

from .agent_team_helpers import _dedupe
from .agent_team_workspace import AgentTeamWorkspaceStatus

_MAX_MISSION_SCHEDULER_WAVES = 16
_MAX_MISSION_SCHEDULER_TASKS = 64
_AGENT_TEAM_TASK_CLAIM_TTL_SECONDS = 300.0

_AGENT_ROLE_TO_TEAM_ROLE: dict[AgentRole, AgentTeamTaskRole] = {
    AgentRole.ORCHESTRATOR: AgentTeamTaskRole.ARCHITECT,
    AgentRole.PLANNER: AgentTeamTaskRole.PLANNER,
    AgentRole.EXECUTOR: AgentTeamTaskRole.BACKEND_EXECUTOR,
    AgentRole.CRITIC: AgentTeamTaskRole.REVIEWER,
    AgentRole.MEMORY_CURATOR: AgentTeamTaskRole.PLANNER,
    AgentRole.SKILL_SCOUT: AgentTeamTaskRole.PLANNER,
}


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


def _should_use_task_workspace(task: AgentTeamTask, executor: DelegatedRunExecutor | None) -> bool:
    if executor is None or getattr(executor, "mode", "observe") in {"observe", "fake"}:
        return False
    return _is_writable_team_task(task)


def _is_writable_team_task(task: AgentTeamTask) -> bool:
    if task.write_scope:
        return True
    if task.task_type in {"implementation", "execution"}:
        return True
    return task.role in {
        AgentTeamTaskRole.BACKEND_EXECUTOR,
        AgentTeamTaskRole.FRONTEND_EXECUTOR,
        AgentTeamTaskRole.TEST_ENGINEER,
    }


def _allowed_tools_for_task(task: AgentTeamTask) -> list[str]:
    tools = list(task.scope)
    if task.active_skill_ids:
        tools.extend(["skills_list", "skill_view", "skill_sources", "skills_search"])
    for ref in task.context_refs:
        if not isinstance(ref, dict):
            continue
        if ref.get("kind") != "skill" and ref.get("type") != "skill":
            continue
        raw_tools = ref.get("recommended_tools") or ()
        if isinstance(raw_tools, str):
            tools.append(raw_tools)
        else:
            tools.extend(str(tool) for tool in raw_tools if str(tool).strip())
    if _is_writable_team_task(task):
        tools.extend(["search_code", "write_text_artifact"])
    return _dedupe(tools)


def _workspace_metadata_for_run(
    run: Any, workspace_status: AgentTeamWorkspaceStatus | None
) -> dict[str, str | None]:
    metadata: dict[str, str | None] = {
        "workspace_id": getattr(run, "workspace_id", None),
        "workspace_branch": getattr(run, "workspace_branch", None),
        "workspace_path": getattr(run, "workspace_path", None),
        "base_commit": getattr(run, "base_commit", None),
        "diff_summary": getattr(run, "diff_summary", None),
        "workspace_status": getattr(run, "workspace_status", None),
    }
    if workspace_status is not None:
        metadata["diff_summary"] = workspace_status.diff_summary
        metadata["workspace_status"] = workspace_status.workspace_status
    return {key: value for key, value in metadata.items() if value}


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


__all__ = [
    "_AGENT_TEAM_TASK_CLAIM_TTL_SECONDS",
    "_MAX_MISSION_SCHEDULER_TASKS",
    "_MAX_MISSION_SCHEDULER_WAVES",
    "_agent_team_execution_mode",
    "_allowed_tools_for_task",
    "_artifact_kind_for_task",
    "_changed_files_for_run",
    "_is_runnable_task",
    "_is_writable_team_task",
    "_max_parallel_runs_for",
    "_risk_notes_for_run",
    "_run_metadata",
    "_scheduler_state",
    "_should_use_task_workspace",
    "_task_identity",
    "_task_wave",
    "_team_role_for_agent_role",
    "_team_status_for_run_status",
    "_test_evidence_for_run",
    "_workspace_metadata_for_run",
]
