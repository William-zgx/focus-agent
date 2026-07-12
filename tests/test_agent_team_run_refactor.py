from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import focus_agent.services.agent_team_run as agent_team_run
from focus_agent.services.agent_team_run import AgentTeamRunMixin


def test_agent_team_run_mixin_delegates_planning_through_patchable_operation(monkeypatch) -> None:
    service = AgentTeamRunMixin()
    expected = (SimpleNamespace(session_id="session-1"), [SimpleNamespace(task_id="task-1")])
    captured: dict[str, object] = {}

    def plan_session(operation_service: object, **kwargs: object) -> object:
        captured["service"] = operation_service
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(agent_team_run, "_run_plan_session", plan_session)

    result = service.plan_session(
        session_id="session-1",
        user_id="user-1",
        create_branches=False,
        parent_thread_id="thread-1",
    )

    assert result is expected
    assert captured == {
        "service": service,
        "session_id": "session-1",
        "user_id": "user-1",
        "create_branches": False,
        "parent_thread_id": "thread-1",
        "task_identity": agent_team_run._task_identity,
        "team_role_for_agent_role": agent_team_run._team_role_for_agent_role,
    }


def test_agent_team_run_mixin_keeps_claimed_execution_patch_seams(monkeypatch) -> None:
    service = AgentTeamRunMixin()
    expected = SimpleNamespace(task_id="task-1")
    captured: dict[str, object] = {}

    def run_task_claimed(operation_service: object, **kwargs: object) -> object:
        captured["service"] = operation_service
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(agent_team_run, "_run_task_claimed", run_task_claimed)

    result = service.run_task_claimed(task_id="task-1", user_id="user-1")

    assert result is expected
    assert captured["service"] is service
    assert captured["task_id"] == "task-1"
    assert captured["user_id"] == "user-1"
    assert captured["owner_factory"]().startswith("agent-team:")
    assert captured["lease_heartbeat_factory"] is agent_team_run._AgentTeamLeaseHeartbeat
    assert (
        captured["failure_strategy_for_exception"] is agent_team_run._failure_strategy_for_exception
    )
    assert captured["failure_handler_factory"] is agent_team_run.FailureHandler
    assert captured["task_execution_result_factory"] is agent_team_run._TaskExecutionResult
    assert captured["artifact_kind_for_task"] is agent_team_run._artifact_kind_for_task
    assert captured["now"] is agent_team_run._now


def test_agent_team_run_operations_do_not_import_the_compatibility_mixin() -> None:
    root = Path(__file__).parents[1]
    source = root.joinpath("src/focus_agent/services/agent_team_run_orchestration.py").read_text(
        encoding="utf-8"
    )
    imports = [
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    ]

    assert "agent_team_run" not in imports
    assert (
        len(
            root.joinpath("src/focus_agent/services/agent_team_run.py")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        <= 700
    )
