from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable
from urllib import error as urllib_error
from urllib import request as urllib_request

from langchain.tools import tool
from langgraph.config import get_stream_writer

from ..config import Settings

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


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "artifact"


def _emit_tool_event(*, tool_name: str, stage: str, **payload: Any) -> None:
    try:
        writer = get_stream_writer()
    except Exception:  # noqa: BLE001
        return
    writer(
        {
            'event': 'tool',
            'tool_name': tool_name,
            'stage': stage,
            **payload,
        }
    )


def _normalize_search_result(*, title: Any, url: Any, content: Any) -> dict[str, str]:
    return {
        "title": str(title or ""),
        "url": str(url or ""),
        "content": str(content or ""),
    }


def _language_for_path(path: Path) -> str:
    return _TEXT_FILE_SUFFIX_TO_LANGUAGE.get(path.suffix.lower(), path.suffix.lower() or "no_extension")


def _looks_binary(chunk: bytes) -> bool:
    return b"\x00" in chunk


def _coerce_relative_posix(path: Path, workspace_root: Path) -> str:
    try:
        relative = path.relative_to(workspace_root)
    except ValueError:
        return str(path)
    rendered = relative.as_posix()
    return rendered or "."


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


def _read_text_file(path: Path) -> str:
    with path.open("rb") as handle:
        chunk = handle.read(4096)
        if _looks_binary(chunk):
            raise ValueError(f"Refusing to read binary file: {path.name}")
        remainder = handle.read()
    return (chunk + remainder).decode("utf-8", errors="replace")


def _format_numbered_lines(lines: list[str], *, start_line: int) -> str:
    width = max(len(str(start_line + len(lines) - 1)), 2)
    return "\n".join(f"{start_line + index:{width}d} | {line}" for index, line in enumerate(lines))


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


def get_default_tools(settings: Settings):
    artifact_dir = Path(settings.artifact_dir).expanduser()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = Path(settings.workspace_root).expanduser().resolve()
    resolved_env = settings.resolved_env or os.environ
    tool_catalog = settings.tool_catalog
    web_search_config = settings.web_search
    tool_configs = {**tool_catalog.by_name, "web_search": web_search_config}
    _base_emit_tool_event = globals()["_emit_tool_event"]

    tool_display_names = {
        tool_name: config.label
        for tool_name, config in tool_configs.items()
    }

    def _emit_tool_event(*, tool_name: str, stage: str, **payload: Any) -> None:
        display_name = tool_display_names.get(tool_name)
        if display_name:
            payload.setdefault("display_name", display_name)
        _base_emit_tool_event(tool_name=tool_name, stage=stage, **payload)

    def _apply_tool_metadata(tool_obj: Any, *, label: str, description: str) -> Any:
        tool_obj.description = description
        if hasattr(tool_obj, "metadata") and isinstance(getattr(tool_obj, "metadata"), dict):
            tool_obj.metadata = {**tool_obj.metadata, "display_name": label}
        else:
            tool_obj.metadata = {"display_name": label}
        return tool_obj
    preferred_web_search_provider = str(web_search_config.provider or "auto").strip().lower() or "auto"
    fallback_web_search_provider = (
        str(web_search_config.fallback_provider).strip().lower()
        if web_search_config.fallback_provider
        else None
    )
    tavily_api_key = (
        (
            resolved_env.get(web_search_config.api_key_env, "").strip()
            if web_search_config.api_key_env
            else ""
        )
        or str(web_search_config.api_key_default or "").strip()
    )

    def _run_tavily_search(*, query: str, max_results: int) -> dict[str, Any]:
        if not tavily_api_key:
            raise RuntimeError("TAVILY_API_KEY is not configured.")
        payload = json.dumps(
            {
                "query": query,
                "max_results": max_results,
                "include_answer": True,
            }
        ).encode("utf-8")
        req = urllib_request.Request(
            "https://api.tavily.com/search",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {tavily_api_key}",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Tavily search failed with HTTP {exc.code}: {body[:300]}") from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"Tavily search failed: {exc.reason}") from exc
        except OSError as exc:
            raise RuntimeError(f"Tavily search failed: {exc}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Tavily search returned invalid JSON.") from exc

        results = data.get("results")
        if not isinstance(results, list):
            raise RuntimeError("Tavily search returned an unusable payload.")

        return {
            "query": query,
            "provider": "tavily",
            "answer": data.get("answer"),
            "results": [
                _normalize_search_result(
                    title=item.get("title"),
                    url=item.get("url"),
                    content=item.get("content"),
                )
                for item in results[:max_results]
            ],
        }

    def _run_duckduckgo_search(*, query: str, max_results: int) -> dict[str, Any]:
        try:
            from ddgs import DDGS
        except ImportError as exc:
            raise RuntimeError("DuckDuckGo fallback is unavailable because 'ddgs' is not installed.") from exc

        try:
            with DDGS(timeout=30) as ddgs:
                raw_results = list(
                    ddgs.text(
                        query,
                        region="wt-wt",
                        safesearch="moderate",
                        max_results=max_results,
                    )
                    or []
                )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"DuckDuckGo search failed: {exc}") from exc

        return {
            "query": query,
            "provider": "duckduckgo",
            "answer": None,
            "results": [
                _normalize_search_result(
                    title=item.get("title"),
                    url=item.get("href") or item.get("link"),
                    content=item.get("body") or item.get("snippet"),
                )
                for item in raw_results[:max_results]
            ],
        }

    def _run_web_search(*, query: str, max_results: int, tool_name: str) -> str:
        normalized_query = query.strip()
        capped_results = max(1, min(int(max_results), 10))
        _emit_tool_event(
            tool_name=tool_name,
            stage='start',
            query=normalized_query,
            max_results=capped_results,
        )
        if not normalized_query:
            message = "Query must not be empty."
            _emit_tool_event(tool_name=tool_name, stage='error', error=message)
            raise ValueError(message)
        if not web_search_config.enabled:
            message = "web_search is disabled by tools configuration."
            _emit_tool_event(tool_name=tool_name, stage='error', error=message)
            raise RuntimeError(message)

        should_try_tavily = preferred_web_search_provider in {"auto", "tavily"}
        should_try_duckduckgo = (
            preferred_web_search_provider == "duckduckgo"
            or fallback_web_search_provider == "duckduckgo"
        )

        tavily_error: str | None = None
        if should_try_tavily and tavily_api_key:
            try:
                payload = _run_tavily_search(query=normalized_query, max_results=capped_results)
                result = json.dumps(payload, ensure_ascii=False)
                _emit_tool_event(
                    tool_name=tool_name,
                    stage='end',
                    provider=payload["provider"],
                    result_count=len(payload["results"]),
                    output=result[:800],
                )
                return result
            except RuntimeError as exc:
                tavily_error = str(exc)
                _emit_tool_event(
                    tool_name=tool_name,
                    stage='delta',
                    provider='tavily',
                    message='Primary Tavily search failed; falling back to DuckDuckGo.',
                    error=tavily_error,
                )
        elif should_try_tavily and not tavily_api_key:
            tavily_error = "Tavily search is configured but the API key is missing."

        if should_try_duckduckgo:
            try:
                payload = _run_duckduckgo_search(query=normalized_query, max_results=capped_results)
            except RuntimeError as exc:
                message = (
                    f"Web search failed. Tavily error: {tavily_error}. DuckDuckGo error: {exc}"
                    if tavily_error
                    else f"Web search failed. DuckDuckGo error: {exc}"
                )
                _emit_tool_event(tool_name=tool_name, stage='error', error=message)
                raise RuntimeError(message) from exc

            result = json.dumps(payload, ensure_ascii=False)
            _emit_tool_event(
                tool_name=tool_name,
                stage='end',
                provider=payload["provider"],
                result_count=len(payload["results"]),
                output=result[:800],
            )
            return result

        message = tavily_error or "No web search provider is configured."
        _emit_tool_event(tool_name=tool_name, stage='error', error=message)
        raise RuntimeError(message)

    @tool
    def current_utc_time() -> str:
        """Return the current UTC timestamp in ISO-8601 format."""
        tool_name = 'current_utc_time'
        _emit_tool_event(tool_name=tool_name, stage='start')
        try:
            value = datetime.now(timezone.utc).isoformat()
            _emit_tool_event(tool_name=tool_name, stage='end', output=value)
            return value
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc))
            raise

    @tool
    def write_text_artifact(title: str, body: str) -> str:
        """Write a text artifact to disk and return its location."""
        tool_name = 'write_text_artifact'
        _emit_tool_event(tool_name=tool_name, stage='start', title=title)
        try:
            filename = f"{_slugify(title)}.md"
            path = artifact_dir / filename
            _emit_tool_event(tool_name=tool_name, stage='delta', message='Writing artifact to disk', path=str(path))
            path.write_text(f"# {title}\n\n{body}\n", encoding='utf-8')
            result = f"artifact_saved:{path}"
            _emit_tool_event(tool_name=tool_name, stage='end', output=result)
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), title=title)
            raise

    @tool
    def list_files(path: str = ".", pattern: str = "**/*", max_results: int | None = None) -> str:
        """List workspace files under a directory using a glob-like pattern."""
        tool_name = 'list_files'
        _emit_tool_event(tool_name=tool_name, stage='start', path=path, pattern=pattern, max_results=max_results)
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
            _emit_tool_event(tool_name=tool_name, stage='end', result_count=len(matches), output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), path=path)
            raise

    @tool
    def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
        """Read a UTF-8 text file from the workspace with line numbers."""
        tool_name = 'read_file'
        _emit_tool_event(tool_name=tool_name, stage='start', path=path, start_line=start_line, end_line=end_line)
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
            _emit_tool_event(tool_name=tool_name, stage='end', output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), path=path)
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
        tool_name = 'search_code'
        _emit_tool_event(
            tool_name=tool_name,
            stage='start',
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
            _emit_tool_event(tool_name=tool_name, stage='end', result_count=len(matches), output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), query=query, path=path)
            raise

    @tool
    def codebase_stats(path: str = ".", max_files: int | None = None) -> str:
        """Summarize file counts and line counts for the current workspace."""
        tool_name = 'codebase_stats'
        _emit_tool_event(tool_name=tool_name, stage='start', path=path, max_files=max_files)
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
            _emit_tool_event(tool_name=tool_name, stage='end', output=result[:800], files_scanned=file_counter)
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), path=path)
            raise

    @tool
    def git_status() -> str:
        """Inspect the current repository status from the workspace root."""
        tool_name = 'git_status'
        _emit_tool_event(tool_name=tool_name, stage='start')
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
            _emit_tool_event(tool_name=tool_name, stage='end', output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc))
            raise

    @tool
    def git_diff(pathspec: str = "", staged: bool = False, context_lines: int | None = None) -> str:
        """Return a git diff for the workspace, optionally narrowed to one path."""
        tool_name = 'git_diff'
        _emit_tool_event(
            tool_name=tool_name,
            stage='start',
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
            _emit_tool_event(tool_name=tool_name, stage='end', output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), pathspec=pathspec, staged=staged)
            raise

    @tool
    def git_log(limit: int | None = None) -> str:
        """Return recent commits from the current repository."""
        tool_name = 'git_log'
        _emit_tool_event(tool_name=tool_name, stage='start', limit=limit)
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
            _emit_tool_event(tool_name=tool_name, stage='end', result_count=len(commits), output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), limit=limit)
            raise

    @tool
    def web_search(query: str, max_results: int | None = None) -> str:
        """Search the live web with Tavily first and DuckDuckGo as a fallback."""
        requested_results = 5 if max_results is None else int(max_results)
        return _run_web_search(query=query, max_results=requested_results, tool_name='web_search')

    registered_tools = {
        "current_utc_time": current_utc_time,
        "write_text_artifact": write_text_artifact,
        "list_files": list_files,
        "read_file": read_file,
        "search_code": search_code,
        "codebase_stats": codebase_stats,
        "git_status": git_status,
        "git_diff": git_diff,
        "git_log": git_log,
        "web_search": web_search,
    }

    tools: list[Any] = []
    for tool_name in tool_catalog.section_names:
        tool_obj = registered_tools.get(tool_name)
        if tool_obj is None:
            continue
        config = tool_configs[tool_name]
        tool_obj = _apply_tool_metadata(
            tool_obj,
            label=config.label,
            description=config.description,
        )
        if config.enabled:
            tools.append(tool_obj)

    return tools
