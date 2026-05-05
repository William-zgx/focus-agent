from __future__ import annotations

import pytest

from focus_agent.config import Settings
from focus_agent.core.agent_team import AgentTeamSession, AgentTeamTask, AgentTeamTaskStatus
from focus_agent.services.agent_team import AgentTeamService


def test_agent_team_plan_uses_adaptive_dynamic_model_plan_and_is_idempotent() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(
        root_thread_id="root-1",
        user_id="user-1",
        goal="Implement a focused backend planning path.",
    )

    planned_session, planned = service.plan_session(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
        max_tasks=2,
    )
    repeated_session, repeated = service.plan_session(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
        max_tasks=2,
    )

    assert [task.task_id for task in repeated] == [task.task_id for task in planned]
    assert len(planned) == 2
    assert planned_session.planning_source == "model"
    assert planned_session.planner_model_id == "adaptive-planner:v1"
    assert planned_session.planning_error is None
    assert repeated_session.plan_hash == planned_session.plan_hash
    assert all(task.plan_source == "model" for task in planned)
    assert all(task.title for task in planned)
    assert all(task.planning_rationale for task in planned)
    assert [task.sort_order for task in planned] == [1, 2]
    assert planned[1].dependencies == [planned[0].task_id]
    assert "Plan the work, clarify boundaries" not in planned[0].goal


def test_agent_team_plan_replace_cancels_unstarted_tasks_without_repository_delete() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(
        root_thread_id="root-1",
        user_id="user-1",
        goal="Implement planning replacement.",
    )
    _, initial = service.plan_session(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
        max_tasks=2,
    )

    replaced_session, replacement = service.plan_session(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
        replace_existing=True,
        focus="Only backend service behavior.",
        max_tasks=2,
    )

    assert replaced_session.planning_source == "model"
    assert {task.task_id for task in initial}.isdisjoint({task.task_id for task in replacement})
    assert all("Only backend service behavior" in task.goal for task in replacement)
    assert all(
        service.get_task(task.task_id, user_id="user-1").status == AgentTeamTaskStatus.CANCELLED
        for task in initial
    )


def test_agent_team_plan_uses_delegation_when_available() -> None:
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(
            agent_delegation_enabled=True,
            agent_role_routing_enabled=True,
            agent_delegation_execution_mode="fake",
        ),
    )
    session = service.create_session(
        root_thread_id="root-1",
        user_id="user-1",
        goal="Plan, implement, and review backend orchestration.",
    )

    planned_session, tasks = service.plan_session(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
        granularity="detailed",
        max_tasks=4,
    )

    assert planned_session.planning_source == "model"
    assert planned_session.planner_model_id
    assert planned_session.plan_hash
    assert 1 <= len(tasks) <= 4
    assert all(task.plan_source == "model" for task in tasks)
    assert all(task.goal for task in tasks)
    assert all(task.acceptance_criteria for task in tasks)


def test_agent_team_plan_prefers_research_dag_over_generic_delegation() -> None:
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(
            agent_delegation_enabled=True,
            agent_role_routing_enabled=True,
            agent_delegation_execution_mode="fake",
        ),
    )
    session = service.create_session(
        root_thread_id="root-1",
        user_id="user-1",
        goal="做一份济州岛深冬旅行的攻略，涵盖旅行常见的各种部分。",
    )

    planned_session, tasks = service.plan_session(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
    )

    assert planned_session.planning_source == "model"
    assert planned_session.planning_error is None
    assert [task.task_type for task in tasks] == [
        "coordination",
        "research",
        "documentation",
        "review",
    ]
    assert tasks[0].title == "确认目标与边界"
    assert tasks[1].role.value == "planner"
    assert tasks[2].role.value == "writer"
    assert tasks[3].role.value == "reviewer"
    assert all(task.plan_source == "model" for task in tasks)


def test_agent_team_plan_falls_back_only_when_adaptive_planning_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_adaptive_failure(*args: object, **kwargs: object) -> list[dict[str, object]]:
        raise RuntimeError("planner fixture failed")

    monkeypatch.setattr(
        "focus_agent.services.agent_team_planning._adaptive_task_specs",
        _raise_adaptive_failure,
    )
    service = AgentTeamService(branch_service=None)
    session = service.create_session(
        root_thread_id="root-1",
        user_id="user-1",
        goal="Create a conservative fallback plan.",
    )

    planned_session, planned = service.plan_session(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
        max_tasks=2,
    )

    assert planned_session.planning_source == "fallback_heuristic"
    assert "Adaptive planning failed" in (planned_session.planning_error or "")
    assert len(planned) == 2
    assert all(task.plan_source == "fallback_heuristic" for task in planned)


def test_agent_team_planning_fields_are_optional_for_old_payloads() -> None:
    session = AgentTeamSession.model_validate(
        {
            "session_id": "session-1",
            "root_thread_id": "root-1",
            "user_id": "user-1",
            "title": "Old",
            "goal": "Old session payload",
            "created_at": "2026-05-05T00:00:00+00:00",
            "updated_at": "2026-05-05T00:00:00+00:00",
        }
    )
    task = AgentTeamTask.model_validate(
        {
            "task_id": "task-1",
            "session_id": "session-1",
            "role": "backend_executor",
            "goal": "Old task payload",
            "created_at": "2026-05-05T00:00:00+00:00",
            "updated_at": "2026-05-05T00:00:00+00:00",
        }
    )

    assert session.planning_source is None
    assert session.plan_hash is None
    assert task.title is None
    assert task.planning_rationale is None
    assert task.sort_order is None
    assert task.task_type is None
    assert task.plan_source is None
