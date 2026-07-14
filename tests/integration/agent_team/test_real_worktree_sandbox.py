"""Integration evidence for Agent Team filesystem isolation.

This suite deliberately uses real ``git worktree`` commands against a temporary
repository. It does not require Docker, a model provider, or repository-local
state.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


@pytest.mark.skipif(
    shutil.which("git") is None, reason="git executable is required for worktree evidence"
)
def test_real_git_worktrees_isolate_uncommitted_agent_changes(tmp_path: Path) -> None:
    """A task worktree must not expose another task's uncommitted changes."""

    repository = tmp_path / "source"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.name", "Agent Team Evidence")
    _git(repository, "config", "user.email", "agent-team-evidence@example.test")
    (repository / "shared.txt").write_text("baseline\n", encoding="utf-8")
    _git(repository, "add", "shared.txt")
    _git(repository, "commit", "-m", "fixture baseline")

    first_worktree = tmp_path / "agent-one"
    second_worktree = tmp_path / "agent-two"
    _git(repository, "worktree", "add", "--detach", str(first_worktree), "HEAD")
    _git(repository, "worktree", "add", "--detach", str(second_worktree), "HEAD")

    try:
        (first_worktree / "shared.txt").write_text("agent one change\n", encoding="utf-8")
        (first_worktree / "agent-one-only.txt").write_text("private\n", encoding="utf-8")

        assert (second_worktree / "shared.txt").read_text(encoding="utf-8") == "baseline\n"
        assert not (second_worktree / "agent-one-only.txt").exists()
        assert (repository / "shared.txt").read_text(encoding="utf-8") == "baseline\n"
        assert not (repository / "agent-one-only.txt").exists()

        first_git_dir = _git(first_worktree, "rev-parse", "--git-dir").strip()
        second_git_dir = _git(second_worktree, "rev-parse", "--git-dir").strip()
        assert first_git_dir != second_git_dir
        assert "agent-one-only.txt" in _git(first_worktree, "status", "--porcelain")
        assert _git(second_worktree, "status", "--porcelain") == ""
        assert _git(repository, "status", "--porcelain") == ""
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(first_worktree)],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(second_worktree)],
            cwd=repository,
            check=False,
            capture_output=True,
            text=True,
        )
