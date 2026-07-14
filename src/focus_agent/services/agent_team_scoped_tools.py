from __future__ import annotations

import fnmatch
import json
import os
import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from langchain.tools import tool

from focus_agent.capabilities.default_tool_modules.common import _read_text_file
from focus_agent.capabilities.default_tool_modules.workspace import _run_git_apply
from focus_agent.capabilities.default_tool_modules.workspace_command import (
    allowed_command_names,
    normalize_command,
    resolve_command_executable,
    validate_command_paths,
    workspace_command_allowed,
    workspace_command_env,
)
from focus_agent.capabilities.default_tool_modules.workspace_patch import _validate_patch_paths
from focus_agent.capabilities.default_tool_modules.workspace_paths import _resolve_workspace_path
from focus_agent.capabilities.sandbox_execution import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
)

_SKIP_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".next",
        ".tox",
        ".cache",
        "dist",
        "build",
    }
)


@runtime_checkable
class AgentTeamSandboxRunner(Protocol):
    """Minimal sandbox dependency required by Agent Team command tools."""

    def run(self, request: SandboxExecutionRequest) -> SandboxExecutionResult:
        """Execute a request in the configured sandbox."""


SandboxRunner = AgentTeamSandboxRunner | Callable[[SandboxExecutionRequest], SandboxExecutionResult]
ToolEventEmitter = Callable[..., None]


def build_agent_team_scoped_tools(
    *,
    workspace_root: str | Path,
    write_scope: Iterable[str] = (),
    sandbox_runner: SandboxRunner,
    task_id: str | None = None,
    require_docker: bool = False,
    allow_fallback: bool = True,
    max_patch_bytes: int = 256_000,
    max_read_lines: int = 500,
    max_search_results: int = 100,
    default_timeout_seconds: int = 60,
    max_timeout_seconds: int = 600,
    max_output_chars: int = 20_000,
    allowed_commands: Iterable[str] = (
        "cargo",
        "go",
        "make",
        "mypy",
        "npm",
        "pnpm",
        "pytest",
        "ruff",
        "uv",
    ),
    command_env_factory: Callable[[], Mapping[str, str]] = workspace_command_env,
    emit_tool_event: ToolEventEmitter | None = None,
) -> dict[str, Any]:
    """Build task-worktree tools without registering or changing chat tools.

    The returned mapping intentionally uses the standard workspace tool names so an
    execution kernel can substitute these task-scoped implementations for one run.
    Commands have no local fallback: every invocation is delegated to
    ``sandbox_runner``.
    """

    root = Path(workspace_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"workspace_root must be an existing directory: {root}")
    if sandbox_runner is None:
        raise ValueError("sandbox_runner is required for Agent Team scoped commands.")

    normalized_write_scope = _normalize_write_scope(write_scope)
    safe_max_patch_bytes = max(1, int(max_patch_bytes))
    safe_max_read_lines = max(1, int(max_read_lines))
    safe_max_search_results = max(1, int(max_search_results))
    safe_default_timeout = max(1, int(default_timeout_seconds))
    safe_max_timeout = max(safe_default_timeout, int(max_timeout_seconds))
    safe_max_output_chars = max(100, int(max_output_chars))
    allowed_command_set = allowed_command_names(tuple(allowed_commands))

    def emit(*, tool_name: str, stage: str, **payload: Any) -> None:
        if emit_tool_event is not None:
            emit_tool_event(tool_name=tool_name, stage=stage, task_id=task_id, **payload)

    def resolve_path(raw_path: str) -> Path:
        return _resolve_workspace_path(raw_path=raw_path, workspace_root=root)

    @tool
    def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
        """Read a text file only from the assigned task worktree."""
        tool_name = "read_file"
        emit(tool_name=tool_name, stage="start", path=path)
        try:
            resolved = resolve_path(path)
            if not resolved.is_file():
                raise IsADirectoryError(path) if resolved.is_dir() else FileNotFoundError(path)
            requested_start = int(start_line)
            if requested_start < 1:
                raise ValueError("start_line must be at least 1.")
            requested_end = (
                requested_start + safe_max_read_lines - 1 if end_line is None else int(end_line)
            )
            if requested_end < requested_start:
                raise ValueError("end_line must be greater than or equal to start_line.")
            capped_end = min(requested_end, requested_start + safe_max_read_lines - 1)
            lines = _read_text_file(resolved).splitlines()
            content = _format_numbered_lines(
                lines[requested_start - 1 : capped_end],
                start_line=requested_start,
            )
            payload = {
                "tool": tool_name,
                "task_id": task_id,
                "workspace_root": str(root),
                "path": _relative_path(resolved, root),
                "start_line": requested_start,
                "end_line": capped_end,
                "total_lines": len(lines),
                "content": content,
                "truncated": requested_end > capped_end,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit(tool_name=tool_name, stage="error", error=str(exc), path=path)
            raise

    @tool
    def search_code(
        query: str,
        path: str = ".",
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int | None = None,
    ) -> str:
        """Search text files only under the assigned task worktree."""
        tool_name = "search_code"
        emit(tool_name=tool_name, stage="start", query=query, path=path, glob=glob)
        try:
            normalized_query = query.strip()
            if not normalized_query:
                raise ValueError("query must not be empty.")
            search_root = resolve_path(path)
            if not search_root.exists():
                raise FileNotFoundError(path)
            requested_max_results = (
                safe_max_search_results if max_results is None else int(max_results)
            )
            capped_max_results = max(1, min(requested_max_results, safe_max_search_results))
            matcher = _line_matcher(
                query=normalized_query,
                literal=literal,
                case_sensitive=case_sensitive,
            )
            candidates = (
                (search_root,) if search_root.is_file() else _iter_workspace_files(search_root)
            )
            matches: list[dict[str, Any]] = []
            truncated = False
            for candidate in candidates:
                relative = _relative_path(candidate, root)
                if glob and not _matches_glob(relative, glob):
                    continue
                try:
                    lines = _read_text_file(candidate).splitlines()
                except ValueError:
                    continue
                for line_number, line in enumerate(lines, start=1):
                    if not matcher(line):
                        continue
                    matches.append(
                        {
                            "path": relative,
                            "line_number": line_number,
                            "line": line,
                        }
                    )
                    if len(matches) >= capped_max_results:
                        truncated = True
                        break
                if truncated:
                    break
            payload = {
                "tool": tool_name,
                "task_id": task_id,
                "workspace_root": str(root),
                "query": query,
                "path": _relative_path(search_root, root),
                "glob": glob,
                "literal": literal,
                "case_sensitive": case_sensitive,
                "results": matches,
                "truncated": truncated,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit(tool_name=tool_name, stage="end", result_count=len(matches), output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit(tool_name=tool_name, stage="error", error=str(exc), query=query, path=path)
            raise

    @tool
    def apply_patch(patch: str) -> str:
        """Apply a text patch only when every affected file is in task write scope."""
        tool_name = "apply_patch"
        emit(tool_name=tool_name, stage="start", patch_bytes=len(patch.encode("utf-8")))
        try:
            if not isinstance(patch, str) or not patch.strip():
                raise ValueError("patch must not be empty.")
            changed_paths = _validate_patch_paths(
                patch=patch,
                workspace_root=root,
                max_patch_bytes=safe_max_patch_bytes,
            )
            relative_paths = _validate_patch_write_scope(
                paths=changed_paths,
                workspace_root=root,
                write_scope=normalized_write_scope,
            )
            _run_git_apply(workspace_root=root, patch=patch, check=True)
            _run_git_apply(workspace_root=root, patch=patch, check=False)
            payload = {
                "tool": tool_name,
                "task_id": task_id,
                "workspace_root": str(root),
                "changed_files": relative_paths,
                "write_scope": list(normalized_write_scope),
                "applied": True,
                "method": "git apply",
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit(tool_name=tool_name, stage="end", result_count=len(relative_paths), output=result)
            return result
        except Exception as exc:  # noqa: BLE001
            emit(tool_name=tool_name, stage="error", error=str(exc))
            raise

    @tool
    def run_workspace_command(
        command: list[str],
        cwd: str = ".",
        timeout_seconds: int | None = None,
        max_output_chars: int | None = None,
    ) -> str:
        """Run an argv command through the injected task sandbox runner only."""
        tool_name = "run_workspace_command"
        normalized_command = normalize_command(command)
        working_directory = resolve_path(cwd)
        normalized_cwd = _relative_path(working_directory, root)
        emit(
            tool_name=tool_name,
            stage="start",
            command=normalized_command,
            cwd=normalized_cwd,
        )
        try:
            if not working_directory.is_dir():
                raise NotADirectoryError(cwd)
            if not workspace_command_allowed(normalized_command, allowed_command_set):
                raise ValueError(
                    f"Command is not allowlisted for Agent Team execution: {normalized_command[0]}"
                )
            validate_command_paths(normalized_command, resolve_path=resolve_path)
            resolved_command = resolve_command_executable(
                normalized_command,
                resolve_path=resolve_path,
            )
            requested_timeout = (
                safe_default_timeout if timeout_seconds is None else int(timeout_seconds)
            )
            requested_output_chars = (
                safe_max_output_chars if max_output_chars is None else int(max_output_chars)
            )
            request = SandboxExecutionRequest(
                workspace_root=root,
                command=resolved_command,
                cwd=normalized_cwd,
                timeout_seconds=max(1, min(requested_timeout, safe_max_timeout)),
                max_output_chars=max(100, min(requested_output_chars, safe_max_output_chars)),
                allow_network=False,
                env=dict(command_env_factory()),
                tool_name=tool_name,
                sandbox_id=f"agent-team-{task_id}" if task_id else None,
                workspace_mode="copy_discard",
                fallback_policy="allow_dev_local" if allow_fallback else "deny",
                policy={
                    "agent_team_task_id": task_id,
                    "require_docker": require_docker,
                    "allow_fallback": allow_fallback,
                },
            )
            sandbox_payload = _sandbox_payload(_run_sandbox(sandbox_runner, request))
            result_payload = _command_result_payload(
                sandbox_payload=sandbox_payload,
                workspace_root=root,
                task_id=task_id,
                require_docker=require_docker,
                allow_fallback=allow_fallback,
            )
            result = json.dumps(result_payload, ensure_ascii=False)
            emit(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit(
                tool_name=tool_name,
                stage="error",
                error=str(exc),
                command=normalized_command,
                cwd=normalized_cwd,
            )
            raise

    return {
        "read_file": read_file,
        "search_code": search_code,
        "apply_patch": apply_patch,
        "run_workspace_command": run_workspace_command,
    }


def _normalize_write_scope(write_scope: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_pattern in write_scope:
        pattern = str(raw_pattern).strip().replace("\\", "/")
        if not pattern:
            continue
        if Path(pattern).is_absolute() or any(part == ".." for part in Path(pattern).parts):
            raise ValueError(f"write_scope pattern must be workspace-relative: {raw_pattern}")
        while pattern.startswith("./"):
            pattern = pattern[2:]
        if pattern:
            normalized.append(pattern)
    return tuple(dict.fromkeys(normalized))


def _validate_patch_write_scope(
    *,
    paths: Iterable[str],
    workspace_root: Path,
    write_scope: tuple[str, ...],
) -> list[str]:
    if not write_scope:
        raise PermissionError("apply_patch requires a non-empty task write_scope.")
    relative_paths: list[str] = []
    out_of_scope: list[str] = []
    for raw_path in paths:
        relative = _relative_path(
            _resolve_workspace_path(raw_path=raw_path, workspace_root=workspace_root),
            workspace_root,
        )
        relative_paths.append(relative)
        if not any(_matches_glob(relative, pattern) for pattern in write_scope):
            out_of_scope.append(relative)
    if out_of_scope:
        raise PermissionError(
            "patch contains files outside task write_scope: " + ", ".join(out_of_scope)
        )
    return relative_paths


def _line_matcher(
    *,
    query: str,
    literal: bool,
    case_sensitive: bool,
) -> Callable[[str], bool]:
    if literal:
        needle = query if case_sensitive else query.lower()

        def match_literal(line: str) -> bool:
            return needle in (line if case_sensitive else line.lower())

        return match_literal
    pattern = re.compile(query, flags=0 if case_sensitive else re.IGNORECASE)
    return lambda line: bool(pattern.search(line))


def _iter_workspace_files(root: Path) -> Iterable[Path]:
    for current_root, directory_names, file_names in os.walk(root):
        directory_names[:] = sorted(
            name for name in directory_names if name not in _SKIP_DIRECTORY_NAMES
        )
        current_path = Path(current_root)
        yield from (current_path / name for name in sorted(file_names))


def _format_numbered_lines(lines: list[str], *, start_line: int) -> str:
    if not lines:
        return ""
    width = max(2, len(str(start_line + len(lines) - 1)))
    return "\n".join(f"{start_line + index:{width}d} | {line}" for index, line in enumerate(lines))


def _matches_glob(path: str, pattern: str) -> bool:
    candidate = pattern or "**/*"
    while True:
        if fnmatch.fnmatch(path, candidate):
            return True
        if "**/" not in candidate:
            return False
        candidate = candidate.replace("**/", "", 1)


def _relative_path(path: Path, workspace_root: Path) -> str:
    try:
        relative = path.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(f"Path must stay within workspace root: {workspace_root}") from exc
    return relative.as_posix() or "."


def _run_sandbox(
    sandbox_runner: SandboxRunner,
    request: SandboxExecutionRequest,
) -> SandboxExecutionResult | Mapping[str, Any]:
    run = getattr(sandbox_runner, "run", None)
    if callable(run):
        return run(request)
    if callable(sandbox_runner):
        return sandbox_runner(request)
    raise TypeError("sandbox_runner must be callable or expose run(request).")


def _sandbox_payload(result: SandboxExecutionResult | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    to_payload = getattr(result, "to_payload", None)
    if callable(to_payload):
        payload = to_payload()
        if isinstance(payload, Mapping):
            return dict(payload)
    raise TypeError("sandbox_runner must return SandboxExecutionResult or a mapping payload.")


def _command_result_payload(
    *,
    sandbox_payload: Mapping[str, Any],
    workspace_root: Path,
    task_id: str | None,
    require_docker: bool,
    allow_fallback: bool,
) -> dict[str, Any]:
    payload = dict(sandbox_payload)
    sandbox_backend = str(payload.get("sandbox_backend") or "").strip().lower()
    fallback_used = bool(payload.get("fallback_used"))
    violations: list[str] = []
    if require_docker and sandbox_backend != "docker":
        violations.append("docker sandbox is required for this task command.")
    if not allow_fallback and fallback_used:
        violations.append("sandbox fallback is not allowed for this task command.")

    command_succeeded = (
        str(payload.get("status") or "").lower() == "completed"
        and payload.get("timed_out") is not True
        and payload.get("exit_code") == 0
    )
    status = (
        "completed"
        if command_succeeded and not violations
        else "blocked"
        if violations
        else "failed"
    )
    evidence = {
        "kind": "agent_team_sandbox_command",
        "task_id": task_id,
        "workspace_root": str(workspace_root),
        "sandbox_backend": sandbox_backend or None,
        "sandbox_id": payload.get("sandbox_id"),
        "run_id": payload.get("run_id"),
        "exit_code": payload.get("exit_code"),
        "timed_out": bool(payload.get("timed_out")),
        "fallback_used": fallback_used,
        "fallback_reason": payload.get("fallback_reason"),
        "require_docker": require_docker,
        "allow_fallback": allow_fallback,
        "policy_violations": violations,
    }
    return {
        **payload,
        "tool": "run_workspace_command",
        "task_id": task_id,
        "workspace_root": str(workspace_root),
        "status": status,
        "ok": status == "completed",
        "evidence": evidence,
    }


__all__ = [
    "AgentTeamSandboxRunner",
    "SandboxRunner",
    "build_agent_team_scoped_tools",
]
