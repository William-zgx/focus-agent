from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace

import pytest

from focus_agent.agent_roles import AgentRole
from focus_agent.config import Settings
from focus_agent.core.agent_team import (
    AgentTeamMergeBundle,
    AgentTeamSessionStatus,
    AgentTeamTask,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
    agent_role_for_team_task_role,
)
from focus_agent.core.branching import BranchRole
from focus_agent.repositories.sqlite_agent_team_repository import SQLiteAgentTeamRepository
from focus_agent.services.agent_team import AgentTeamService
from focus_agent.services.agent_team_workspace import AgentTeamWorkspaceService


class FakeBranchService:
    def __init__(self) -> None:
        self.calls = []

    def fork_branch(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(branch_id="branch-1", child_thread_id="child-1")


class CleanupRecordingWorkspaceService:
    def __init__(self) -> None:
        self.cleanup_calls: list[dict[str, object]] = []

    def cleanup_workspace(self, **kwargs: object) -> dict[str, object]:
        self.cleanup_calls.append(kwargs)
        return {"removed": [], "errors": [], "pruned": True}


def _git(cwd, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_agent_team_service_creates_standalone_session_without_root_thread() -> None:
    service = AgentTeamService(branch_service=None)

    session = service.create_session(user_id="user-1", goal="Run standalone mission")

    assert session.root_thread_id.startswith("agent-team-standalone-")
    assert session.goal == "Run standalone mission"
    assert (
        service.get_session(session.session_id, user_id="user-1").root_thread_id
        == session.root_thread_id
    )

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


def test_agent_team_task_role_mapping_matches_governance_roles() -> None:
    assert agent_role_for_team_task_role(AgentTeamTaskRole.PLANNER) == AgentRole.PLANNER
    assert agent_role_for_team_task_role(AgentTeamTaskRole.ARCHITECT) == AgentRole.ORCHESTRATOR
    assert agent_role_for_team_task_role(AgentTeamTaskRole.BACKEND_EXECUTOR) == AgentRole.EXECUTOR
    assert agent_role_for_team_task_role(AgentTeamTaskRole.FRONTEND_EXECUTOR) == AgentRole.EXECUTOR
    assert agent_role_for_team_task_role(AgentTeamTaskRole.TEST_ENGINEER) == AgentRole.CRITIC
    assert agent_role_for_team_task_role(AgentTeamTaskRole.REVIEWER) == AgentRole.CRITIC
    assert agent_role_for_team_task_role(AgentTeamTaskRole.VERIFIER) == AgentRole.CRITIC
    assert agent_role_for_team_task_role(AgentTeamTaskRole.WRITER) == AgentRole.EXECUTOR
    assert agent_role_for_team_task_role("backend_executor") == AgentRole.EXECUTOR


def test_agent_team_task_execution_links_are_optional_for_old_payloads() -> None:
    task = AgentTeamTask.model_validate(
        {
            "task_id": "task-1",
            "session_id": "session-1",
            "role": "backend_executor",
            "goal": "Old task payload",
            "created_at": "2026-04-28T00:00:00+00:00",
            "updated_at": "2026-04-28T00:00:00+00:00",
        }
    )

    assert task.agent_run_id is None
    assert task.delegated_task_id is None
    assert task.artifact_ids == []
    assert task.execution_status is None
    assert task.workspace_id is None
    assert task.workspace_branch is None
    assert task.workspace_path is None
    assert task.base_commit is None
    assert task.diff_summary is None
    assert task.test_evidence == []
    assert task.workspace_status is None
    assert task.acceptance_criteria == []
    assert task.context_refs == []
    assert task.run_status is None
    assert task.started_at is None
    assert task.finished_at is None
    assert task.last_error is None


def test_agent_team_workspace_service_creates_worktree_and_collects_status(tmp_path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is required for worktree metadata collection")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "focus-agent@example.test")
    _git(repo, "config", "user.name", "Focus Agent Test")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")

    service = AgentTeamService(
        branch_service=None,
        workspace_service=AgentTeamWorkspaceService(repo_root=repo),
    )
    session = service.create_session(user_id="user-1", goal="Isolated worktree")
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="backend_executor",
        title="Write metadata",
        goal="Write metadata",
        create_branch=False,
    )

    workspace = service.workspace_service.ensure_workspace(session=session, task=task)
    assert workspace.workspace_path.endswith(
        f".focus_agent/worktrees/{session.session_id}/{task.task_id}"
    )
    assert workspace.workspace_branch.startswith(f"codex/agent-team/{session.session_id[:12]}/")
    assert workspace.base_commit

    workspace_path = repo / ".focus_agent" / "worktrees" / session.session_id / task.task_id
    (workspace_path / "agent-team.txt").write_text("changed\n")
    status = service.workspace_service.collect_status(workspace.workspace_path)

    assert status.workspace_status == "dirty"
    assert status.changed_files == ["agent-team.txt"]
    assert "agent-team.txt" in status.diff_summary


def test_agent_team_workspace_cleanup_removes_orphan_directory_and_prunes(tmp_path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is required for worktree metadata collection")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "focus-agent@example.test")
    _git(repo, "config", "user.name", "Focus Agent Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")

    service = AgentTeamWorkspaceService(repo_root=repo)
    orphan = repo / ".focus_agent" / "worktrees" / "session-1" / "task-1"
    orphan.mkdir(parents=True)
    (orphan / "stale.txt").write_text("stale\n", encoding="utf-8")

    result = service.cleanup_workspace(session_id="session-1", force=True)

    assert orphan.exists() is False
    assert str(orphan) in result["removed"]
    assert result["pruned"] is True
    assert result["errors"] == []


def test_agent_team_service_lists_sessions_with_filters() -> None:
    service = AgentTeamService(branch_service=None)
    first = service.create_session(root_thread_id="root-1", user_id="user-1", goal="First")
    second = service.create_session(root_thread_id="root-2", user_id="user-1", goal="Second")
    other_user = service.create_session(root_thread_id="root-1", user_id="user-2", goal="Other")
    service.dispatch_default_tasks(
        session_id=second.session_id,
        user_id="user-1",
        create_branches=False,
    )

    assert [item.session_id for item in service.list_sessions(user_id="user-1", limit=1)] == [
        second.session_id
    ]
    assert [
        item.session_id for item in service.list_sessions(user_id="user-1", root_thread_id="root-1")
    ] == [first.session_id]
    assert [
        item.session_id for item in service.list_sessions(user_id="user-1", status="running")
    ] == [second.session_id]
    assert [item.session_id for item in service.list_sessions(user_id="user-1", offset=1)] == [
        first.session_id
    ]
    assert other_user.session_id not in [
        item.session_id for item in service.list_sessions(user_id="user-1")
    ]


def test_agent_team_service_plan_session_is_idempotent_and_writes_dag_fields() -> None:
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(
            agent_delegation_enabled=True,
            agent_role_routing_enabled=True,
            agent_delegation_execution_mode="fake",
            agent_team_skill_scout_enabled=False,
        ),
    )
    session = service.create_session(
        root_thread_id="root-1",
        user_id="user-1",
        goal="Plan, implement, and test backend orchestration.",
    )

    _, planned = service.plan_session(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
    )
    _, repeated = service.plan_session(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
    )

    assert [task.task_id for task in repeated] == [task.task_id for task in planned]
    assert len(planned) >= 2
    assert planned[0].role == AgentTeamTaskRole.ARCHITECT
    assert planned[1].dependencies == [planned[0].task_id]
    assert planned[1].acceptance_criteria
    assert planned[1].context_refs == []


def test_agent_team_service_plan_session_injects_selected_skill_context(tmp_path) -> None:
    skill_dir = tmp_path / "agent-tools"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: agent-tools",
                "description: Agent tool and skill discovery workflow",
                "triggers: agent-tools:",
                "when_to_use: The team needs to discover agent skills and common tools",
                "recommended_tools: skills_search,skill_view,search_code",
                "capability_requirements: skill-discovery",
                "prompt_mode: explore",
                "---",
                "",
                "# Agent Tools",
                "",
                "Search configured skill sources before implementation.",
            ]
        ),
        encoding="utf-8",
    )
    service = AgentTeamService(
        branch_service=None,
        settings=Settings(
            skill_directories=(str(tmp_path),),
            skill_semantic_match_enabled=False,
            agent_team_skill_scout_enabled=True,
        ),
    )
    session = service.create_session(
        root_thread_id="root-1",
        user_id="user-1",
        goal="agent-tools: Add autonomous skill discovery to AgentTeam planning.",
    )

    planned_session, planned = service.plan_session(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
    )

    assert planned_session.skill_plan["selected_skill_ids"] == ["agent-tools"]
    assert planned
    assert planned[0].active_skill_ids == ["agent-tools"]
    assert "skills_search" in planned[0].scope
    assert "skill:agent-tools" in planned[0].capability_requirements
    assert any(ref.get("type") == "skill" for ref in planned[0].context_refs)


def test_agent_team_service_run_ready_tasks_records_execution_evidence() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(root_thread_id="root-1", user_id="user-1", goal="Run tasks")
    first = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="backend_executor",
        goal="Implement backend",
        acceptance_criteria=["Backend fake run records artifacts."],
        context_refs=[{"kind": "thread", "id": "root-1"}],
        create_branch=False,
    )
    second = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="test_engineer",
        goal="Verify backend",
        dependencies=[first.task_id],
        create_branch=False,
    )

    _, after_first_run = service.run_ready_tasks(session_id=session.session_id, user_id="user-1")
    by_id = {task.task_id: task for task in after_first_run}

    assert by_id[first.task_id].status == AgentTeamTaskStatus.DONE
    assert by_id[first.task_id].run_status == "completed"
    assert by_id[first.task_id].agent_run_id == f"run-{first.task_id}"
    assert by_id[first.task_id].delegated_task_id == first.task_id
    assert by_id[first.task_id].artifact_ids == [f"artifact-{first.task_id}-fake-result"]
    assert by_id[first.task_id].execution_status == "completed"
    assert by_id[first.task_id].started_at is not None
    assert by_id[first.task_id].finished_at is not None
    assert by_id[first.task_id].last_error == ""
    assert by_id[second.task_id].status == AgentTeamTaskStatus.DONE

    outputs = service.list_task_outputs(task_id=first.task_id, user_id="user-1")
    assert outputs[0].metadata["execution"]["agent_run_id"] == f"run-{first.task_id}"
    context_refs = outputs[0].metadata["artifacts"][0]["payload"]["context_refs"]
    assert {"kind": "thread", "id": "root-1"} in context_refs
    assert any(item.get("type") == "agent_team_session" for item in context_refs)
    assert any(item.get("type") == "agent_team_task_contract" for item in context_refs)
    assert any(item.get("type") == "agent_team_dependency_outputs" for item in context_refs)
    assert outputs[0].test_evidence == [f"delegated fake run run-{first.task_id}: completed"]

    second_outputs = service.list_task_outputs(task_id=second.task_id, user_id="user-1")
    assert second_outputs[0].metadata["scheduler"]["wave"] == 2


def test_agent_team_service_run_task_skips_unfinished_dependencies() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(root_thread_id="root-1", user_id="user-1", goal="Run tasks")
    dependency = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="backend_executor",
        goal="Implement backend",
        create_branch=False,
    )
    blocked = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="test_engineer",
        goal="Verify backend",
        dependencies=[dependency.task_id],
        create_branch=False,
    )

    result = service.run_task(task_id=blocked.task_id, user_id="user-1")

    assert result.status == AgentTeamTaskStatus.PENDING
    assert service.list_task_outputs(task_id=blocked.task_id, user_id="user-1") == []


def test_agent_team_merge_bundle_includes_execution_evidence() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(root_thread_id="root-1", user_id="user-1", goal="Build MVP")
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="backend_executor",
        goal="Implement backend",
        create_branch=False,
    )

    service.update_task(
        task_id=task.task_id,
        user_id="user-1",
        status=AgentTeamTaskStatus.DONE,
        agent_run_id="run-1",
        delegated_task_id="delegated-task-1",
        artifact_ids=["execution-artifact-1"],
        execution_status="completed",
    )
    service.record_task_output(
        task_id=task.task_id,
        user_id="user-1",
        artifact_id="output-artifact-1",
        summary="Backend execution completed with artifacts.",
        metadata={
            "execution": {
                "agent_run_id": "run-1",
                "delegated_task_id": "delegated-task-1",
                "artifact_ids": ["execution-artifact-1"],
                "execution_status": "completed",
            }
        },
    )

    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert bundle.recommended_next_action == "request_changes"
    assert any("Missing review/verification evidence" in item for item in bundle.risk_items)
    assert bundle.execution_evidence == [
        {
            "task_id": task.task_id,
            "role": "backend_executor",
            "agent_run_id": "run-1",
            "delegated_task_id": "delegated-task-1",
            "artifact_ids": ["execution-artifact-1"],
            "execution_status": "completed",
        }
    ]


def test_agent_team_merge_bundle_treats_queued_tasks_as_pending() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(root_thread_id="root-1", user_id="user-1", goal="Build MVP")
    done_task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="backend_executor",
        goal="Implement backend",
        create_branch=False,
    )
    queued_task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="test_engineer",
        goal="Verify backend",
        create_branch=False,
    )
    service.update_task(
        task_id=done_task.task_id,
        user_id="user-1",
        status=AgentTeamTaskStatus.DONE,
    )
    service.update_task(
        task_id=queued_task.task_id,
        user_id="user-1",
        status=AgentTeamTaskStatus.QUEUED,
    )
    service.record_task_output(
        task_id=done_task.task_id,
        user_id="user-1",
        summary="Backend execution completed.",
    )

    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert bundle.recommended_next_action == "request_changes"
    assert any("Pending test_engineer" in item for item in bundle.open_questions)


def test_merge_bundle_requests_changes_when_required_task_evidence_is_missing() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(user_id="user-1", goal="Deliver evidence-gated output")
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.WRITER,
        title="Write final answer",
        goal="Write final answer",
        evidence_required=["benchmark table"],
        create_branch=False,
    )
    service.record_task_output(
        task_id=task.task_id,
        user_id="user-1",
        summary="Final answer drafted without the required source comparison.",
    )
    service.update_task(
        task_id=task.task_id,
        user_id="user-1",
        status=AgentTeamTaskStatus.DONE,
    )

    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert bundle.recommended_next_action == "request_changes"
    assert any("benchmark table" in item for item in bundle.risk_items)
    assert any("Missing required evidence" in item for item in bundle.final_answer_warnings)

    service = AgentTeamService(branch_service=None)
    session = service.create_session(
        root_thread_id="root-1", user_id="user-1", goal="Verify mission"
    )
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="test_engineer",
        goal="Run verification",
        create_branch=False,
    )

    first_bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")
    assert any(item.startswith("Pending test_engineer:") for item in first_bundle.open_questions)

    service.update_task(
        task_id=task.task_id,
        user_id="user-1",
        status=AgentTeamTaskStatus.DONE,
        verification_summary="Verification completed.",
    )
    service.record_task_output(
        task_id=task.task_id,
        user_id="user-1",
        kind="test_report",
        summary="Verification completed.",
        test_evidence=["pytest tests/test_agent_team_service.py"],
    )

    second_bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert second_bundle.open_questions == []
    assert not any("Pending test_engineer:" in item for item in second_bundle.risk_items)

    service = AgentTeamService(branch_service=None)
    session = service.create_session(
        root_thread_id="root-1",
        user_id="user-1",
        goal="Generate a production onboarding checklist",
    )
    service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="backend_executor",
        goal="Draft checklist",
        create_branch=False,
    )

    service.run_ready_tasks(session_id=session.session_id, user_id="user-1")
    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert bundle.final_answer_status == "placeholder"
    assert "模拟执行" in (bundle.final_answer or "")
    assert "没有生成可交付的真实答案" in (bundle.final_answer or "")
    assert bundle.recommended_next_action == "request_changes"
    assert bundle.source_output_ids


def test_agent_team_merge_bundle_fixture_output_builds_ready_final_answer() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(
        root_thread_id="root-1",
        user_id="user-1",
        goal="Build MVP ledger final answer",
    )
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="backend_executor",
        goal="Implement ledger",
        create_branch=False,
    )
    service.record_task_output(
        task_id=task.task_id,
        user_id="user-1",
        summary="Ledger backend is implemented for the MVP ledger goal.",
        metadata={
            "artifacts": [
                {
                    "payload": {
                        "raw_text": "Raw ledger delivery text.",
                        "parsed": {"final_answer": "Parsed MVP ledger delivery."},
                    }
                }
            ]
        },
    )
    service.update_task(task_id=task.task_id, user_id="user-1", status=AgentTeamTaskStatus.DONE)

    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert bundle.final_answer_status == "ready"
    assert "Build MVP ledger final answer" in (bundle.final_answer or "")
    assert "Raw ledger delivery text." in (bundle.final_answer or "")
    assert "Parsed MVP ledger delivery." in (bundle.final_answer or "")


def test_agent_team_merge_bundle_without_executor_output_blocks_final_answer() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(
        root_thread_id="root-1",
        user_id="user-1",
        goal="Ship release notes",
    )
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="test_engineer",
        goal="Verify release notes",
        create_branch=False,
    )
    service.record_task_output(
        task_id=task.task_id,
        user_id="user-1",
        kind="test_report",
        summary="Release notes verification passed.",
    )
    service.update_task(task_id=task.task_id, user_id="user-1", status=AgentTeamTaskStatus.DONE)

    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert bundle.final_answer_status == "blocked"
    assert "缺少执行/撰写任务产出" in (bundle.final_answer or "")
    assert any(
        "Missing executor or writer output" in warning for warning in bundle.final_answer_warnings
    )


def test_agent_team_merge_bundle_old_payload_fields_remain_compatible() -> None:
    bundle = AgentTeamMergeBundle.model_validate(
        {
            "session_id": "session-1",
            "summary": "Old merge summary",
            "accepted_tasks": ["task-1"],
            "key_findings": ["Backend finished"],
            "test_evidence": ["pytest tests/test_agent_team_service.py"],
            "risk_items": [],
            "recommended_next_action": "merge",
        }
    )

    assert bundle.summary == "Old merge summary"
    assert bundle.key_findings == ["Backend finished"]
    assert bundle.test_evidence == ["pytest tests/test_agent_team_service.py"]
    assert bundle.risk_items == []
    assert bundle.recommended_next_action == "merge"
    assert bundle.final_answer is None
    assert bundle.final_answer_status is None
    assert bundle.final_answer_warnings == []
    assert bundle.source_output_ids == []


def test_agent_team_service_records_outputs_and_prepares_merge_bundle() -> None:
    workspace_service = CleanupRecordingWorkspaceService()
    service = AgentTeamService(branch_service=None, workspace_service=workspace_service)  # type: ignore[arg-type]
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
    assert workspace_service.cleanup_calls == [
        {"session_id": session.session_id, "force": True}
    ]


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
    first.update_task(
        task_id=task.task_id,
        user_id="user-1",
        agent_run_id="run-1",
        delegated_task_id="delegated-task-1",
        artifact_ids=["execution-artifact-1"],
        execution_status="completed",
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

    assert [item.session_id for item in second.list_sessions(user_id="user-1")] == [
        session.session_id
    ]
    restored_session = second.get_session(session.session_id, user_id="user-1")
    assert restored_session.status == "completed"
    assert restored_session.latest_merge_bundle is not None
    assert restored_session.latest_merge_bundle["changed_files"] == [
        "src/focus_agent/repositories/sqlite_agent_team_repository.py"
    ]
    assert restored_session.merge_decision is not None
    assert restored_session.merge_decision["accepted_tasks"] == [task.task_id]
    restored_task = second.list_tasks(session_id=session.session_id, user_id="user-1")[0]
    assert restored_task.task_id == task.task_id
    assert restored_task.agent_run_id == "run-1"
    assert restored_task.delegated_task_id == "delegated-task-1"
    assert restored_task.artifact_ids == ["execution-artifact-1"]
    assert restored_task.execution_status == "completed"
    assert restored_session.latest_merge_bundle["execution_evidence"] == [
        {
            "task_id": task.task_id,
            "role": "backend_executor",
            "agent_run_id": "run-1",
            "delegated_task_id": "delegated-task-1",
            "artifact_ids": ["execution-artifact-1"],
            "execution_status": "completed",
        }
    ]
    outputs = second.list_task_outputs(task_id=task.task_id, user_id="user-1")
    assert outputs[0].summary == "Persistence survives service recreation."
    assert outputs[0].metadata == {"source": "unit-test"}


def test_agent_team_service_persists_default_dispatch_bundle_across_instances(tmp_path) -> None:
    db_path = tmp_path / "agent-team.sqlite3"
    first = AgentTeamService(
        branch_service=None,
        repository=SQLiteAgentTeamRepository(str(db_path)),
    )
    session = first.create_session(
        root_thread_id="root-1", user_id="user-1", goal="Persist dispatch bundle"
    )

    dispatched_session, tasks = first.dispatch_default_tasks(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
    )
    bundle = first.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert dispatched_session.status == AgentTeamSessionStatus.RUNNING
    assert len(tasks) == 6
    assert bundle.session_id == session.session_id
    assert bundle.recommended_next_action == "request_changes"

    second = AgentTeamService(
        branch_service=None,
        repository=SQLiteAgentTeamRepository(str(db_path)),
    )

    restored_session = second.get_session(session.session_id, user_id="user-1")
    assert restored_session.status == AgentTeamSessionStatus.AWAITING_REVIEW
    assert restored_session.latest_merge_bundle is not None
    assert restored_session.latest_merge_bundle["session_id"] == session.session_id
    assert restored_session.latest_merge_bundle["recommended_next_action"] == "request_changes"

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
    session = service.create_session(
        root_thread_id="root-1", user_id="user-1", goal="Ship Agent Team Workbench"
    )

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


def test_agent_team_service_runs_legacy_primed_default_planner() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(
        root_thread_id="root-1", user_id="user-1", goal="Run default mission plan"
    )
    _, tasks = service.dispatch_default_tasks(
        session_id=session.session_id,
        user_id="user-1",
        create_branches=False,
    )

    _, after_run = service.run_ready_tasks(session_id=session.session_id, user_id="user-1")
    by_id = {task.task_id: task for task in after_run}

    assert tasks[0].status == AgentTeamTaskStatus.RUNNING
    assert by_id[tasks[0].task_id].status == AgentTeamTaskStatus.DONE
    assert by_id[tasks[0].task_id].run_status == "completed"
    assert all(task.status == AgentTeamTaskStatus.DONE for task in by_id.values())


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
