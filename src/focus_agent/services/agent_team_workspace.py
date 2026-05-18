from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from focus_agent.core.agent_team import AgentTeamSession, AgentTeamTask


@dataclass(frozen=True)
class AgentTeamWorkspace:
    workspace_id: str
    workspace_path: str
    workspace_branch: str
    base_commit: str

    def as_metadata(self) -> dict[str, str]:
        return {
            "workspace_id": self.workspace_id,
            "workspace_path": self.workspace_path,
            "workspace_branch": self.workspace_branch,
            "base_commit": self.base_commit,
        }


@dataclass(frozen=True)
class AgentTeamWorkspaceStatus:
    changed_files: list[str]
    diff_summary: str
    workspace_status: str
    porcelain: list[str]

    def as_metadata(self) -> dict[str, Any]:
        return {
            "changed_files": list(self.changed_files),
            "diff_summary": self.diff_summary,
            "workspace_status": self.workspace_status,
            "porcelain": list(self.porcelain),
        }


class AgentTeamWorkspaceService:
    """Create and inspect per-task git worktrees for Agent Team execution."""

    def __init__(self, *, repo_root: str | Path | None = None) -> None:
        self.repo_root = self._resolve_repo_root(repo_root)
        self.worktrees_root = self.repo_root / ".focus_agent" / "worktrees"

    def ensure_workspace(
        self,
        *,
        session: AgentTeamSession,
        task: AgentTeamTask,
    ) -> AgentTeamWorkspace:
        workspace_id = f"{session.session_id}:{task.task_id}"
        workspace_path = self.worktrees_root / session.session_id / task.task_id
        workspace_branch = _workspace_branch_name(session=session, task=task)
        base_commit = self._git("rev-parse", "HEAD").stdout.strip()
        workspace_path.parent.mkdir(parents=True, exist_ok=True)

        if not (workspace_path / ".git").exists():
            branch_exists = bool(
                self._git("branch", "--list", workspace_branch, check=False).stdout.strip()
            )
            if branch_exists:
                self._git("worktree", "add", str(workspace_path), workspace_branch)
            else:
                self._git("worktree", "add", "-b", workspace_branch, str(workspace_path), base_commit)

        return AgentTeamWorkspace(
            workspace_id=workspace_id,
            workspace_path=str(workspace_path),
            workspace_branch=workspace_branch,
            base_commit=base_commit,
        )

    def collect_status(self, workspace_path: str | Path) -> AgentTeamWorkspaceStatus:
        path = Path(workspace_path)
        porcelain_text = self._git("-C", str(path), "status", "--short", "--porcelain").stdout
        porcelain = [line for line in porcelain_text.splitlines() if line.strip()]
        changed_files = _changed_files_from_porcelain(porcelain)
        diff_summary = self._diff_summary(path)
        workspace_status = "dirty" if porcelain else "clean"
        return AgentTeamWorkspaceStatus(
            changed_files=changed_files,
            diff_summary=diff_summary,
            workspace_status=workspace_status,
            porcelain=porcelain,
        )

    def cleanup_workspace(
        self,
        *,
        session_id: str,
        task_id: str | None = None,
        force: bool = False,
        delete_empty_session_dir: bool = True,
    ) -> dict[str, Any]:
        targets = self._cleanup_targets(session_id=session_id, task_id=task_id)
        removed: list[str] = []
        errors: list[str] = []
        for target in targets:
            args = ["worktree", "remove"]
            if force:
                args.append("--force")
            args.append(str(target))
            result = self._git(*args, check=False)
            if result.returncode == 0:
                removed.append(str(target))
            else:
                errors.append(result.stderr.strip() or f"Failed to remove {target}")
        if delete_empty_session_dir:
            session_dir = self.worktrees_root / session_id
            if session_dir.exists():
                try:
                    session_dir.rmdir()
                except OSError:
                    pass
        return {"removed": removed, "errors": errors}

    def _cleanup_targets(self, *, session_id: str, task_id: str | None) -> list[Path]:
        session_dir = self.worktrees_root / session_id
        if task_id:
            target = session_dir / task_id
            return [target] if target.exists() else []
        if not session_dir.exists():
            return []
        return sorted(path for path in session_dir.iterdir() if path.is_dir())

    def _diff_summary(self, workspace_path: Path) -> str:
        diff = self._git("-C", str(workspace_path), "diff", "--stat", "--no-ext-diff").stdout.strip()
        untracked = self._git(
            "-C",
            str(workspace_path),
            "ls-files",
            "--others",
            "--exclude-standard",
        ).stdout.splitlines()
        if not untracked:
            return diff
        untracked_summary = "\n".join(f" {path} | untracked" for path in untracked if path)
        return "\n".join(item for item in (diff, untracked_summary) if item)

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "git command failed"
            raise RuntimeError(message)
        return result

    @staticmethod
    def _resolve_repo_root(repo_root: str | Path | None) -> Path:
        if repo_root is not None:
            return Path(repo_root).expanduser().resolve()
        git = shutil.which("git")
        if git is None:
            return Path.cwd().resolve()
        result = subprocess.run(
            [git, "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).resolve()
        return Path.cwd().resolve()


def _workspace_branch_name(*, session: AgentTeamSession, task: AgentTeamTask) -> str:
    session_short = _slug(session.session_id, fallback="session")[:12]
    task_label = task.title or task.goal or task.task_id
    task_slug = _slug(task_label, fallback="task")[:48]
    task_short = _slug(task.task_id, fallback="task")[:8]
    return f"codex/agent-team/{session_short}/{task_slug}-{task_short}"


def _slug(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-._")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or fallback


def _changed_files_from_porcelain(lines: list[str]) -> list[str]:
    changed: list[str] = []
    for line in lines:
        if not line:
            continue
        path = line[3:] if len(line) > 3 else line
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip()
        if path:
            changed.append(path)
    return list(dict.fromkeys(changed))


__all__ = [
    "AgentTeamWorkspace",
    "AgentTeamWorkspaceService",
    "AgentTeamWorkspaceStatus",
]
