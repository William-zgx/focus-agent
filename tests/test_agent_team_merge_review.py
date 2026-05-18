from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from focus_agent.core.agent_team import (
    AgentTeamArtifactKind,
    AgentTeamMergeReview,
    AgentTeamMergeReviewEvent,
    AgentTeamMergeReviewStatus,
    AgentTeamSession,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)
from focus_agent.repositories.agent_team_repository import (
    AgentTeamRepository,
    InMemoryAgentTeamRepository,
)
from focus_agent.repositories.sqlite_agent_team_repository import SQLiteAgentTeamRepository
from focus_agent.services.agent_team import AgentTeamService
from focus_agent.services.agent_team_workspace import AgentTeamWorkspaceService


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


def _repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    if shutil.which("git") is None:
        pytest.skip("git is required for merge review tests")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "focus-agent@example.test")
    _git(repo, "config", "user.name", "Focus Agent Test")
    (repo / "app.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "app.txt")
    _git(repo, "commit", "-m", "init")
    worktree = tmp_path / "task-worktree"
    _git(repo, "worktree", "add", "-b", "task-branch", str(worktree), "HEAD")
    return repo, worktree


def _session() -> AgentTeamSession:
    return AgentTeamSession(
        session_id="session-1",
        root_thread_id="root-1",
        user_id="user-1",
        title="Merge review",
        goal="Review task changes",
        created_at="2026-05-14T00:00:00+00:00",
        updated_at="2026-05-14T00:00:00+00:00",
    )


def _task(*, workspace_path: str | None = None) -> AgentTeamTask:
    return AgentTeamTask(
        task_id="task-1",
        session_id="session-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Update backend",
        status=AgentTeamTaskStatus.DONE,
        workspace_path=workspace_path,
        changed_files=["app.txt"],
        test_evidence=["pytest tests/test_agent_team_merge_review.py"],
        created_at="2026-05-14T00:01:00+00:00",
        updated_at="2026-05-14T00:01:00+00:00",
    )


def _output(*, fake: bool = False) -> AgentTeamTaskOutput:
    metadata = {"execution_mode": "fake"} if fake else {"passed": True}
    summary = "fake delegated result" if fake else "Updated backend file."
    return AgentTeamTaskOutput(
        output_id="output-1",
        task_id="task-1",
        kind=AgentTeamArtifactKind.PATCH_SUMMARY,
        summary=summary,
        changed_files=["app.txt"],
        test_evidence=["pytest tests/test_agent_team_merge_review.py"],
        metadata=metadata,
        created_at="2026-05-14T00:02:00+00:00",
    )


@pytest.fixture(params=["memory", "sqlite"])
def merge_review_repo_factory(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Callable[[], AgentTeamRepository]:
    if request.param == "memory":
        repo = InMemoryAgentTeamRepository()
        return lambda: repo
    db_path = tmp_path / "agent-team.sqlite3"
    return lambda: SQLiteAgentTeamRepository(str(db_path))


def test_agent_team_merge_review_repository_roundtrip(
    merge_review_repo_factory: Callable[[], AgentTeamRepository],
) -> None:
    repo = merge_review_repo_factory()
    session = _session()
    review = AgentTeamMergeReview(
        review_id="review-1",
        session_id=session.session_id,
        user_id=session.user_id,
        status=AgentTeamMergeReviewStatus.READY,
        selected_task_ids=["task-1"],
        changed_files=["app.txt"],
        metadata={"patch_bytes": 12},
        created_at="2026-05-14T00:03:00+00:00",
        updated_at="2026-05-14T00:03:00+00:00",
    )
    event = AgentTeamMergeReviewEvent(
        event_id="event-1",
        review_id=review.review_id,
        session_id=session.session_id,
        event_type="previewed",
        status=AgentTeamMergeReviewStatus.READY,
        message="ready",
        created_at="2026-05-14T00:04:00+00:00",
    )

    repo.create_session(session)
    repo.save_merge_review(review)
    repo.add_merge_review_event(event)

    assert repo.get_merge_review(review.review_id) == review
    assert repo.list_merge_reviews(session_id=session.session_id) == [review]
    assert repo.list_merge_review_events(review_id=review.review_id) == [event]


def test_agent_team_merge_review_previews_and_applies_worktree_patch(tmp_path: Path) -> None:
    repo_root, worktree = _repo_with_worktree(tmp_path)
    (worktree / "app.txt").write_text("base\nworker change\n", encoding="utf-8")
    service = AgentTeamService(
        branch_service=None,
        workspace_service=AgentTeamWorkspaceService(repo_root=repo_root),
    )
    session = service.create_session(user_id="user-1", goal="Apply worker change")
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="backend_executor",
        goal="Update app",
        create_branch=False,
    )
    service.update_task(
        task_id=task.task_id,
        user_id="user-1",
        status=AgentTeamTaskStatus.DONE,
        workspace_path=str(worktree),
        changed_files=["app.txt"],
        test_evidence=["pytest -q"],
    )
    service.record_task_output(
        task_id=task.task_id,
        user_id="user-1",
        kind=AgentTeamArtifactKind.PATCH_SUMMARY,
        summary="Changed app.txt",
        changed_files=["app.txt"],
        test_evidence=["pytest -q"],
    )

    review = service.create_merge_review(
        session_id=session.session_id,
        user_id="user-1",
        selected_task_ids=[task.task_id],
    )
    preview = service.preview_merge_review(
        session_id=session.session_id,
        review_id=review.review_id,
        user_id="user-1",
    )

    assert preview.status == AgentTeamMergeReviewStatus.READY
    assert preview.changed_files == ["app.txt"]
    assert preview.test_evidence == ["pytest -q"]
    assert preview.metadata["patch_bytes"] > 0

    applied = service.apply_merge_review(
        session_id=session.session_id,
        review_id=review.review_id,
        user_id="user-1",
    )

    assert applied.status == AgentTeamMergeReviewStatus.APPLIED
    assert (repo_root / "app.txt").read_text(encoding="utf-8") == "base\nworker change\n"
    assert [
        event.event_type
        for event in service.list_merge_review_events(
            session_id=session.session_id,
            review_id=review.review_id,
            user_id="user-1",
        )
    ] == ["created", "previewed", "applied"]


def test_agent_team_merge_review_apply_records_conflict(tmp_path: Path) -> None:
    repo_root, worktree = _repo_with_worktree(tmp_path)
    (worktree / "app.txt").write_text("worker change\n", encoding="utf-8")
    (repo_root / "app.txt").write_text("local conflicting change\n", encoding="utf-8")
    service = AgentTeamService(
        branch_service=None,
        workspace_service=AgentTeamWorkspaceService(repo_root=repo_root),
    )
    session = service.create_session(user_id="user-1", goal="Conflict")
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role="backend_executor",
        goal="Update app",
        create_branch=False,
    )
    service.update_task(
        task_id=task.task_id,
        user_id="user-1",
        status=AgentTeamTaskStatus.DONE,
        workspace_path=str(worktree),
    )
    review = service.create_merge_review(
        session_id=session.session_id,
        user_id="user-1",
        selected_task_ids=[task.task_id],
    )

    conflict = service.apply_merge_review(
        session_id=session.session_id,
        review_id=review.review_id,
        user_id="user-1",
    )

    assert conflict.status == AgentTeamMergeReviewStatus.CONFLICT
    assert "app.txt" in conflict.conflict_files
    assert (repo_root / "app.txt").read_text(encoding="utf-8") == "local conflicting change\n"


def test_agent_team_merge_review_marks_fake_output_non_adoptable() -> None:
    repo = InMemoryAgentTeamRepository()
    session = _session()
    task = _task()
    repo.create_session(session)
    repo.create_task(task)
    repo.add_task_output(_output(fake=True))
    service = AgentTeamService(branch_service=None, repository=repo)

    review = service.create_merge_review(
        session_id=session.session_id,
        user_id=session.user_id,
        selected_task_ids=[task.task_id],
    )
    preview = service.preview_merge_review(
        session_id=session.session_id,
        review_id=review.review_id,
        user_id=session.user_id,
    )

    assert preview.status == AgentTeamMergeReviewStatus.ERROR
    assert preview.metadata["non_adoptable_task_ids"] == [task.task_id]
    assert preview.task_summaries[0]["adoptable"] is False


def test_agent_team_merge_review_reject_and_api_flow() -> None:
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from focus_agent.api.deps import get_app_runtime, get_current_principal
        from focus_agent.api.routers.agent_team import router as agent_team_router
        from focus_agent.security.tokens import Principal
    except ImportError as exc:
        pytest.skip(f"API package is not importable in this integration workspace: {exc}")

    from types import SimpleNamespace

    service = AgentTeamService(branch_service=None)
    app = FastAPI()
    app.include_router(agent_team_router)
    runtime = SimpleNamespace(agent_team_service=service)
    app.dependency_overrides[get_app_runtime] = lambda: runtime
    app.dependency_overrides[get_current_principal] = lambda: Principal(user_id="anonymous")
    client = TestClient(app)

    created = client.post("/v1/agent-team/sessions", json={"goal": "API merge review"})
    assert created.status_code == 200
    session_id = created.json()["session"]["session_id"]
    task = client.post(
        f"/v1/agent-team/sessions/{session_id}/tasks",
        json={"role": "backend_executor", "goal": "Task", "create_branch": False},
    )
    assert task.status_code == 200
    task_id = task.json()["task"]["task_id"]
    assert (
        client.patch(f"/v1/agent-team/tasks/{task_id}", json={"status": "done"}).status_code == 200
    )

    review_response = client.post(
        f"/v1/agent-team/sessions/{session_id}/merge-review",
        json={"selected_task_ids": [task_id]},
    )
    assert review_response.status_code == 200
    review_id = review_response.json()["review"]["review_id"]

    listed = client.get(f"/v1/agent-team/sessions/{session_id}/merge-review")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1

    rejected = client.post(
        f"/v1/agent-team/sessions/{session_id}/merge-review/{review_id}/reject",
        json={"rationale": "Needs more tests"},
    )

    assert rejected.status_code == 200
    assert rejected.json()["review"]["status"] == "rejected"
    assert rejected.json()["events"][-1]["event_type"] == "rejected"
