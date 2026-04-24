from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import fnmatch
from html.parser import HTMLParser
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable
import unicodedata
from urllib import parse as urllib_parse
from urllib import error as urllib_error
from urllib import request as urllib_request

from langchain.tools import tool
from langgraph.config import get_config, get_stream_writer

from ..config import Settings
from ..core.types import PromptMode
from ..memory import MemoryRetriever, MemoryWriter
from ..memory.models import MemoryKind, MemoryScope, MemoryVisibility, MemoryWriteRequest
from ..memory.retriever import _build_retrieval_query
from ..storage.namespaces import (
    conversation_main_namespace,
    project_memory_namespace,
    root_thread_episodic_namespace,
    user_profile_namespace,
)

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


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = normalized.replace("_", "-")
    normalized = re.sub(r"[^\w\s-]+", "", normalized, flags=re.UNICODE)
    normalized = re.sub(r"[-\s]+", "-", normalized, flags=re.UNICODE)
    return normalized.strip("-") or "artifact"


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


class _ReadableHTMLExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        elif lowered == "title":
            self._in_title = True
        elif lowered in {"p", "div", "br", "li", "section", "article", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        elif lowered == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if self._skip_depth == 0 and not self._in_title:
            self.text_parts.append(text)

    @property
    def title(self) -> str:
        return _collapse_whitespace(" ".join(self.title_parts))

    @property
    def text(self) -> str:
        return _collapse_whitespace("\n".join(self.text_parts))


def _collapse_whitespace(value: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


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


def _parse_namespace(value: str) -> tuple[str, ...]:
    parts = [
        part.strip()
        for part in re.split(r"[:/,]", value)
        if part.strip()
    ]
    if not parts:
        raise ValueError("namespace must not be empty.")
    return tuple(parts)


def _get_current_thread_id() -> str | None:
    try:
        config = get_config()
    except Exception:  # noqa: BLE001
        return None
    configurable = dict(config.get("configurable") or {})
    value = configurable.get("thread_id")
    return str(value) if value else None


def _default_memory_namespaces(
    *,
    user_id: str | None = None,
    root_thread_id: str | None = None,
) -> list[tuple[str, ...]]:
    effective_user_id = (user_id or "default").strip() or "default"
    effective_thread_id = (root_thread_id or _get_current_thread_id() or "").strip()
    namespaces = [
        user_profile_namespace(effective_user_id),
        project_memory_namespace("default"),
    ]
    if effective_thread_id:
        namespaces.append(root_thread_episodic_namespace(effective_thread_id))
        namespaces.append(conversation_main_namespace(effective_thread_id))
    return namespaces


def _resolve_memory_namespace(
    *,
    namespace: str | None,
    kind: MemoryKind,
    scope: MemoryScope,
    user_id: str | None = None,
    root_thread_id: str | None = None,
) -> tuple[str, ...]:
    if namespace and namespace.strip():
        return _parse_namespace(namespace)
    if scope == MemoryScope.PROJECT:
        return project_memory_namespace("default")
    if scope == MemoryScope.ROOT_THREAD:
        effective_thread_id = (root_thread_id or _get_current_thread_id() or "default").strip() or "default"
        if kind == MemoryKind.TURN_SUMMARY:
            return root_thread_episodic_namespace(effective_thread_id)
        return conversation_main_namespace(effective_thread_id)
    return user_profile_namespace((user_id or "default").strip() or "default")


def _coerce_memory_scope(scope: str, *, namespace: str | None = None) -> MemoryScope:
    normalized_scope = scope.strip().lower()
    if normalized_scope == "conversation":
        return MemoryScope.ROOT_THREAD
    if normalized_scope in {MemoryScope.BRANCH.value, MemoryScope.SKILL.value} and not (namespace or "").strip():
        raise ValueError(f"scope={normalized_scope!r} requires an explicit namespace.")
    return MemoryScope(normalized_scope)


def _default_memory_visibility(*, kind: MemoryKind, scope: MemoryScope) -> MemoryVisibility:
    if scope == MemoryScope.USER and kind in {MemoryKind.USER_PREFERENCE, MemoryKind.USER_PROFILE}:
        return MemoryVisibility.SHARED
    if scope == MemoryScope.PROJECT and kind == MemoryKind.PROJECT_FACT:
        return MemoryVisibility.SHARED
    if scope == MemoryScope.BRANCH and kind == MemoryKind.BRANCH_FINDING:
        return MemoryVisibility.PROMOTABLE
    if scope == MemoryScope.ROOT_THREAD and kind in {
        MemoryKind.BRANCH_FINDING,
        MemoryKind.IMPORTED_CONCLUSION,
    }:
        return MemoryVisibility.SHARED
    return MemoryVisibility.PRIVATE


def _json_safe_memory_item(item: Any, *, namespace: tuple[str, ...]) -> dict[str, Any]:
    record = getattr(item, "record", None)
    if record is not None and hasattr(record, "model_dump"):
        value = record.model_dump(mode="json")
        key = getattr(record, "memory_id", None)
    else:
        value = getattr(item, "value", item)
        key = getattr(item, "key", None)
        if not isinstance(value, dict):
            value = {"content": str(value)}
    memory_id = str(value.get("memory_id") or key or "")
    payload = {
        "memory_id": memory_id,
        "namespace": list(value.get("namespace") or namespace),
        "kind": value.get("kind"),
        "scope": value.get("scope"),
        "visibility": value.get("visibility"),
        "content": value.get("content") or "",
        "summary": value.get("summary") or "",
        "tags": value.get("tags") or [],
        "confidence": value.get("confidence"),
        "importance": value.get("importance"),
        "created_at": value.get("created_at"),
        "updated_at": value.get("updated_at"),
    }
    score = getattr(item, "score", None)
    matched_terms = getattr(item, "matched_terms", None)
    if score is not None:
        payload["score"] = float(score)
    if matched_terms:
        payload["matched_terms"] = list(matched_terms)
    return payload



def _resolve_artifact_path(*, artifact_dir: Path, artifact_id: str) -> Path:
    if not artifact_id.strip():
        raise ValueError("artifact_id must not be empty.")
    candidate = Path(artifact_id).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (artifact_dir / candidate).resolve()
    try:
        resolved.relative_to(artifact_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"Artifact path must stay within artifact directory: {artifact_dir}") from exc
    return resolved


def _artifact_title_from_id(artifact_id: str) -> str:
    artifact_path = Path(artifact_id)
    return artifact_path.stem.replace("-", " ").strip().title() or artifact_path.name


def _is_blocked_fetch_host(host: str | None) -> bool:
    if not host:
        return True
    normalized = host.strip().lower().strip("[]")
    if normalized in {"localhost", "localhost.localdomain"} or normalized.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    )


def _extract_checkpoint_state(checkpoint: dict[str, Any] | None) -> dict[str, Any]:
    if not checkpoint:
        return {}
    values = checkpoint.get("channel_values") or {}
    if isinstance(values, dict):
        root = values.get("__root__")
        if isinstance(root, dict):
            return dict(root)
        return dict(values)
    return {}


def _message_role(message: Any) -> str:
    role = getattr(message, "type", None) or getattr(message, "role", None)
    return str(role or type(message).__name__).replace("Message", "").lower()


def _message_content(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def get_default_tools(
    settings: Settings,
    *,
    store=None,
    checkpointer=None,
    artifact_metadata_repository=None,
):
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

    def _require_non_empty_text_arg(args: dict[str, Any], key: str) -> str:
        value = args.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must not be empty.")
        return value.strip()

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

    def _validate_web_fetch_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "url")

    def _validate_web_search_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "query")

    def _validate_write_artifact_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "title")
        _require_non_empty_text_arg(args, "body")

    def _validate_memory_save_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "content")

    def _validate_memory_forget_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "memory_id")

    artifact_metadata_repo = artifact_metadata_repository

    def _get_artifact_metadata_repo():
        nonlocal artifact_metadata_repo
        if artifact_metadata_repo is not None:
            return artifact_metadata_repo
        if not settings.database_uri:
            return None
        from ..repositories.artifact_metadata_repository import ArtifactMetadataRepository

        artifact_metadata_repo = ArtifactMetadataRepository(settings.database_uri)
        artifact_metadata_repo.setup()
        return artifact_metadata_repo

    def _upsert_artifact_metadata(*, thread_id: str | None, artifact_id: str, path: Path, title: str) -> None:
        if not thread_id:
            return
        repo = _get_artifact_metadata_repo()
        if repo is None:
            return
        repo.upsert_from_file(
            thread_id=thread_id,
            artifact_id=artifact_id,
            path=path,
            title=title,
        )

    def _artifact_payload_from_metadata(record: Any) -> dict[str, Any]:
        updated_at = getattr(record, "updated_at", None)
        return {
            "artifact_id": str(getattr(record, "artifact_id")),
            "path": str(getattr(record, "path")),
            "title": str(getattr(record, "title")),
            "size_bytes": int(getattr(record, "size_bytes")),
            "updated_at": (
                updated_at.isoformat()
                if isinstance(updated_at, datetime)
                else str(updated_at or "")
            ),
        }

    def _list_artifacts_from_filesystem(*, limit: int) -> tuple[list[dict[str, Any]], bool]:
        artifacts: list[dict[str, Any]] = []
        truncated = False
        for candidate in sorted(artifact_dir.rglob("*")):
            if not candidate.is_file():
                continue
            try:
                relative = candidate.relative_to(artifact_dir).as_posix()
            except ValueError:
                continue
            stat = candidate.stat()
            artifacts.append(
                {
                    "artifact_id": relative,
                    "path": str(candidate),
                    "title": _artifact_title_from_id(relative),
                    "size_bytes": stat.st_size,
                    "updated_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                }
            )
            if len(artifacts) >= limit:
                truncated = True
                break
        return artifacts, truncated

    def _apply_tool_metadata(
        tool_obj: Any,
        *,
        label: str,
        description: str,
        runtime: dict[str, Any] | None = None,
    ) -> Any:
        tool_obj.description = description
        merged_runtime = dict(runtime or {})
        if hasattr(tool_obj, "metadata") and isinstance(getattr(tool_obj, "metadata"), dict):
            tool_obj.metadata = {**tool_obj.metadata, "display_name": label, **merged_runtime}
        else:
            tool_obj.metadata = {"display_name": label, **merged_runtime}
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

    def _run_web_search_primary(*, query: str, max_results: int, tool_name: str) -> str:
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
        if should_try_tavily and tavily_api_key:
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

        if should_try_tavily and not tavily_api_key:
            message = "Tavily search is configured but the API key is missing."
            _emit_tool_event(tool_name=tool_name, stage='error', error=message, provider='tavily')
            raise RuntimeError(message)

        if preferred_web_search_provider == "duckduckgo":
            payload = _run_duckduckgo_search(query=normalized_query, max_results=capped_results)
            result = json.dumps(payload, ensure_ascii=False)
            _emit_tool_event(
                tool_name=tool_name,
                stage='end',
                provider=payload["provider"],
                result_count=len(payload["results"]),
                output=result[:800],
            )
            return result

        message = "No primary web search provider is configured."
        _emit_tool_event(tool_name=tool_name, stage='error', error=message)
        raise RuntimeError(message)

    def _fallback_web_search(_error: Exception, args: dict[str, Any]) -> str:
        normalized_query = str(args.get("query") or "").strip()
        requested_results = int(args.get("max_results") or 5)
        capped_results = max(1, min(requested_results, 10))
        should_try_duckduckgo = (
            preferred_web_search_provider == "duckduckgo"
            or fallback_web_search_provider == "duckduckgo"
        )
        if not should_try_duckduckgo:
            raise RuntimeError("No fallback web search provider is configured.")
        payload = _run_duckduckgo_search(query=normalized_query, max_results=capped_results)
        result = json.dumps(payload, ensure_ascii=False)
        _emit_tool_event(
            tool_name="web_search",
            stage='delta',
            provider='duckduckgo',
            message='Primary web search failed; using DuckDuckGo fallback.',
            output=result[:800],
        )
        return result

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
            thread_id = _get_current_thread_id()
            display_path = _coerce_relative_posix(path, workspace_root)
            _emit_tool_event(
                tool_name=tool_name,
                stage='delta',
                message='Writing artifact to disk',
                path=display_path,
            )
            path.write_text(f"# {title}\n\n{body}\n", encoding='utf-8')
            _upsert_artifact_metadata(
                thread_id=thread_id,
                artifact_id=filename,
                path=path,
                title=_artifact_title_from_id(filename),
            )
            result = f"artifact_saved:{display_path}"
            _emit_tool_event(tool_name=tool_name, stage='end', output=result)
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), title=title)
            raise

    @tool
    def artifact_list(max_results: int | None = None) -> str:
        """List text artifacts saved in the configured artifact directory."""
        tool_name = 'artifact_list'
        _emit_tool_event(tool_name=tool_name, stage='start', max_results=max_results)
        try:
            requested_results = (
                tool_catalog.artifact_list.default_max_results
                if max_results is None
                else int(max_results)
            )
            capped_results = max(1, min(requested_results, tool_catalog.artifact_list.max_results_cap))
            repo = _get_artifact_metadata_repo()
            thread_id = _get_current_thread_id()
            if repo is not None and thread_id:
                try:
                    metadata_rows = repo.list_by_thread(thread_id, limit=capped_results + 1)
                    truncated = len(metadata_rows) > capped_results
                    artifacts = [
                        _artifact_payload_from_metadata(record)
                        for record in metadata_rows[:capped_results]
                    ]
                except Exception as exc:  # noqa: BLE001
                    _emit_tool_event(
                        tool_name=tool_name,
                        stage='delta',
                        message='Artifact metadata lookup failed; falling back to filesystem.',
                        error=str(exc),
                    )
                    artifacts, truncated = _list_artifacts_from_filesystem(limit=capped_results)
            else:
                artifacts, truncated = _list_artifacts_from_filesystem(limit=capped_results)
            result = json.dumps(
                {
                    "artifact_dir": str(artifact_dir),
                    "artifacts": artifacts,
                    "truncated": truncated,
                },
                ensure_ascii=False,
            )
            _emit_tool_event(tool_name=tool_name, stage='end', result_count=len(artifacts), output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc))
            raise

    @tool
    def artifact_read(artifact_id: str) -> str:
        """Read a saved text artifact by filename or artifact id."""
        tool_name = 'artifact_read'
        _emit_tool_event(tool_name=tool_name, stage='start', artifact_id=artifact_id)
        try:
            path = _resolve_artifact_path(artifact_dir=artifact_dir, artifact_id=artifact_id)
            repo = _get_artifact_metadata_repo()
            if repo is not None:
                try:
                    metadata_record = repo.get_by_artifact_id(artifact_id)
                except Exception as exc:  # noqa: BLE001
                    _emit_tool_event(
                        tool_name=tool_name,
                        stage='delta',
                        message='Artifact metadata lookup failed; reading from filesystem path.',
                        error=str(exc),
                    )
                else:
                    if metadata_record is not None:
                        metadata_path = Path(str(getattr(metadata_record, "path"))).expanduser()
                        if not metadata_path.is_absolute():
                            metadata_path = metadata_path.resolve()
                        try:
                            metadata_path.relative_to(artifact_dir.resolve())
                        except ValueError:
                            pass
                        else:
                            path = metadata_path
            if not path.exists():
                raise FileNotFoundError(artifact_id)
            if path.is_dir():
                raise IsADirectoryError(artifact_id)
            content = _read_text_file(path)
            truncated = len(content) > tool_catalog.artifact_read.max_chars
            payload = {
                "artifact_id": path.relative_to(artifact_dir.resolve()).as_posix(),
                "path": str(path),
                "content": content[: tool_catalog.artifact_read.max_chars],
                "truncated": truncated,
            }
            result = json.dumps(payload, ensure_ascii=False)
            _emit_tool_event(tool_name=tool_name, stage='end', output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), artifact_id=artifact_id)
            raise

    @tool
    def artifact_update(artifact_id: str, body: str, mode: str = "replace") -> str:
        """Replace, append to, or prepend content in an existing text artifact."""
        tool_name = 'artifact_update'
        _emit_tool_event(tool_name=tool_name, stage='start', artifact_id=artifact_id, mode=mode)
        try:
            path = _resolve_artifact_path(artifact_dir=artifact_dir, artifact_id=artifact_id)
            if not path.exists():
                raise FileNotFoundError(artifact_id)
            if path.is_dir():
                raise IsADirectoryError(artifact_id)
            existing = _read_text_file(path)
            normalized_mode = mode.strip().lower()
            if normalized_mode == "replace":
                updated = body
            elif normalized_mode == "append":
                separator = "" if existing.endswith("\n") or not existing else "\n"
                updated = f"{existing}{separator}{body}"
            elif normalized_mode == "prepend":
                separator = "" if body.endswith("\n") or not existing else "\n"
                updated = f"{body}{separator}{existing}"
            else:
                raise ValueError("mode must be one of: replace, append, prepend.")
            path.write_text(updated, encoding="utf-8")
            relative_artifact_id = path.relative_to(artifact_dir.resolve()).as_posix()
            _upsert_artifact_metadata(
                thread_id=_get_current_thread_id(),
                artifact_id=relative_artifact_id,
                path=artifact_dir / relative_artifact_id,
                title=_artifact_title_from_id(relative_artifact_id),
            )
            payload = {
                "artifact_id": relative_artifact_id,
                "path": str(path),
                "mode": normalized_mode,
                "size_bytes": path.stat().st_size,
            }
            result = json.dumps(payload, ensure_ascii=False)
            _emit_tool_event(tool_name=tool_name, stage='end', output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), artifact_id=artifact_id)
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
    def web_fetch(url: str, max_chars: int | None = None) -> str:
        """Fetch and extract readable text from a user-provided HTTP or HTTPS URL."""
        tool_name = 'web_fetch'
        _emit_tool_event(tool_name=tool_name, stage='start', url=url, max_chars=max_chars)
        try:
            parsed = urllib_parse.urlparse(url.strip())
            if parsed.scheme not in {"http", "https"}:
                raise ValueError("Only http and https URLs are supported.")
            if _is_blocked_fetch_host(parsed.hostname):
                raise ValueError("Refusing to fetch localhost, private, reserved, or link-local hosts.")
            requested_chars = (
                tool_catalog.web_fetch.default_max_chars
                if max_chars is None
                else int(max_chars)
            )
            capped_chars = max(1, min(requested_chars, tool_catalog.web_fetch.max_chars_cap))
            request = urllib_request.Request(
                urllib_parse.urlunparse(parsed),
                headers={"User-Agent": "FocusAgent/1.0 (+https://example.local/focus-agent)"},
                method="GET",
            )
            with urllib_request.urlopen(request, timeout=30) as response:
                raw = response.read(min(capped_chars * 4, tool_catalog.web_fetch.max_chars_cap * 4))
                final_url = response.geturl() if hasattr(response, "geturl") else urllib_parse.urlunparse(parsed)
                headers = getattr(response, "headers", {}) or {}
                content_type = headers.get("content-type", "") if hasattr(headers, "get") else ""
                charset = (
                    headers.get_content_charset()
                    if hasattr(headers, "get_content_charset")
                    else None
                ) or "utf-8"
            decoded = raw.decode(charset, errors="replace")
            title = ""
            if "html" in content_type.lower() or "<html" in decoded[:500].lower():
                parser = _ReadableHTMLExtractor()
                parser.feed(decoded)
                title = parser.title
                content = parser.text
            else:
                content = _collapse_whitespace(decoded)
            truncated = len(content) > capped_chars
            payload = {
                "url": url,
                "final_url": final_url,
                "title": title,
                "content_type": content_type,
                "content": content[:capped_chars],
                "truncated": truncated,
            }
            result = json.dumps(payload, ensure_ascii=False)
            _emit_tool_event(tool_name=tool_name, stage='end', output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), url=url)
            raise

    @tool
    def memory_save(
        content: str,
        kind: str = "user_preference",
        scope: str = "user",
        namespace: str | None = None,
        summary: str = "",
        tags: list[str] | None = None,
        user_id: str | None = None,
        root_thread_id: str | None = None,
        confidence: float | None = None,
        importance: float = 0.6,
    ) -> str:
        """Save an explicit durable memory such as a user preference or project fact."""
        tool_name = 'memory_save'
        _emit_tool_event(tool_name=tool_name, stage='start', kind=kind, scope=scope, namespace=namespace)
        try:
            if store is None:
                raise RuntimeError("Memory store is not configured.")
            if not content.strip():
                raise ValueError("content must not be empty.")
            memory_kind = MemoryKind(kind.strip())
            memory_scope = _coerce_memory_scope(scope, namespace=namespace)
            resolved_namespace = _resolve_memory_namespace(
                namespace=namespace,
                kind=memory_kind,
                scope=memory_scope,
                user_id=user_id,
                root_thread_id=root_thread_id,
            )
            record = MemoryWriteRequest(
                kind=memory_kind,
                scope=memory_scope,
                visibility=_default_memory_visibility(kind=memory_kind, scope=memory_scope),
                namespace=resolved_namespace,
                content=content.strip(),
                summary=(summary or content).strip()[:240],
                tags=tags or [],
                root_thread_id=root_thread_id or _get_current_thread_id(),
                user_id=(user_id or "default").strip() or "default",
                confidence=confidence,
                importance=importance,
            )
            action, memory_id = MemoryWriter(store=store)._upsert_record(record)
            payload = {
                "memory_id": memory_id,
                "namespace": list(resolved_namespace),
                "kind": memory_kind.value,
                "scope": memory_scope.value,
                "visibility": record.visibility.value,
                "saved": action in {"written", "merged"},
                "action": action,
            }
            result = json.dumps(payload, ensure_ascii=False)
            _emit_tool_event(tool_name=tool_name, stage='end', output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc))
            raise

    @tool
    def memory_search(
        query: str,
        namespace: str | None = None,
        user_id: str | None = None,
        root_thread_id: str | None = None,
        limit: int | None = None,
    ) -> str:
        """Search durable memories by query across the default memory namespaces."""
        tool_name = 'memory_search'
        _emit_tool_event(tool_name=tool_name, stage='start', query=query, namespace=namespace, limit=limit)
        try:
            if store is None:
                raise RuntimeError("Memory store is not configured.")
            if not query.strip():
                raise ValueError("query must not be empty.")
            requested_limit = (
                tool_catalog.memory_search.default_limit
                if limit is None
                else int(limit)
            )
            capped_limit = max(1, min(requested_limit, tool_catalog.memory_search.max_limit))
            search_limit = min(
                tool_catalog.memory_search.max_limit,
                max(capped_limit, tool_catalog.memory_search.default_limit),
            )
            namespaces = (
                [_parse_namespace(namespace)]
                if namespace and namespace.strip()
                else _default_memory_namespaces(user_id=user_id, root_thread_id=root_thread_id)
            )
            effective_query = _build_retrieval_query(
                query=query.strip(),
                state={},
                prompt_mode=PromptMode.EXPLORE,
            )
            retriever = MemoryRetriever(store=store, default_limit=search_limit)
            hits = []
            for candidate_namespace in namespaces:
                hits.extend(
                    retriever._search_namespace(
                        candidate_namespace,
                        effective_query,
                        limit=search_limit,
                    )
                )
            reranked_hits = retriever._rerank_hits(
                hits,
                query=effective_query,
                prompt_mode=PromptMode.EXPLORE,
            )
            deduped_hits = retriever._dedupe_hits(reranked_hits)
            results = [
                _json_safe_memory_item(item, namespace=item.namespace)
                for item in deduped_hits[:capped_limit]
            ]
            payload = {
                "query": query,
                "namespaces": [list(item) for item in namespaces],
                "results": results,
                "truncated": len(deduped_hits) > capped_limit,
            }
            result = json.dumps(payload, ensure_ascii=False)
            _emit_tool_event(tool_name=tool_name, stage='end', result_count=len(results), output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), query=query)
            raise

    @tool
    def memory_forget(
        memory_id: str,
        namespace: str | None = None,
        user_id: str | None = None,
        root_thread_id: str | None = None,
    ) -> str:
        """Delete a saved memory by id from an explicit or default memory namespace."""
        tool_name = 'memory_forget'
        _emit_tool_event(tool_name=tool_name, stage='start', memory_id=memory_id, namespace=namespace)
        try:
            if store is None:
                raise RuntimeError("Memory store is not configured.")
            normalized_id = memory_id.strip()
            if not normalized_id:
                raise ValueError("memory_id must not be empty.")
            namespaces = (
                [_parse_namespace(namespace)]
                if namespace and namespace.strip()
                else _default_memory_namespaces(user_id=user_id, root_thread_id=root_thread_id)
            )
            deleted_namespace: tuple[str, ...] | None = None
            for candidate_namespace in namespaces:
                if store.get(candidate_namespace, normalized_id) is None:
                    continue
                store.delete(candidate_namespace, normalized_id)
                deleted_namespace = candidate_namespace
                break
            payload = {
                "memory_id": normalized_id,
                "deleted": deleted_namespace is not None,
                "namespace": list(deleted_namespace) if deleted_namespace else None,
                "searched_namespaces": [list(item) for item in namespaces],
            }
            result = json.dumps(payload, ensure_ascii=False)
            _emit_tool_event(tool_name=tool_name, stage='end', output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), memory_id=memory_id)
            raise

    @tool
    def conversation_summary(thread_id: str = "", recent_messages: int | None = None) -> str:
        """Return the latest saved rolling summary and recent messages for a thread."""
        tool_name = 'conversation_summary'
        _emit_tool_event(tool_name=tool_name, stage='start', thread_id=thread_id, recent_messages=recent_messages)
        try:
            if checkpointer is None:
                raise RuntimeError("Conversation checkpointer is not configured.")
            effective_thread_id = thread_id.strip() or _get_current_thread_id()
            if not effective_thread_id:
                raise ValueError("thread_id is required outside an active graph run.")
            requested_messages = (
                tool_catalog.conversation_summary.default_recent_messages
                if recent_messages is None
                else int(recent_messages)
            )
            capped_messages = max(
                0,
                min(requested_messages, tool_catalog.conversation_summary.max_recent_messages),
            )
            checkpoint = checkpointer.get({"configurable": {"thread_id": effective_thread_id}})
            state = _extract_checkpoint_state(checkpoint)
            messages = list(state.get("messages", []) or [])
            recent = [
                {
                    "role": _message_role(message),
                    "content": _message_content(message)[:1200],
                }
                for message in messages[-capped_messages:]
            ]
            payload = {
                "thread_id": effective_thread_id,
                "rolling_summary": state.get("rolling_summary", ""),
                "task_brief": state.get("task_brief", ""),
                "branch_meta": state.get("branch_meta"),
                "active_skill_ids": state.get("active_skill_ids", []),
                "message_count": len(messages),
                "recent_messages": recent,
            }
            result = json.dumps(payload, ensure_ascii=False)
            _emit_tool_event(tool_name=tool_name, stage='end', output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            _emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), thread_id=thread_id)
            raise

    @tool
    def web_search(query: str, max_results: int | None = None) -> str:
        """Search the live web with Tavily first and DuckDuckGo as a fallback."""
        requested_results = 5 if max_results is None else int(max_results)
        return _run_web_search_primary(query=query, max_results=requested_results, tool_name='web_search')

    registered_tools = {
        "current_utc_time": current_utc_time,
        "write_text_artifact": write_text_artifact,
        "artifact_list": artifact_list,
        "artifact_read": artifact_read,
        "artifact_update": artifact_update,
        "list_files": list_files,
        "read_file": read_file,
        "search_code": search_code,
        "codebase_stats": codebase_stats,
        "git_status": git_status,
        "git_diff": git_diff,
        "git_log": git_log,
        "web_fetch": web_fetch,
        "memory_save": memory_save,
        "memory_search": memory_search,
        "memory_forget": memory_forget,
        "conversation_summary": conversation_summary,
        "web_search": web_search,
    }
    tool_runtime_metadata: dict[str, dict[str, Any]] = {
        "current_utc_time": {
            "parallel_safe": True,
            "max_observation_chars": 256,
        },
        "write_text_artifact": {
            "side_effect": True,
            "validator": _validate_write_artifact_args,
            "max_observation_chars": 512,
        },
        "artifact_list": {
            "parallel_safe": True,
            "max_observation_chars": 6000,
        },
        "artifact_read": {
            "parallel_safe": True,
            "max_observation_chars": 8000,
        },
        "artifact_update": {
            "side_effect": True,
            "max_observation_chars": 512,
        },
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
        "web_fetch": {
            "parallel_safe": True,
            "validator": _validate_web_fetch_args,
            "max_observation_chars": 7000,
        },
        "memory_save": {
            "side_effect": True,
            "validator": _validate_memory_save_args,
            "max_observation_chars": 800,
        },
        "memory_search": {
            "parallel_safe": True,
            "max_observation_chars": 6000,
        },
        "memory_forget": {
            "side_effect": True,
            "validator": _validate_memory_forget_args,
            "max_observation_chars": 800,
        },
        "conversation_summary": {
            "parallel_safe": True,
            "cacheable": True,
            "cache_scope": "thread",
            "max_observation_chars": 4000,
        },
        "web_search": {
            "parallel_safe": True,
            "validator": _validate_web_search_args,
            "fallback_group": "web_search",
            "fallback_handler": _fallback_web_search,
            "max_observation_chars": 7000,
        },
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
            runtime=tool_runtime_metadata.get(tool_name),
        )
        if config.enabled:
            tools.append(tool_obj)

    return tools
