from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from focus_agent.capabilities.sandbox_execution import (
    SandboxExecutionRequest,
)
from focus_agent.services.agent_team_scoped_tools import build_agent_team_scoped_tools


class FakeSandboxRunner:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[SandboxExecutionRequest] = []

    def run(self, request: SandboxExecutionRequest) -> dict[str, object]:
        self.requests.append(request)
        return self.payload


def _git(cwd: Path, *args: str) -> None:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


@pytest.fixture()
def task_worktree(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is required for scoped patch tests")
    root = tmp_path / "task-worktree"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "focus-agent@example.test")
    _git(root, "config", "user.name", "Focus Agent")
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "app.py").write_text("value = 'before'\nneedle = True\n", encoding="utf-8")
    (root / "tests" / "test_app.py").write_text(
        "def test_app():\n    assert True\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# project\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")
    return root


def _tools(
    task_worktree: Path,
    *,
    write_scope: list[str] | None = None,
    sandbox_runner: FakeSandboxRunner | None = None,
    require_docker: bool = False,
    allow_fallback: bool = True,
    allowed_commands: tuple[str, ...] | None = None,
) -> dict[str, object]:
    return build_agent_team_scoped_tools(
        workspace_root=task_worktree,
        write_scope=write_scope or ["src/**"],
        sandbox_runner=sandbox_runner
        or FakeSandboxRunner(
            {
                "status": "completed",
                "exit_code": 0,
                "timed_out": False,
                "sandbox_backend": "docker",
                "fallback_used": False,
                "run_id": "run-default",
            }
        ),
        task_id="task-123",
        require_docker=require_docker,
        allow_fallback=allow_fallback,
        allowed_commands=allowed_commands
        or ("cargo", "go", "make", "mypy", "npm", "pnpm", "pytest", "ruff", "uv"),
    )


def _invoke(tool: object, **arguments: object) -> str:
    return tool.invoke(arguments)


def test_scoped_read_and_search_stay_within_task_worktree(task_worktree: Path) -> None:
    tools = _tools(task_worktree)

    read_payload = json.loads(_invoke(tools["read_file"], path="src/app.py", start_line=2))
    search_payload = json.loads(
        _invoke(tools["search_code"], query="needle", path="src", literal=True)
    )

    assert read_payload["path"] == "src/app.py"
    assert "2 | needle = True" in read_payload["content"]
    assert search_payload["results"] == [
        {"path": "src/app.py", "line_number": 2, "line": "needle = True"}
    ]
    with pytest.raises(ValueError, match="within workspace root"):
        _invoke(tools["read_file"], path="../outside.txt")
    with pytest.raises(ValueError, match="within workspace root"):
        _invoke(tools["search_code"], query="needle", path="../")


def test_scoped_patch_rejects_any_file_outside_write_scope_without_writing(
    task_worktree: Path,
) -> None:
    tools = _tools(task_worktree, write_scope=["src/**"])
    patch = """\
diff --git a/src/app.py b/src/app.py
index 6d73382..8a25b79 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
-value = 'before'
+value = 'after'
 needle = True
diff --git a/tests/test_app.py b/tests/test_app.py
index 0d1d678..1a3bbc4 100644
--- a/tests/test_app.py
+++ b/tests/test_app.py
@@ -1,2 +1,2 @@
 def test_app():
-    assert True
+    assert False
"""

    with pytest.raises(PermissionError, match="outside task write_scope"):
        _invoke(tools["apply_patch"], patch=patch)

    assert (task_worktree / "src" / "app.py").read_text(encoding="utf-8") == (
        "value = 'before'\nneedle = True\n"
    )
    assert (task_worktree / "tests" / "test_app.py").read_text(encoding="utf-8") == (
        "def test_app():\n    assert True\n"
    )


def test_scoped_patch_applies_workspace_relative_file_matching_write_scope(
    task_worktree: Path,
) -> None:
    tools = _tools(task_worktree, write_scope=["src/**"])
    patch = """\
diff --git a/src/app.py b/src/app.py
index 6d73382..8a25b79 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
-value = 'before'
+value = 'after'
 needle = True
"""

    payload = json.loads(_invoke(tools["apply_patch"], patch=patch))

    assert payload["changed_files"] == ["src/app.py"]
    assert payload["write_scope"] == ["src/**"]
    assert (
        (task_worktree / "src" / "app.py").read_text(encoding="utf-8").startswith("value = 'after'")
    )


def test_scoped_command_only_uses_injected_runner_and_returns_evidence(
    task_worktree: Path,
) -> None:
    runner = FakeSandboxRunner(
        {
            "status": "completed",
            "command": ["pytest", "-q"],
            "cwd": ".",
            "exit_code": 0,
            "timed_out": False,
            "stdout": "1 passed\n",
            "stderr": "",
            "sandbox_backend": "docker",
            "sandbox_id": "sandbox-1",
            "run_id": "run-1",
            "fallback_used": False,
        }
    )
    tools = _tools(task_worktree, sandbox_runner=runner, require_docker=True)

    payload = json.loads(
        _invoke(
            tools["run_workspace_command"],
            command=["pytest", "-q"],
            cwd=".",
            timeout_seconds=12,
        )
    )

    assert len(runner.requests) == 1
    request = runner.requests[0]
    assert request.workspace_root == task_worktree.resolve()
    assert request.cwd == "."
    assert request.workspace_mode == "copy_discard"
    assert request.policy["require_docker"] is True
    assert payload["ok"] is True
    assert payload["evidence"] == {
        "kind": "agent_team_sandbox_command",
        "task_id": "task-123",
        "workspace_root": str(task_worktree.resolve()),
        "sandbox_backend": "docker",
        "sandbox_id": "sandbox-1",
        "run_id": "run-1",
        "exit_code": 0,
        "timed_out": False,
        "fallback_used": False,
        "fallback_reason": None,
        "require_docker": True,
        "allow_fallback": True,
        "policy_violations": [],
    }


@pytest.mark.parametrize(
    ("require_docker", "allow_fallback", "payload", "expected_violation"),
    [
        (
            True,
            True,
            {
                "status": "completed",
                "exit_code": 0,
                "timed_out": False,
                "sandbox_backend": "local_subprocess",
                "fallback_used": True,
                "fallback_reason": "docker unavailable",
                "run_id": "local-1",
            },
            "docker sandbox is required",
        ),
        (
            False,
            False,
            {
                "status": "completed",
                "exit_code": 0,
                "timed_out": False,
                "sandbox_backend": "local_subprocess",
                "fallback_used": True,
                "fallback_reason": "docker unavailable",
                "run_id": "local-2",
            },
            "sandbox fallback is not allowed",
        ),
    ],
)
def test_scoped_command_returns_blocked_evidence_for_docker_and_fallback_policy(
    task_worktree: Path,
    require_docker: bool,
    allow_fallback: bool,
    payload: dict[str, object],
    expected_violation: str,
) -> None:
    tools = _tools(
        task_worktree,
        sandbox_runner=FakeSandboxRunner(payload),
        require_docker=require_docker,
        allow_fallback=allow_fallback,
    )

    result = json.loads(_invoke(tools["run_workspace_command"], command=["pytest", "-q"]))

    assert result["status"] == "blocked"
    assert result["ok"] is False
    assert any(expected_violation in item for item in result["evidence"]["policy_violations"])


def test_scoped_command_rejects_cwd_and_argument_paths_outside_task_worktree(
    task_worktree: Path,
) -> None:
    runner = FakeSandboxRunner({})
    tools = _tools(task_worktree, sandbox_runner=runner)

    with pytest.raises(ValueError, match="within workspace root"):
        _invoke(tools["run_workspace_command"], command=["pytest", "../outside"])
    with pytest.raises(ValueError, match="within workspace root"):
        _invoke(tools["run_workspace_command"], command=["pytest"], cwd="../")

    assert runner.requests == []


def test_scoped_command_enforces_configured_allowlist_before_sandbox_execution(
    task_worktree: Path,
) -> None:
    runner = FakeSandboxRunner({})
    tools = _tools(
        task_worktree,
        sandbox_runner=runner,
        allowed_commands=("ruff",),
    )

    with pytest.raises(ValueError, match="not allowlisted"):
        _invoke(tools["run_workspace_command"], command=["python3", "--version"])

    assert runner.requests == []
