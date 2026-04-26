from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, Callable

from langchain.tools import tool

from .common import _coerce_relative_posix
from .workspace import _resolve_workspace_path


def _run_git_command(*, workspace_root: Path, args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=workspace_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("git is not installed.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git command timed out: {' '.join(args)}") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown git error"
        raise RuntimeError(stderr)
    return completed.stdout


def build_git_tools(
    *,
    workspace_root: Path,
    tool_catalog: Any,
    emit_tool_event: Callable[..., None],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    @tool
    def git_status() -> str:
        """Inspect the current repository status from the workspace root."""
        tool_name = "git_status"
        emit_tool_event(tool_name=tool_name, stage="start")
        try:
            output = _run_git_command(workspace_root=workspace_root, args=["status", "--short", "--branch"])
            lines = output.splitlines()
            branch = lines[0][3:].strip() if lines and lines[0].startswith("## ") else None
            payload = {
                "branch": branch,
                "is_clean": len(lines) <= 1,
                "entries": lines[1:] if branch is not None else lines,
                "raw": output.strip(),
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc))
            raise

    @tool
    def git_diff(pathspec: str = "", staged: bool = False, context_lines: int | None = None) -> str:
        """Return a git diff for the workspace, optionally narrowed to one path."""
        tool_name = "git_diff"
        emit_tool_event(
            tool_name=tool_name,
            stage="start",
            pathspec=pathspec,
            staged=staged,
            context_lines=context_lines,
        )
        try:
            requested_context_lines = (
                tool_catalog.git_diff.default_context_lines
                if context_lines is None
                else int(context_lines)
            )
            capped_context_lines = max(0, min(requested_context_lines, tool_catalog.git_diff.max_context_lines))
            args = ["diff", "--no-color", f"--unified={capped_context_lines}"]
            if staged:
                args.append("--cached")
            if pathspec.strip():
                resolved = _resolve_workspace_path(raw_path=pathspec, workspace_root=workspace_root)
                args.extend(["--", _coerce_relative_posix(resolved, workspace_root)])
            output = _run_git_command(workspace_root=workspace_root, args=args)
            payload = {
                "pathspec": pathspec or None,
                "staged": staged,
                "diff": output[: tool_catalog.git_diff.max_diff_chars],
                "truncated": len(output) > tool_catalog.git_diff.max_diff_chars,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), pathspec=pathspec, staged=staged)
            raise

    @tool
    def git_log(limit: int | None = None) -> str:
        """Return recent commits from the current repository."""
        tool_name = "git_log"
        emit_tool_event(tool_name=tool_name, stage="start", limit=limit)
        try:
            requested_limit = tool_catalog.git_log.default_limit if limit is None else int(limit)
            capped_limit = max(1, min(requested_limit, tool_catalog.git_log.max_limit))
            output = _run_git_command(
                workspace_root=workspace_root,
                args=["log", f"-n{capped_limit}", "--pretty=format:%H%x09%h%x09%s"],
            )
            commits = []
            for line in output.splitlines():
                full_hash, short_hash, subject = (line.split("\t", 2) + ["", "", ""])[:3]
                commits.append(
                    {
                        "commit": full_hash,
                        "short": short_hash,
                        "subject": subject,
                    }
                )
            result = json.dumps({"limit": capped_limit, "commits": commits}, ensure_ascii=False)
            emit_tool_event(tool_name=tool_name, stage="end", result_count=len(commits), output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), limit=limit)
            raise

    return (
        {
            "git_status": git_status,
            "git_diff": git_diff,
            "git_log": git_log,
        },
        {
            "git_status": {
                "parallel_safe": True,
                "max_observation_chars": 3000,
            },
            "git_diff": {
                "parallel_safe": True,
                "max_observation_chars": 6000,
            },
            "git_log": {
                "parallel_safe": True,
                "max_observation_chars": 5000,
            },
        },
    )
