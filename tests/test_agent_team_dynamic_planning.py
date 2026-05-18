from __future__ import annotations

import pytest

from focus_agent.config import Settings
from focus_agent.core.agent_team import AgentTeamSession, AgentTeamTask, AgentTeamTaskStatus
from focus_agent.services.agent_team import AgentTeamService
from focus_agent.services.agent_team_run_helpers import _allowed_tools_for_task


def _write_skill(
    root,
    *,
    name: str,
    description: str,
    triggers: str = "",
    when_to_use: str = "",
    recommended_tools: str = "",
):
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]
    if triggers:
        lines.append(f"triggers: {triggers}")
    if when_to_use:
        lines.append(f"when_to_use: {when_to_use}")
    if recommended_tools:
        lines.append(f"recommended_tools: {recommended_tools}")
    lines.extend(["---", "", f"# {name}", "", "Follow this skill."])
    (skill_dir / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")


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


def test_agent_team_plan_prefetches_skills_and_injects_allowed_tools(tmp_path) -> None:
    _write_skill(
        tmp_path,
        name="team-support",
        description="Agent team implementation support",
        triggers="team:",
        when_to_use="The user needs agent team implementation support",
        recommended_tools="read_file,git_diff",
    )
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(skill_directories=(str(tmp_path),)),
    )
    session = service.create_session(
        root_thread_id="root-1",
        user_id="user-1",
        goal="team: Implement backend orchestration support.",
    )

    planned_session, tasks = service.plan_session(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
        max_tasks=2,
    )

    assert planned_session.skill_plan["selected_skill_ids"] == ["team-support"]
    assert planned_session.skill_plan["recommended_tools"] == ["read_file", "git_diff"]
    assert all(task.active_skill_ids == ["team-support"] for task in tasks)
    assert all(task.skill_resolution_events for task in tasks)
    assert any(ref.get("skill_id") == "team-support" for ref in tasks[0].context_refs)
    assert "skill:team-support" in tasks[0].capability_requirements
    assert "git_diff" in _allowed_tools_for_task(tasks[0])
    assert "skills_search" in _allowed_tools_for_task(tasks[0])


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


def test_agent_team_adaptive_planning_varies_dag_by_mission_profile() -> None:
    cases = [
        (
            "Research database migration options",
            "research",
            ["coordination", "research", "documentation", "review"],
        ),
        (
            "Debug failing checkout regression",
            "debugging",
            ["diagnosis", "diagnosis", "implementation", "verification"],
        ),
        (
            "Review payment flow changes for risk",
            "review",
            ["coordination", "review", "documentation"],
        ),
        (
            "Implement backend API rate limits",
            "implementation",
            ["coordination", "implementation", "verification", "review"],
        ),
        (
            "Verify release candidate behavior",
            "verification",
            ["coordination", "verification", "review"],
        ),
        (
            "Write operator runbook",
            "writing",
            ["coordination", "research", "documentation", "review"],
        ),
    ]
    observed_shapes: set[tuple[str, ...]] = set()

    for goal, focus, expected_types in cases:
        service = AgentTeamService(branch_service=None)
        session = service.create_session(
            root_thread_id=f"root-{focus}",
            user_id="user-1",
            goal=goal,
        )

        planned_session, tasks = service.plan_session(
            session_id=session.session_id,
            user_id="user-1",
            create_branches=False,
            focus=focus,
        )

        task_types = [task.task_type for task in tasks]
        observed_shapes.add(tuple(task_types))
        assert planned_session.planning_source == "model"
        assert task_types == expected_types
        assert all(task.task_kind for task in tasks)
        assert all(task.input_contract for task in tasks)
        assert all(task.output_contract for task in tasks)
        assert all(task.replan_policy for task in tasks)

    assert len(observed_shapes) >= 5


def test_agent_team_fallback_planning_uses_profile_specific_debug_dag(
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
        goal="Debug failing checkout regression.",
    )

    planned_session, tasks = service.plan_session(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
        focus="debugging",
    )

    assert planned_session.planning_source == "fallback_heuristic"
    assert [task.task_type for task in tasks] == [
        "diagnosis",
        "implementation",
        "verification",
    ]
    assert [task.role.value for task in tasks] == [
        "verifier",
        "backend_executor",
        "verifier",
    ]
    assert tasks[1].dependencies == [tasks[0].task_id]
    assert tasks[2].dependencies == [tasks[1].task_id]
    assert tasks[1].risk_level == "high"
    assert "root cause differs" in " ".join(tasks[1].replan_policy.get("replan_when", []))
    assert tasks[1].write_scope == ["src/**", "tests/**"]


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


def test_agent_team_planning_compiles_dag_from_deliverable_contracts_and_evidence() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(
        root_thread_id="root-contracts",
        user_id="user-1",
        goal="Implement backend API rate limits with focused tests.",
    )

    planned_session, tasks = service.plan_session(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
    )

    assert planned_session.planning_source == "model"
    assert [task.task_type for task in tasks] == [
        "coordination",
        "implementation",
        "verification",
        "review",
    ]
    assert [task.title for task in tasks] != ["Plan", "Execute", "Verify"]
    assert tasks[1].dependencies == [tasks[0].task_id]
    assert tasks[2].dependencies == [tasks[1].task_id]
    assert tasks[3].dependencies == [tasks[2].task_id]
    assert "implementation contract" in tasks[1].input_contract["requires"]
    assert "patch summary" in tasks[1].output_contract["produces"]
    assert "changed files" in tasks[1].evidence_required
    assert tasks[1].write_scope == ["src/**", "tests/**"]
    assert "patch summary" in tasks[2].input_contract["requires"]
    assert "test command and result" in tasks[2].evidence_required


def test_agent_team_research_and_implementation_have_distinct_deliverable_dags() -> None:
    service = AgentTeamService(branch_service=None)
    research_session = service.create_session(
        root_thread_id="root-research-contracts",
        user_id="user-1",
        goal="Research database migration options and compare risks.",
    )
    implementation_session = service.create_session(
        root_thread_id="root-implementation-contracts",
        user_id="user-1",
        goal="Implement backend database migration API.",
    )

    _, research_tasks = service.plan_session(
        session_id=research_session.session_id,
        user_id="user-1",
        create_branches=False,
        focus="research",
    )
    _, implementation_tasks = service.plan_session(
        session_id=implementation_session.session_id,
        user_id="user-1",
        create_branches=False,
        focus="implementation",
    )

    assert [task.task_type for task in research_tasks] != [
        task.task_type for task in implementation_tasks
    ]
    assert "research findings" in research_tasks[2].input_contract["requires"]
    assert "source notes" in research_tasks[1].evidence_required
    assert "patch summary" not in research_tasks[1].output_contract["produces"]
    assert "patch summary" in implementation_tasks[1].output_contract["produces"]
    assert "test command and result" in implementation_tasks[2].evidence_required


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
    assert task.task_kind is None
    assert task.input_contract is None
    assert task.output_contract is None
    assert task.evidence_required == []
    assert task.capability_requirements == []
    assert task.risk_level is None
    assert task.write_scope == []
    assert task.replan_policy is None
    assert task.plan_source is None
