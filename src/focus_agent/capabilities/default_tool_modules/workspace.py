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
from ..workspace_files import WORKSPACE_SKIP_DIR_NAMES, language_for_path
from .build_context import ToolBuildContext
from .common import (
    _capped_int,
    _coerce_relative_posix,
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
from .workspace_patch import _validate_patch_paths
from .workspace_paths import (
    _resolve_workspace_command_cwd,
    _resolve_workspace_path,
    _trusted_skill_python_interpreter_name,
    _trusted_workspace_skill_collection_roots,
    _workspace_skill_root_for_path,
)
from .workspace_read import _validate_read_file_args, build_read_file_tool
from .workspace_tree import build_workspace_tree_tool


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
        dirnames[:] = sorted(name for name in dirnames if name not in WORKSPACE_SKIP_DIR_NAMES)
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


def _trusted_skill_script_command_allowed(
    command: list[str],
    *,
    working_dir: Path,
    workspace_root: Path,
    skill_collection_roots: Any,
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
        skill_collection_roots=skill_collection_roots,
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


def _validate_search_code_args(args: dict[str, Any]) -> None:
    _require_non_empty_text_arg(args, "query")


def _validate_workspace_search_args(args: dict[str, Any]) -> None:
    _require_non_empty_text_arg(args, "query")


def _validate_apply_patch_args(args: dict[str, Any]) -> None:
    _require_non_empty_text_arg(args, "patch")


def _normalize_run_workspace_command_args(
    args: dict[str, Any], *, workspace_root: Path
) -> tuple[list[str], Path, str]:
    normalized_command = normalize_command(args.get("command"))
    working_dir = _resolve_workspace_command_cwd(
        raw_cwd=args.get("cwd", "."), workspace_root=workspace_root
    )
    normalized_cwd = _coerce_relative_posix(working_dir, workspace_root)
    args["command"] = normalized_command
    args["cwd"] = normalized_cwd
    return normalized_command, working_dir, normalized_cwd


def _make_run_workspace_command_validator(
    workspace_root: Path,
) -> Callable[[dict[str, Any]], None]:
    def _validate_run_workspace_command_args(args: dict[str, Any]) -> None:
        _normalize_run_workspace_command_args(args, workspace_root=workspace_root)

    return _validate_run_workspace_command_args


def _line_matcher(query: str, *, literal: bool, case_sensitive: bool) -> Callable[[str], bool]:
    if literal:
        needle = query if case_sensitive else query.lower()

        def literal_matcher(line: str) -> bool:
            haystack = line if case_sensitive else line.lower()
            return needle in haystack

        return literal_matcher
    pattern = re.compile(query, flags=0 if case_sensitive else re.IGNORECASE)

    def regex_matcher(line: str) -> bool:
        return bool(pattern.search(line))

    return regex_matcher


def build_list_files_tool(context: ToolBuildContext) -> Any:
    workspace_root = context.workspace_root
    tool_catalog = context.tool_catalog
    emit_tool_event = context.emit_tool_event

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
            capped_results = _capped_int(
                max_results,
                default=tool_catalog.list_files.default_max_results,
                cap=tool_catalog.list_files.max_results_cap,
            )
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

    return list_files


def build_search_code_tool(context: ToolBuildContext) -> Any:
    workspace_root = context.workspace_root
    tool_catalog = context.tool_catalog
    emit_tool_event = context.emit_tool_event

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
            capped_results = _capped_int(
                max_results,
                default=tool_catalog.search_code.default_max_results,
                cap=tool_catalog.search_code.max_results_cap,
            )
            normalized_query = query.strip()
            if not normalized_query:
                raise ValueError("query must not be empty.")
            matcher = _line_matcher(
                normalized_query, literal=literal, case_sensitive=case_sensitive
            )

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
                    line_context = _search_result_context(lines, line_number=line_number)
                    if line_context:
                        item["context"] = line_context
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

    return search_code


def build_workspace_search_tool(context: ToolBuildContext) -> Any:
    workspace_root = context.workspace_root
    tool_catalog = context.tool_catalog
    emit_tool_event = context.emit_tool_event

    @tool
    def workspace_search(query: str, limit: int | None = None) -> str:
        """Search workspace code and docs using the semantic retrieval index."""
        tool_name = "workspace_search"
        emit_tool_event(tool_name=tool_name, stage="start", query=query, limit=limit)
        try:
            normalized_query = query.strip()
            if not normalized_query:
                raise ValueError("query must not be empty.")
            capped_limit = _capped_int(
                limit,
                default=tool_catalog.workspace_search.default_limit,
                cap=tool_catalog.workspace_search.max_limit,
            )
            provider = getattr(context.memory_embedding_service, "provider", None)
            from ...retrieval.workspace import WorkspaceSemanticSearchService

            results = WorkspaceSemanticSearchService(
                retrieval_index=context.retrieval_index,
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

    return workspace_search


def build_codebase_stats_tool(context: ToolBuildContext) -> Any:
    workspace_root = context.workspace_root
    tool_catalog = context.tool_catalog
    emit_tool_event = context.emit_tool_event

    @tool
    def codebase_stats(path: str = ".", max_files: int | None = None) -> str:
        """Summarize file counts and line counts for the current workspace."""
        tool_name = "codebase_stats"
        emit_tool_event(tool_name=tool_name, stage="start", path=path, max_files=max_files)
        try:
            root = _resolve_workspace_path(raw_path=path, workspace_root=workspace_root)
            if not root.exists():
                raise FileNotFoundError(path)
            capped_files = _capped_int(
                max_files,
                default=tool_catalog.codebase_stats.default_max_files,
                cap=tool_catalog.codebase_stats.max_files_cap,
            )
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
                language = language_for_path(candidate)
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

    return codebase_stats


def build_apply_patch_tool(context: ToolBuildContext) -> Any:
    workspace_root = context.workspace_root
    tool_catalog = context.tool_catalog
    emit_tool_event = context.emit_tool_event

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

    return apply_patch


def build_run_workspace_command_tool(
    context: ToolBuildContext,
    *,
    trusted_skill_collection_root_paths: Any,
) -> Any:
    workspace_root = context.workspace_root
    command_config = context.tool_catalog.run_workspace_command
    emit_tool_event = context.emit_tool_event

    def _resolve_workspace_command_path(raw_path: str) -> Path:
        return _resolve_workspace_path(raw_path=raw_path, workspace_root=workspace_root)

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
            args, workspace_root=workspace_root
        )
        emit_tool_event(
            tool_name=tool_name, stage="start", command=normalized_command, cwd=normalized_cwd
        )
        try:
            if not working_dir.exists():
                raise FileNotFoundError(normalized_cwd)
            if not working_dir.is_dir():
                raise NotADirectoryError(normalized_cwd)
            allowed_commands = allowed_command_names(command_config.allowed_commands)
            if not workspace_command_allowed(
                normalized_command, allowed_commands
            ) and not _trusted_skill_script_command_allowed(
                normalized_command,
                working_dir=working_dir,
                workspace_root=workspace_root,
                skill_collection_roots=trusted_skill_collection_root_paths,
            ):
                raise ValueError(
                    "command is not allowlisted; pass argv for a supported test, lint, "
                    "build, check, or trusted local skill script command."
                )
            validate_command_paths(normalized_command, resolve_path=_resolve_workspace_command_path)
            resolve_command_executable(
                normalized_command, resolve_path=_resolve_workspace_command_path
            )
            capped_timeout = _capped_int(
                timeout_seconds,
                default=command_config.default_timeout_seconds,
                cap=command_config.max_timeout_seconds,
            )
            capped_output_chars = _capped_int(
                max_output_chars,
                default=command_config.max_output_chars,
                cap=command_config.max_output_chars,
                floor=100,
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
                    thread_id=context.get_current_thread_id(),
                    branch_id=context.get_current_branch_id(),
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

    return run_workspace_command


def build_workspace_tools(
    context: ToolBuildContext,
    *,
    trusted_skill_collection_roots: Iterable[str | Path] = (),
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    workspace_root = context.workspace_root
    tool_catalog = context.tool_catalog
    trusted_skill_collection_root_paths = _trusted_workspace_skill_collection_roots(
        workspace_root=workspace_root,
        configured_roots=trusted_skill_collection_roots,
    )
    return (
        {
            "list_files": build_list_files_tool(context),
            "workspace_tree": build_workspace_tree_tool(
                workspace_root=workspace_root,
                tree_config=tool_catalog.workspace_tree,
                emit_tool_event=context.emit_tool_event,
            ),
            "read_file": build_read_file_tool(
                workspace_root=workspace_root,
                tool_catalog=tool_catalog,
                emit_tool_event=context.emit_tool_event,
            ),
            "search_code": build_search_code_tool(context),
            "workspace_search": build_workspace_search_tool(context),
            "codebase_stats": build_codebase_stats_tool(context),
            "apply_patch": build_apply_patch_tool(context),
            "run_workspace_command": build_run_workspace_command_tool(
                context,
                trusted_skill_collection_root_paths=trusted_skill_collection_root_paths,
            ),
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
                "validator": _make_run_workspace_command_validator(workspace_root),
                "max_observation_chars": 8000,
            },
        },
    )
