from __future__ import annotations

from types import SimpleNamespace

from focus_agent.core.agent_team import AgentTeamSessionStatus, AgentTeamTaskRole, AgentTeamTaskStatus
from focus_agent.core.branching import BranchRole
from focus_agent.repositories.sqlite_agent_team_repository import SQLiteAgentTeamRepository
from focus_agent.services.agent_team import AgentTeamService


class FakeBranchService:
    def __init__(self) -> None:
        self.calls = []

    def fork_branch(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(branch_id="branch-1", child_thread_id="child-1")


def test_agent_team_service_creates_task_branch_with_role_mapping() -> None:
    branch_service = FakeBranchService()
    service = AgentTeamService(branch_service=branch_service)  # type: ignore[arg-type]
    session = service.create_session(
        root_thread_id="root-1",
        user_id="user-1",
        title="Workbench",
        goal="Build MVP",
    )

    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Implement backend",
        scope=["src/focus_agent/services/agent_team.py"],
    )

    assert task.branch_id == "branch-1"
    assert task.child_thread_id == "child-1"
    assert branch_service.calls[0]["parent_thread_id"] == "root-1"
    assert branch_service.calls[0]["branch_role"] == BranchRole.EXECUTE
    assert service.get_session(session.session_id, user_id="user-1").status == "running"


def test_agent_team_service_records_outputs_and_prepares_merge_bundle() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(root_thread_id="root-1", user_id="user-1", goal="Build MVP")
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="test_engineer",
        goal="Verify backend",
        create_branch=False,
    )

    service.record_task_output(
        task_id=task.task_id,
        user_id="user-1",
        kind="test_report",
        artifact_id="artifact-1",
        summary="Backend service tests cover the MVP ledger flow.",
        changed_files=["tests/test_agent_team_service.py"],
        test_evidence=["pytest tests/test_agent_team_service.py"],
    )
    service.update_task(task_id=task.task_id, user_id="user-1", status=AgentTeamTaskStatus.DONE)

    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")
    assert bundle.accepted_tasks == [task.task_id]
    assert bundle.recommended_next_action == "merge"
    assert bundle.changed_files == ["tests/test_agent_team_service.py"]
    assert bundle.test_evidence == ["pytest tests/test_agent_team_service.py"]

    decision = service.apply_merge_decision(
        session_id=session.session_id,
        user_id="user-1",
        approved=True,
        rationale="Looks good",
    )
    assert decision.accepted_tasks == [task.task_id]
    assert service.get_session(session.session_id, user_id="user-1").status == "completed"


def test_agent_team_service_persists_workbench_state_across_instances(tmp_path) -> None:
    db_path = tmp_path / "agent-team.sqlite3"
    first = AgentTeamService(
        branch_service=None,
        repository=SQLiteAgentTeamRepository(str(db_path)),
    )
    session = first.create_session(root_thread_id="root-1", user_id="user-1", goal="Build MVP")
    task = first.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="backend_executor",
        goal="Persist backend state",
        create_branch=False,
    )
    first.record_task_output(
        task_id=task.task_id,
        user_id="user-1",
        artifact_id="artifact-1",
        summary="Persistence survives service recreation.",
        changed_files=["src/focus_agent/repositories/sqlite_agent_team_repository.py"],
        test_evidence=["pytest tests/test_agent_team_service.py"],
        risk_notes=["local fallback only"],
        metadata={"source": "unit-test"},
    )
    first.update_task(task_id=task.task_id, user_id="user-1", status=AgentTeamTaskStatus.DONE)
    bundle = first.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")
    first.apply_merge_decision(
        session_id=session.session_id,
        user_id="user-1",
        approved=True,
        action="merge",
        accepted_tasks=bundle.accepted_tasks,
    )

    second = AgentTeamService(
        branch_service=None,
        repository=SQLiteAgentTeamRepository(str(db_path)),
    )

    assert [item.session_id for item in second.list_sessions(user_id="user-1")] == [session.session_id]
    restored_session = second.get_session(session.session_id, user_id="user-1")
    assert restored_session.status == "completed"
    assert restored_session.latest_merge_bundle is not None
    assert restored_session.latest_merge_bundle["changed_files"] == [
        "src/focus_agent/repositories/sqlite_agent_team_repository.py"
    ]
    assert restored_session.merge_decision is not None
    assert restored_session.merge_decision["accepted_tasks"] == [task.task_id]
    assert second.list_tasks(session_id=session.session_id, user_id="user-1")[0].task_id == task.task_id
    outputs = second.list_task_outputs(task_id=task.task_id, user_id="user-1")
    assert outputs[0].summary == "Persistence survives service recreation."
    assert outputs[0].metadata == {"source": "unit-test"}


def test_agent_team_service_persists_default_dispatch_bundle_across_instances(tmp_path) -> None:
    db_path = tmp_path / "agent-team.sqlite3"
    first = AgentTeamService(
        branch_service=None,
        repository=SQLiteAgentTeamRepository(str(db_path)),
    )
    session = first.create_session(root_thread_id="root-1", user_id="user-1", goal="Persist dispatch bundle")

    dispatched_session, tasks = first.dispatch_default_tasks(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
    )
    bundle = first.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert dispatched_session.status == AgentTeamSessionStatus.RUNNING
    assert len(tasks) == 6
    assert bundle.session_id == session.session_id
    assert bundle.recommended_next_action == "split_followup"

    second = AgentTeamService(
        branch_service=None,
        repository=SQLiteAgentTeamRepository(str(db_path)),
    )

    restored_session = second.get_session(session.session_id, user_id="user-1")
    assert restored_session.status == AgentTeamSessionStatus.AWAITING_REVIEW
    assert restored_session.latest_merge_bundle is not None
    assert restored_session.latest_merge_bundle["session_id"] == session.session_id
    assert restored_session.latest_merge_bundle["recommended_next_action"] == "split_followup"

    restored_tasks = second.list_tasks(session_id=session.session_id, user_id="user-1")
    assert [task.role.value for task in restored_tasks] == [
        "planner",
        "backend_executor",
        "frontend_executor",
        "test_engineer",
        "reviewer",
        "verifier",
    ]
    assert restored_tasks[0].status == AgentTeamTaskStatus.RUNNING
    assert all(task.status == AgentTeamTaskStatus.PENDING for task in restored_tasks[1:])


def test_agent_team_service_dispatches_default_task_set_without_recursive_agents() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(root_thread_id="root-1", user_id="user-1", goal="Ship Agent Team Workbench")

    dispatched_session, tasks = service.dispatch_default_tasks(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
    )

    roles = [task.role.value for task in tasks]
    assert roles == [
        "planner",
        "backend_executor",
        "frontend_executor",
        "test_engineer",
        "reviewer",
        "verifier",
    ]
    assert dispatched_session.status == "running"
    assert tasks[0].status == "running"
    assert all(task.status == "pending" for task in tasks[1:])
    assert all(task.branch_id is None and task.child_thread_id is None for task in tasks)
    assert tasks[1].dependencies == [tasks[0].task_id]
    assert tasks[2].dependencies == [tasks[0].task_id]
    assert tasks[3].dependencies == [tasks[1].task_id, tasks[2].task_id]

    _, repeated_tasks = service.dispatch_default_tasks(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
    )
    assert [task.task_id for task in repeated_tasks] == [task.task_id for task in tasks]


def test_agent_team_merge_bundle_keeps_open_questions_compact() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(
        root_thread_id="root-1",
        user_id="user-1",
        goal="上线前复核刷新后的 Agent Team 页面是否能继续保留协作汇总、风险和证据。",
    )

    _, tasks = service.dispatch_default_tasks(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
    )
    blocked_task = tasks[0]
    running_task = tasks[1]
    service.update_task(
        task_id=blocked_task.task_id,
        user_id="user-1",
        status=AgentTeamTaskStatus.BLOCKED,
    )
    service.update_task(
        task_id=running_task.task_id,
        user_id="user-1",
        status=AgentTeamTaskStatus.RUNNING,
    )

    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert bundle.recommended_next_action == "request_changes"
    assert bundle.open_questions
    assert all("Session goal:" not in question for question in bundle.open_questions)
    assert all(len(question) <= 170 for question in bundle.open_questions)
