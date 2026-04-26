from __future__ import annotations

from collections import Counter
import fnmatch
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterable

from langchain.tools import tool

from .common import _coerce_relative_posix, _read_text_file, _require_non_empty_text_arg

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
    return _TEXT_FILE_SUFFIX_TO_LANGUAGE.get(path.suffix.lower(), path.suffix.lower() or "no_extension")


def _resolve_workspace_path(*, raw_path: str, workspace_root: Path) -> Path:
    candidate = Path(raw_path).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (workspace_root / candidate).resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(f"Path must stay within workspace root: {workspace_root}") from exc
    return resolved


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


def build_workspace_tools(
    *,
    workspace_root: Path,
    tool_catalog: Any,
    emit_tool_event: Callable[..., None],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
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

    @tool
    def list_files(path: str = ".", pattern: str = "**/*", max_results: int | None = None) -> str:
        """List workspace files under a directory using a glob-like pattern."""
        tool_name = "list_files"
        emit_tool_event(tool_name=tool_name, stage="start", path=path, pattern=pattern, max_results=max_results)
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
            emit_tool_event(tool_name=tool_name, stage="end", result_count=len(matches), output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), path=path)
            raise

    @tool
    def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
        """Read a UTF-8 text file from the workspace with line numbers."""
        tool_name = "read_file"
        emit_tool_event(tool_name=tool_name, stage="start", path=path, start_line=start_line, end_line=end_line)
        try:
            resolved = _resolve_workspace_path(raw_path=path, workspace_root=workspace_root)
            if resolved.is_dir():
                raise IsADirectoryError(path)
            if start_line < 1:
                raise ValueError("start_line must be at least 1.")
            requested_end_line = tool_catalog.read_file.default_end_line if end_line is None else int(end_line)
            if requested_end_line < start_line:
                raise ValueError("end_line must be greater than or equal to start_line.")
            capped_end_line = min(requested_end_line, start_line + tool_catalog.read_file.max_lines - 1)
            content = _read_text_file(resolved)
            all_lines = content.splitlines()
            selected_lines = all_lines[start_line - 1 : capped_end_line]
            rendered = _format_numbered_lines(selected_lines, start_line=start_line) if selected_lines else ""
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
            capped_results = max(1, min(requested_results, tool_catalog.search_code.max_results_cap))
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
                    matches.append(
                        {
                            "path": relative,
                            "line_number": line_number,
                            "line": line,
                        }
                    )
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
            emit_tool_event(tool_name=tool_name, stage="end", result_count=len(matches), output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), query=query, path=path)
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
            emit_tool_event(tool_name=tool_name, stage="end", output=result[:800], files_scanned=file_counter)
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), path=path)
            raise

    return (
        {
            "list_files": list_files,
            "read_file": read_file,
            "search_code": search_code,
            "codebase_stats": codebase_stats,
        },
        {
            "list_files": {
                "parallel_safe": True,
                "cacheable": True,
                "cache_scope": "thread",
                "max_observation_chars": 6000,
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
            "codebase_stats": {
                "parallel_safe": True,
                "cacheable": True,
                "cache_scope": "thread",
                "max_observation_chars": 5000,
            },
        },
    )
