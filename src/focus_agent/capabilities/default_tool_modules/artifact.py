from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain.tools import tool

from ...retrieval.artifacts import artifact_content_hash, index_artifact_content
from ...storage import LocalArtifactStore
from .common import _coerce_relative_posix, _require_non_empty_text_arg


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = normalized.replace("_", "-")
    normalized = re.sub(r"[^\w\s-]+", "", normalized, flags=re.UNICODE)
    normalized = re.sub(r"[-\s]+", "-", normalized, flags=re.UNICODE)
    return normalized.strip("-") or "artifact"


def _artifact_title_from_id(artifact_id: str) -> str:
    artifact_path = Path(artifact_id)
    return artifact_path.stem.replace("-", " ").strip().title() or artifact_path.name


def build_artifact_tools(
    *,
    artifact_dir: Path,
    workspace_root: Path,
    settings: Any,
    tool_catalog: Any,
    artifact_store: Any,
    artifact_metadata_repository: Any,
    memory_embedding_service: Any = None,
    retrieval_index: Any = None,
    emit_tool_event: Callable[..., None],
    get_current_thread_id: Callable[[], str | None],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    def _validate_write_artifact_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "title")
        _require_non_empty_text_arg(args, "body")

    artifact_metadata_repo = artifact_metadata_repository
    store = artifact_store or LocalArtifactStore(artifact_dir)

    def _artifact_path_for(artifact_id: str) -> Path:
        if hasattr(store, "path_for"):
            return store.path_for(artifact_id)
        return Path(store.url(artifact_id)).expanduser().resolve()

    def _artifact_id_for_path(path: Path) -> str:
        if hasattr(store, "artifact_id_for_path"):
            return store.artifact_id_for_path(path)
        return path.relative_to(artifact_dir.resolve()).as_posix()

    def _get_artifact_metadata_repo():
        nonlocal artifact_metadata_repo
        if artifact_metadata_repo is not None:
            return artifact_metadata_repo
        if not settings.database_uri:
            return None
        from ...repositories.artifact_metadata_repository import ArtifactMetadataRepository

        artifact_metadata_repo = ArtifactMetadataRepository(settings.database_uri)
        artifact_metadata_repo.setup()
        return artifact_metadata_repo

    def _upsert_artifact_metadata(
        *, thread_id: str | None, artifact_id: str, path: Path, title: str
    ) -> None:
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

    def _index_artifact_best_effort(
        *,
        artifact_id: str,
        title: str,
        content: str,
        thread_id: str | None,
    ) -> None:
        index = retrieval_index
        provider = getattr(memory_embedding_service, "provider", None)
        if index is None or provider is None:
            return

        try:
            index_artifact_content(
                retrieval_index=index,
                embedding_provider=provider,
                artifact_id=artifact_id,
                title=title,
                content=content,
                thread_id=thread_id,
            )
        except Exception:  # noqa: BLE001
            return

    def _search_artifacts_from_filesystem(*, query: str, limit: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        terms = _query_terms(query)
        artifact_iter = (
            store.iter_artifacts()
            if hasattr(store, "iter_artifacts")
            else LocalArtifactStore(artifact_dir).iter_artifacts()
        )
        for item in artifact_iter:
            try:
                content = store.load(item.artifact_id).decode("utf-8")
            except Exception:  # noqa: BLE001
                continue
            score, snippet = _artifact_text_match(query=query, terms=terms, content=content)
            if score <= 0:
                continue
            results.append(
                {
                    "artifact_id": item.artifact_id,
                    "title": _artifact_title_from_id(item.artifact_id),
                    "path": str(item.path),
                    "snippet": snippet,
                    "score": score,
                    "backend": "filesystem",
                }
            )
        results.sort(key=lambda item: (-float(item["score"]), str(item["artifact_id"])))
        return results[:limit]

    def _search_artifacts_from_index(*, query: str, limit: int) -> list[dict[str, Any]]:
        index = retrieval_index
        provider = getattr(memory_embedding_service, "provider", None)
        if index is None or provider is None:
            return []
        vector = provider.embed([query])[0]
        hits = index.search(
            collection="focus_artifact_chunks",
            query=query,
            vector=vector,
            limit=limit,
        )
        results: list[dict[str, Any]] = []
        for hit in hits:
            artifact_id = str(hit.fields.get("artifact_id") or hit.source_id)
            try:
                content = store.load(artifact_id).decode("utf-8")
            except Exception:  # noqa: BLE001
                continue
            expected_hash = str(hit.fields.get("artifact_hash") or "")
            if expected_hash and expected_hash != artifact_content_hash(content):
                continue
            results.append(
                {
                    "artifact_id": artifact_id,
                    "title": str(hit.fields.get("title") or _artifact_title_from_id(hit.source_id)),
                    "chunk_index": hit.fields.get("chunk_index"),
                    "snippet": hit.text[:600],
                    "score": hit.score,
                    "backend": "zvec",
                }
            )
        return results

    def _artifact_payload_from_metadata(record: Any) -> dict[str, Any]:
        updated_at = getattr(record, "updated_at", None)
        return {
            "artifact_id": str(record.artifact_id),
            "path": str(record.path),
            "title": str(record.title),
            "size_bytes": int(record.size_bytes),
            "updated_at": (
                updated_at.isoformat()
                if isinstance(updated_at, datetime)
                else str(updated_at or "")
            ),
        }

    def _list_artifacts_from_filesystem(*, limit: int) -> tuple[list[dict[str, Any]], bool]:
        artifacts: list[dict[str, Any]] = []
        truncated = False
        artifact_iter = (
            store.iter_artifacts()
            if hasattr(store, "iter_artifacts")
            else LocalArtifactStore(artifact_dir).iter_artifacts()
        )
        for item in artifact_iter:
            artifacts.append(
                {
                    "artifact_id": item.artifact_id,
                    "path": str(item.path),
                    "title": _artifact_title_from_id(item.artifact_id),
                    "size_bytes": item.size_bytes,
                    "updated_at": item.updated_at.isoformat(),
                }
            )
            if len(artifacts) >= limit:
                truncated = True
                break
        return artifacts, truncated

    @tool
    def write_text_artifact(title: str, body: str) -> str:
        """Write a text artifact to disk and return its location."""
        tool_name = "write_text_artifact"
        emit_tool_event(tool_name=tool_name, stage="start", title=title)
        try:
            filename = f"{_slugify(title)}.md"
            thread_id = get_current_thread_id()
            path = _artifact_path_for(filename)
            display_path = _coerce_relative_posix(path, workspace_root)
            emit_tool_event(
                tool_name=tool_name,
                stage="delta",
                message="Writing artifact to disk",
                path=display_path,
            )
            store.save(filename, f"# {title}\n\n{body}\n".encode())
            _index_artifact_best_effort(
                artifact_id=filename,
                title=_artifact_title_from_id(filename),
                content=f"# {title}\n\n{body}\n",
                thread_id=thread_id,
            )
            _upsert_artifact_metadata(
                thread_id=thread_id,
                artifact_id=filename,
                path=path,
                title=_artifact_title_from_id(filename),
            )
            result = f"artifact_saved:{display_path}"
            emit_tool_event(tool_name=tool_name, stage="end", output=result)
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), title=title)
            raise

    @tool
    def artifact_list(max_results: int | None = None) -> str:
        """List text artifacts saved in the configured artifact directory."""
        tool_name = "artifact_list"
        emit_tool_event(tool_name=tool_name, stage="start", max_results=max_results)
        try:
            requested_results = (
                tool_catalog.artifact_list.default_max_results
                if max_results is None
                else int(max_results)
            )
            capped_results = max(
                1, min(requested_results, tool_catalog.artifact_list.max_results_cap)
            )
            repo = _get_artifact_metadata_repo()
            thread_id = get_current_thread_id()
            if repo is not None and thread_id:
                try:
                    metadata_rows = repo.list_by_thread(thread_id, limit=capped_results + 1)
                    truncated = len(metadata_rows) > capped_results
                    artifacts = [
                        _artifact_payload_from_metadata(record)
                        for record in metadata_rows[:capped_results]
                    ]
                except Exception as exc:  # noqa: BLE001
                    emit_tool_event(
                        tool_name=tool_name,
                        stage="delta",
                        message="Artifact metadata lookup failed; falling back to filesystem.",
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
            emit_tool_event(
                tool_name=tool_name, stage="end", result_count=len(artifacts), output=result[:800]
            )
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc))
            raise

    @tool
    def artifact_read(artifact_id: str) -> str:
        """Read a saved text artifact by filename or artifact id."""
        tool_name = "artifact_read"
        emit_tool_event(tool_name=tool_name, stage="start", artifact_id=artifact_id)
        try:
            read_artifact_id = artifact_id
            path = _artifact_path_for(read_artifact_id)
            repo = _get_artifact_metadata_repo()
            if repo is not None:
                try:
                    metadata_record = repo.get_by_artifact_id(artifact_id)
                except Exception as exc:  # noqa: BLE001
                    emit_tool_event(
                        tool_name=tool_name,
                        stage="delta",
                        message="Artifact metadata lookup failed; reading from filesystem path.",
                        error=str(exc),
                    )
                else:
                    if metadata_record is not None:
                        metadata_path = Path(str(metadata_record.path)).expanduser()
                        if not metadata_path.is_absolute():
                            metadata_path = metadata_path.resolve()
                        try:
                            metadata_path.relative_to(artifact_dir.resolve())
                        except ValueError:
                            pass
                        else:
                            read_artifact_id = _artifact_id_for_path(metadata_path)
                            path = metadata_path
            if not store.exists(read_artifact_id):
                raise FileNotFoundError(artifact_id)
            if path.is_dir():
                raise IsADirectoryError(artifact_id)
            content = store.load(read_artifact_id).decode("utf-8")
            truncated = len(content) > tool_catalog.artifact_read.max_chars
            payload = {
                "artifact_id": _artifact_id_for_path(path),
                "path": str(path),
                "content": content[: tool_catalog.artifact_read.max_chars],
                "truncated": truncated,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(
                tool_name=tool_name, stage="error", error=str(exc), artifact_id=artifact_id
            )
            raise

    @tool
    def artifact_update(artifact_id: str, body: str, mode: str = "replace") -> str:
        """Replace, append to, or prepend content in an existing text artifact."""
        tool_name = "artifact_update"
        emit_tool_event(tool_name=tool_name, stage="start", artifact_id=artifact_id, mode=mode)
        try:
            path = _artifact_path_for(artifact_id)
            if not store.exists(artifact_id):
                raise FileNotFoundError(artifact_id)
            if path.is_dir():
                raise IsADirectoryError(artifact_id)
            existing = store.load(artifact_id).decode("utf-8")
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
            relative_artifact_id = _artifact_id_for_path(path)
            store.save(relative_artifact_id, updated.encode("utf-8"))
            path = _artifact_path_for(relative_artifact_id)
            _index_artifact_best_effort(
                artifact_id=relative_artifact_id,
                title=_artifact_title_from_id(relative_artifact_id),
                content=updated,
                thread_id=get_current_thread_id(),
            )
            _upsert_artifact_metadata(
                thread_id=get_current_thread_id(),
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
            emit_tool_event(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(
                tool_name=tool_name, stage="error", error=str(exc), artifact_id=artifact_id
            )
            raise

    @tool
    def artifact_search(query: str, limit: int | None = None) -> str:
        """Search saved text artifact chunks."""
        tool_name = "artifact_search"
        emit_tool_event(tool_name=tool_name, stage="start", query=query, limit=limit)
        try:
            if not query.strip():
                raise ValueError("query must not be empty.")
            requested_limit = (
                tool_catalog.artifact_search.default_limit if limit is None else int(limit)
            )
            capped_limit = max(1, min(requested_limit, tool_catalog.artifact_search.max_limit))
            try:
                results = _search_artifacts_from_index(query=query, limit=capped_limit)
            except Exception as exc:  # noqa: BLE001
                emit_tool_event(
                    tool_name=tool_name,
                    stage="delta",
                    message="Artifact retrieval index failed; falling back to filesystem.",
                    error=str(exc),
                )
                results = []
            if not results:
                results = _search_artifacts_from_filesystem(query=query, limit=capped_limit)
            payload = {"query": query, "results": results, "truncated": False}
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(
                tool_name=tool_name, stage="end", result_count=len(results), output=result[:800]
            )
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), query=query)
            raise

    return (
        {
            "write_text_artifact": write_text_artifact,
            "artifact_list": artifact_list,
            "artifact_read": artifact_read,
            "artifact_update": artifact_update,
            "artifact_search": artifact_search,
        },
        {
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
            "artifact_search": {
                "parallel_safe": True,
                "max_observation_chars": 6000,
            },
        },
    )


def _query_terms(query: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]+", query.lower())))


def _artifact_text_match(*, query: str, terms: tuple[str, ...], content: str) -> tuple[float, str]:
    lowered = content.lower()
    matched = [term for term in terms if term and term in lowered]
    if not matched:
        return (1.0, _snippet(content, query)) if query.lower() in lowered else (0.0, "")
    score = len(matched) / max(1, len(terms))
    return score, _snippet(content, matched[0])


def _snippet(content: str, needle: str, *, radius: int = 160) -> str:
    index = content.lower().find(needle.lower())
    if index < 0:
        return content[: radius * 2]
    start = max(0, index - radius)
    end = min(len(content), index + len(needle) + radius)
    return content[start:end]
