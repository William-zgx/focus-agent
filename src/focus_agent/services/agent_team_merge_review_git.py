from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .agent_team_helpers import _dedupe


def repo_root(service: object) -> Path:
    workspace_service = getattr(service, "workspace_service", None)
    repo_root_value = getattr(workspace_service, "repo_root", None)
    if repo_root_value:
        return Path(repo_root_value).expanduser().resolve()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return Path.cwd().resolve()


def git_diff_for_workspace(workspace_path: str | None, base_commit: str | None) -> str:
    if not workspace_path:
        return ""
    return _run_git_workspace(workspace_path, "diff", "--binary", base_commit or "HEAD")


def git_changed_files(workspace_path: str | None, base_commit: str | None) -> list[str]:
    if not workspace_path:
        return []
    output = _run_git_workspace(workspace_path, "diff", "--name-only", base_commit or "HEAD")
    return _dedupe(line.strip() for line in output.splitlines() if line.strip())


def git_diffstat(workspace_path: str | None, base_commit: str | None) -> str:
    if not workspace_path:
        return ""
    return _run_git_workspace(workspace_path, "diff", "--stat", base_commit or "HEAD").strip()


def check_patch(*, target_root: Path, patch: str) -> dict[str, Any]:
    if not patch.strip():
        return {"ok": True, "files": [], "message": None, "returncode": 0}
    result = run_git_apply(target_root=target_root, patch=patch, check_only=True)
    return {
        "ok": result["returncode"] == 0,
        "files": extract_conflict_files(str(result["message"] or "")),
        "message": None if result["returncode"] == 0 else result["message"],
        "returncode": result["returncode"],
    }


def run_git_apply(*, target_root: Path, patch: str, check_only: bool) -> dict[str, Any]:
    args = ["git", "apply"]
    if check_only:
        args.append("--check")
    result = subprocess.run(
        args,
        input=patch,
        cwd=target_root,
        text=True,
        capture_output=True,
        check=False,
    )
    message = (result.stderr or result.stdout or "").strip()
    return {"returncode": result.returncode, "message": message}


def extract_conflict_files(message: str) -> list[str]:
    files: list[str] = []
    for line in message.splitlines():
        text = line.strip()
        if not text.startswith("error:"):
            continue
        for marker in ("patch failed:", "does not exist in index:", "already exists in index:"):
            if marker not in text:
                continue
            value = text.split(marker, 1)[1].strip()
            if ":" in value:
                value = value.split(":", 1)[0].strip()
            if value:
                files.append(value)
    return _dedupe(files)


def _run_git_workspace(workspace_path: str, *args: str) -> str:
    path = Path(workspace_path).expanduser()
    if not path.exists():
        return ""
    result = subprocess.run(
        ["git", *args],
        cwd=path,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


__all__ = [
    "check_patch",
    "extract_conflict_files",
    "git_changed_files",
    "git_diff_for_workspace",
    "git_diffstat",
    "repo_root",
    "run_git_apply",
]
