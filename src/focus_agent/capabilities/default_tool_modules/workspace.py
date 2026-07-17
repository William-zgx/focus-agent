from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from langchain.tools import tool

from ..sandbox_execution import SandboxExecutionRequest, default_sandbox_execution_service
from .common import (
    _coerce_relative_posix,
    _get_current_branch_id,
    _get_current_thread_id,
    _read_text_file,
    _require_non_empty_text_arg,
)
from .workspace_command import (
    allowed_command_names,
    normalize_command,
    resolve_command_executable,
    validate_command_paths,
    workspace_command_allowed,
    workspace_command_env,
)
from .workspace_patch import _patch_line_token as _patch_line_token
from .workspace_patch import (
    _patch_mentions_unsupported_file_mode as _patch_mentions_unsupported_file_mode,
)
from .workspace_patch import _patch_paths as _patch_paths
from .workspace_patch import _patch_token_path as _patch_token_path
from .workspace_patch import _validate_patch_paths as _validate_patch_paths
from .workspace_paths import (
    _resolve_focus_home_skill_cwd as _resolve_focus_home_skill_cwd,
)
from .workspace_paths import (
    _resolve_workspace_command_cwd as _resolve_workspace_command_cwd,
)
from .workspace_paths import _resolve_workspace_path as _resolve_workspace_path
from .workspace_paths import (
    _resolve_workspace_skill_collection_root as _resolve_workspace_skill_collection_root,
)
from .workspace_paths import (
    _trusted_skill_python_interpreter_name as _trusted_skill_python_interpreter_name,
)
from .workspace_paths import (
    _trusted_workspace_skill_collection_roots as _trusted_workspace_skill_collection_roots,
)
from .workspace_paths import (
    _workspace_skill_root_for_path as _workspace_skill_root_for_path,
)
from .workspace_tree import build_workspace_tree_tool

_SKIP_DIR_NAMES = {
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
    ".claude",
    ".focus_agent",
    "dist",
    "build",
}
_TEXT_FILE_SUFFIX_TO_LANGUAGE = {
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".go": "Go",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".html": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".json": "JSON",
    ".kt": "Kotlin",
    ".md": "Markdown",
    ".mjs": "JavaScript",
    ".php": "PHP",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".sh": "Shell",
    ".sql": "SQL",
    ".swift": "Swift",
    ".toml": "TOML",
    ".ts": "TypeScript",
    ".tsx": "TSX",
    ".txt": "Text",
    ".xml": "XML",
    ".yaml": "YAML",
    ".yml": "YAML",
}


def _language_for_path(path: Path) -> str:
    return _TEXT_FILE_SUFFIX_TO_LANGUAGE.get(
        path.suffix.lower(), path.suffix.lower() or "no_extension"
    )


def _matches_glob_pattern(path_text: str, pattern: str) -> bool:
    candidate = pattern or "**/*"
    while True:
        if fnmatch.fnmatch(path_text, candidate):
            return True
        marker = "**/"
        if marker not in candidate:
            return False
        candidate = candidate.replace(marker, "", 1)


def _iter_workspace_files(root: Path) -> Iterable[Path]:
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in _SKIP_DIR_NAMES)
        current_path = Path(current_root)
        for filename in sorted(filenames):
            yield current_path / filename


def _format_numbered_lines(lines: list[str], *, start_line: int) -> str:
    width = max(len(str(start_line + len(lines) - 1)), 2)
    return "\n".join(f"{start_line + index:{width}d} | {line}" for index, line in enumerate(lines))


def _search_result_context(lines: list[str], *, line_number: int) -> str | None:
    line = lines[line_number - 1] if 0 < line_number <= len(lines) else ""
    if not line.rstrip().endswith("{"):
        return None
    end_line = min(len(lines), line_number + 16)
    return _format_numbered_lines(lines[line_number - 1 : end_line], start_line=line_number)


def _run_git_apply(*, workspace_root: Path, patch: str, check: bool) -> str:
    args = ["git", "apply", "--whitespace=nowarn"]
    if check:
        args.append("--check")
    try:
        completed = subprocess.run(
            args,
            cwd=workspace_root,
            input=patch,
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
        raise RuntimeError("git apply timed out.") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown git apply error"
        raise RuntimeError(detail)
    return completed.stdout.strip()


def build_workspace_tools(
    *,
    workspace_root: Path,
    tool_catalog: Any,
    emit_tool_event: Callable[..., None],
    trusted_skill_collection_roots: Iterable[str | Path] = (),
    memory_embedding_service: Any | None = None,
    retrieval_index: Any | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    trusted_skill_collection_root_paths = _trusted_workspace_skill_collection_roots(
        workspace_root=workspace_root,
        configured_roots=trusted_skill_collection_roots,
    )

    def _trusted_skill_script_command_allowed(
        command: list[str],
        *,
        working_dir: Path,
    ) -> bool:
        if not _trusted_skill_python_interpreter_name(command[0]):
            return False
        if len(command) < 2:
            return False
        script_arg = command[1].strip()
        if not script_arg or script_arg.startswith("-"):
            return False
        skill_root = _workspace_skill_root_for_path(
            path=working_dir,
            workspace_root=workspace_root,
            skill_collection_roots=trusted_skill_collection_root_paths,
        )
        if skill_root is None:
            return False
        script_path = (
            Path(script_arg).expanduser()
            if Path(script_arg).is_absolute()
            else working_dir / script_arg
        ).resolve()
        try:
            script_relative = script_path.relative_to(working_dir)
            script_path.relative_to(skill_root)
            script_path.relative_to(workspace_root)
        except ValueError:
            return False
        return (
            script_relative.parts[:1] == ("scripts",)
            and script_path.suffix == ".py"
            and script_path.is_file()
        )

    def _validate_read_file_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "path")
        start_line = int(args.get("start_line", 1))
        if start_line < 1:
            raise ValueError("start_line must be at least 1.")
        end_line = args.get("end_line")
        if end_line is not None and int(end_line) < start_line:
            raise ValueError("end_line must be greater than or equal to start_line.")

    def _validate_search_code_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "query")

    def _validate_workspace_search_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "query")

    def _validate_apply_patch_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "patch")

    def _normalize_run_workspace_command_args(args: dict[str, Any]) -> tuple[list[str], Path, str]:
        normalized_command = normalize_command(args.get("command"))
        working_dir = _resolve_workspace_command_cwd(
            raw_cwd=args.get("cwd", "."), workspace_root=workspace_root
        )
        normalized_cwd = _coerce_relative_posix(working_dir, workspace_root)
        args["command"] = normalized_command
        args["cwd"] = normalized_cwd
        return normalized_command, working_dir, normalized_cwd

    def _validate_run_workspace_command_args(args: dict[str, Any]) -> None:
        _normalize_run_workspace_command_args(args)

    def _resolve_workspace_command_path(raw_path: str) -> Path:
        return _resolve_workspace_path(raw_path=raw_path, workspace_root=workspace_root)

    @tool
    def list_files(path: str = ".", pattern: str = "**/*", max_results: int | None = None) -> str:
        """List workspace files under a directory using a glob-like pattern."""
        tool_name = "list_files"
        emit_tool_event(
            tool_name=tool_name, stage="start", path=path, pattern=pattern, max_results=max_results
        )
        try:
            root = _resolve_workspace_path(raw_path=path, workspace_root=workspace_root)
            if not root.exists():
                raise FileNotFoundError(path)
            requested_results = (
                tool_catalog.list_files.default_max_results
                if max_results is None
                else int(max_results)
            )
            capped_results = max(1, min(requested_results, tool_catalog.list_files.max_results_cap))
            matches: list[str] = []
            truncated = False
            if root.is_file():
                relative = _coerce_relative_posix(root, workspace_root)
                if _matches_glob_pattern(relative, pattern):
                    matches = [relative]
            else:
                normalized_pattern = pattern or "**/*"
                for candidate in _iter_workspace_files(root):
                    relative = _coerce_relative_posix(candidate, workspace_root)
                    if not _matches_glob_pattern(relative, normalized_pattern):
                        continue
                    matches.append(relative)
                    if len(matches) >= capped_results:
                        truncated = True
                        break

            payload = {
                "workspace_root": str(workspace_root),
                "path": _coerce_relative_posix(root, workspace_root),
                "pattern": pattern,
                "results": matches,
                "truncated": truncated,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(
                tool_name=tool_name, stage="end", result_count=len(matches), output=result[:800]
            )
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), path=path)
            raise

    workspace_tree = build_workspace_tree_tool(
        workspace_root=workspace_root,
        tree_config=tool_catalog.workspace_tree,
        emit_tool_event=emit_tool_event,
    )

    @tool
    def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
        """Read a UTF-8 text file from the workspace with line numbers."""
        tool_name = "read_file"
        emit_tool_event(
            tool_name=tool_name, stage="start", path=path, start_line=start_line, end_line=end_line
        )
        try:
            resolved = _resolve_workspace_path(raw_path=path, workspace_root=workspace_root)
            if resolved.is_dir():
                raise IsADirectoryError(path)
            if start_line < 1:
                raise ValueError("start_line must be at least 1.")
            requested_end_line = (
                tool_catalog.read_file.default_end_line if end_line is None else int(end_line)
            )
            if requested_end_line < start_line:
                raise ValueError("end_line must be greater than or equal to start_line.")
            capped_end_line = min(
                requested_end_line, start_line + tool_catalog.read_file.max_lines - 1
            )
            content = _read_text_file(resolved)
            all_lines = content.splitlines()
            selected_lines = all_lines[start_line - 1 : capped_end_line]
            rendered = (
                _format_numbered_lines(selected_lines, start_line=start_line)
                if selected_lines
                else ""
            )
            if len(rendered) > tool_catalog.read_file.max_chars:
                rendered = rendered[: tool_catalog.read_file.max_chars]
            payload = {
                "path": _coerce_relative_posix(resolved, workspace_root),
                "start_line": start_line,
                "end_line": capped_end_line,
                "total_lines": len(all_lines),
                "content": rendered,
                "truncated": requested_end_line > capped_end_line,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), path=path)
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
        """Search for matching text in workspace files and return matching lines."""
        tool_name = "search_code"
        emit_tool_event(
            tool_name=tool_name,
            stage="start",
            query=query,
            path=path,
            glob=glob,
            literal=literal,
            case_sensitive=case_sensitive,
            max_results=max_results,
        )
        try:
            root = _resolve_workspace_path(raw_path=path, workspace_root=workspace_root)
            if not root.exists():
                raise FileNotFoundError(path)
            requested_results = (
                tool_catalog.search_code.default_max_results
                if max_results is None
                else int(max_results)
            )
            capped_results = max(
                1, min(requested_results, tool_catalog.search_code.max_results_cap)
            )
            normalized_query = query.strip()
            if not normalized_query:
                raise ValueError("query must not be empty.")

            matcher: Any
            if literal:
                needle = normalized_query if case_sensitive else normalized_query.lower()

                def matcher(line: str) -> bool:
                    haystack = line if case_sensitive else line.lower()
                    return needle in haystack
            else:
                flags = 0 if case_sensitive else re.IGNORECASE
                pattern = re.compile(normalized_query, flags=flags)

                def matcher(line: str) -> bool:
                    return bool(pattern.search(line))

            candidates = [root] if root.is_file() else _iter_workspace_files(root)
            matches: list[dict[str, Any]] = []
            truncated = False
            for candidate in candidates:
                relative = _coerce_relative_posix(candidate, workspace_root)
                if glob and not _matches_glob_pattern(relative, glob):
                    continue
                try:
                    lines = _read_text_file(candidate).splitlines()
                except ValueError:
                    continue
                for line_number, line in enumerate(lines, start=1):
                    if not matcher(line):
                        continue
                    item = {
                        "path": relative,
                        "line_number": line_number,
                        "line": line,
                    }
                    context = _search_result_context(lines, line_number=line_number)
                    if context:
                        item["context"] = context
                    matches.append(item)
                    if len(matches) >= capped_results:
                        truncated = True
                        break
                if truncated:
                    break

            payload = {
                "query": query,
                "path": _coerce_relative_posix(root, workspace_root),
                "glob": glob,
                "literal": literal,
                "case_sensitive": case_sensitive,
                "results": matches,
                "truncated": truncated,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(
                tool_name=tool_name, stage="end", result_count=len(matches), output=result[:800]
            )
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(
                tool_name=tool_name, stage="error", error=str(exc), query=query, path=path
            )
            raise

    @tool
    def workspace_search(query: str, limit: int | None = None) -> str:
        """Search workspace code and docs using the semantic retrieval index."""
        tool_name = "workspace_search"
        emit_tool_event(tool_name=tool_name, stage="start", query=query, limit=limit)
        try:
            normalized_query = query.strip()
            if not normalized_query:
                raise ValueError("query must not be empty.")
            requested_limit = (
                tool_catalog.workspace_search.default_limit if limit is None else int(limit)
            )
            capped_limit = max(
                1,
                min(requested_limit, tool_catalog.workspace_search.max_limit),
            )
            provider = getattr(memory_embedding_service, "provider", None)
            from ...retrieval.workspace import WorkspaceSemanticSearchService

            results = WorkspaceSemanticSearchService(
                retrieval_index=retrieval_index,
                embedding_provider=provider,
                workspace_root=workspace_root,
            ).search_workspace(query=normalized_query, limit=capped_limit)
            payload = {
                "query": query,
                "workspace_root": str(workspace_root),
                "results": results,
                "truncated": False,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(
                tool_name=tool_name,
                stage="end",
                result_count=len(results),
                output=result[:800],
            )
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), query=query)
            raise

    @tool
    def codebase_stats(path: str = ".", max_files: int | None = None) -> str:
        """Summarize file counts and line counts for the current workspace."""
        tool_name = "codebase_stats"
        emit_tool_event(tool_name=tool_name, stage="start", path=path, max_files=max_files)
        try:
            root = _resolve_workspace_path(raw_path=path, workspace_root=workspace_root)
            if not root.exists():
                raise FileNotFoundError(path)
            requested_files = (
                tool_catalog.codebase_stats.default_max_files
                if max_files is None
                else int(max_files)
            )
            capped_files = max(1, min(requested_files, tool_catalog.codebase_stats.max_files_cap))
            file_counter = 0
            total_lines = 0
            total_bytes = 0
            truncated = False
            language_counter: Counter[str] = Counter()
            line_counter: Counter[str] = Counter()

            candidates = [root] if root.is_file() else _iter_workspace_files(root)
            for candidate in candidates:
                file_counter += 1
                if file_counter > capped_files:
                    truncated = True
                    file_counter -= 1
                    break
                try:
                    content = _read_text_file(candidate)
                except ValueError:
                    continue
                language = _language_for_path(candidate)
                line_count = len(content.splitlines())
                byte_count = candidate.stat().st_size
                language_counter[language] += 1
                line_counter[language] += line_count
                total_lines += line_count
                total_bytes += byte_count

            breakdown = [
                {
                    "language": language,
                    "files": language_counter[language],
                    "lines": line_counter[language],
                }
                for language, _count in language_counter.most_common()
            ]
            payload = {
                "path": _coerce_relative_posix(root, workspace_root),
                "workspace_root": str(workspace_root),
                "files_scanned": file_counter,
                "total_lines": total_lines,
                "total_bytes": total_bytes,
                "language_breakdown": breakdown,
                "truncated": truncated,
                "method": "workspace text scan",
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(
                tool_name=tool_name, stage="end", output=result[:800], files_scanned=file_counter
            )
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), path=path)
            raise

    @tool
    def apply_patch(patch: str) -> str:
        """Apply a unified diff to text files under the workspace root."""
        tool_name = "apply_patch"
        emit_tool_event(tool_name=tool_name, stage="start", patch_bytes=len(patch.encode("utf-8")))
        try:
            changed_paths = _validate_patch_paths(
                patch=patch,
                workspace_root=workspace_root,
                max_patch_bytes=tool_catalog.apply_patch.max_patch_bytes,
            )
            _run_git_apply(workspace_root=workspace_root, patch=patch, check=True)
            _run_git_apply(workspace_root=workspace_root, patch=patch, check=False)
            payload = {
                "workspace_root": str(workspace_root),
                "changed_files": list(changed_paths),
                "applied": True,
                "method": "git apply",
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(
                tool_name=tool_name, stage="end", result_count=len(changed_paths), output=result
            )
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc))
            raise

    @tool
    def run_workspace_command(
        command: list[str],
        cwd: str = ".",
        timeout_seconds: int | None = None,
        max_output_chars: int | None = None,
    ) -> str:
        """Run an allowlisted workspace command without a shell."""
        tool_name = "run_workspace_command"
        args = {"command": command, "cwd": cwd}
        normalized_command, working_dir, normalized_cwd = _normalize_run_workspace_command_args(
            args
        )
        emit_tool_event(
            tool_name=tool_name, stage="start", command=normalized_command, cwd=normalized_cwd
        )
        try:
            if not working_dir.exists():
                raise FileNotFoundError(normalized_cwd)
            if not working_dir.is_dir():
                raise NotADirectoryError(normalized_cwd)
            allowed_commands = allowed_command_names(
                tool_catalog.run_workspace_command.allowed_commands
            )
            if not workspace_command_allowed(
                normalized_command, allowed_commands
            ) and not _trusted_skill_script_command_allowed(
                normalized_command,
                working_dir=working_dir,
            ):
                raise ValueError(
                    "command is not allowlisted; pass argv for a supported test, lint, "
                    "build, check, or trusted local skill script command."
                )
            validate_command_paths(normalized_command, resolve_path=_resolve_workspace_command_path)
            resolve_command_executable(
                normalized_command, resolve_path=_resolve_workspace_command_path
            )
            requested_timeout = (
                tool_catalog.run_workspace_command.default_timeout_seconds
                if timeout_seconds is None
                else int(timeout_seconds)
            )
            capped_timeout = max(
                1,
                min(requested_timeout, tool_catalog.run_workspace_command.max_timeout_seconds),
            )
            requested_output_chars = (
                tool_catalog.run_workspace_command.max_output_chars
                if max_output_chars is None
                else int(max_output_chars)
            )
            capped_output_chars = max(
                100,
                min(requested_output_chars, tool_catalog.run_workspace_command.max_output_chars),
            )
            sandbox_result = default_sandbox_execution_service().run(
                SandboxExecutionRequest(
                    workspace_root=workspace_root,
                    command=normalized_command,
                    cwd=normalized_cwd,
                    timeout_seconds=capped_timeout,
                    max_output_chars=capped_output_chars,
                    allow_network=False,
                    env=workspace_command_env(),
                    tool_name=tool_name,
                    thread_id=_get_current_thread_id(),
                    branch_id=_get_current_branch_id(),
                )
            )
            result = sandbox_result.to_json()
            emit_tool_event(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(
                tool_name=tool_name,
                stage="error",
                error=str(exc),
                command=normalized_command,
                cwd=normalized_cwd,
            )
            raise

    return (
        {
            "list_files": list_files,
            "workspace_tree": workspace_tree,
            "read_file": read_file,
            "search_code": search_code,
            "workspace_search": workspace_search,
            "codebase_stats": codebase_stats,
            "apply_patch": apply_patch,
            "run_workspace_command": run_workspace_command,
        },
        {
            "list_files": {
                "parallel_safe": True,
                "cacheable": True,
                "cache_scope": "thread",
                "max_observation_chars": 6000,
            },
            "workspace_tree": {
                "parallel_safe": True,
                "cacheable": True,
                "cache_scope": "thread",
                "max_observation_chars": 8000,
            },
            "read_file": {
                "parallel_safe": True,
                "cacheable": True,
                "cache_scope": "thread",
                "validator": _validate_read_file_args,
                "max_observation_chars": 8000,
            },
            "search_code": {
                "parallel_safe": True,
                "cacheable": True,
                "cache_scope": "thread",
                "validator": _validate_search_code_args,
                "max_observation_chars": 7000,
            },
            "workspace_search": {
                "parallel_safe": True,
                "cacheable": True,
                "cache_scope": "thread",
                "validator": _validate_workspace_search_args,
                "max_observation_chars": 8000,
                "toolset": "workspace",
                "intent_policies": ("workspace_lookup", "planning"),
            },
            "codebase_stats": {
                "parallel_safe": True,
                "cacheable": True,
                "cache_scope": "thread",
                "max_observation_chars": 5000,
            },
            "apply_patch": {
                "side_effect": True,
                "side_effect_kind": "workspace_write",
                "requires_workspace_write": True,
                "requires_approval": True,
                "risk_level": "medium",
                "validator": _validate_apply_patch_args,
                "max_observation_chars": 5000,
            },
            "run_workspace_command": {
                "side_effect": True,
                "side_effect_kind": "workspace_command",
                "requires_workspace_write": True,
                "requires_approval": True,
                "risk_level": "medium",
                "validator": _validate_run_workspace_command_args,
                "max_observation_chars": 8000,
            },
        },
    )
