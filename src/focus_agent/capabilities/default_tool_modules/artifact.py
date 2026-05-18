from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain.tools import tool

from .common import _coerce_relative_posix, _read_text_file, _require_non_empty_text_arg


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = normalized.replace("_", "-")
    normalized = re.sub(r"[^\w\s-]+", "", normalized, flags=re.UNICODE)
    normalized = re.sub(r"[-\s]+", "-", normalized, flags=re.UNICODE)
    return normalized.strip("-") or "artifact"


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


def build_artifact_tools(
    *,
    artifact_dir: Path,
    workspace_root: Path,
    settings: Any,
    tool_catalog: Any,
    artifact_metadata_repository: Any,
    emit_tool_event: Callable[..., None],
    get_current_thread_id: Callable[[], str | None],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    def _validate_write_artifact_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "title")
        _require_non_empty_text_arg(args, "body")

    artifact_metadata_repo = artifact_metadata_repository

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
                    "updated_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
                }
            )
            if len(artifacts) >= limit:
                truncated = True
                break
        return artifacts, truncated

    @tool
    def write_text_artifact(title: str, body: str) -> str:
        """Write a text artifact to disk and return its location."""
        tool_name = 'write_text_artifact'
        emit_tool_event(tool_name=tool_name, stage='start', title=title)
        try:
            filename = f"{_slugify(title)}.md"
            path = artifact_dir / filename
            thread_id = get_current_thread_id()
            display_path = _coerce_relative_posix(path, workspace_root)
            emit_tool_event(
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
            emit_tool_event(tool_name=tool_name, stage='end', output=result)
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), title=title)
            raise

    @tool
    def artifact_list(max_results: int | None = None) -> str:
        """List text artifacts saved in the configured artifact directory."""
        tool_name = 'artifact_list'
        emit_tool_event(tool_name=tool_name, stage='start', max_results=max_results)
        try:
            requested_results = (
                tool_catalog.artifact_list.default_max_results
                if max_results is None
                else int(max_results)
            )
            capped_results = max(1, min(requested_results, tool_catalog.artifact_list.max_results_cap))
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
            emit_tool_event(tool_name=tool_name, stage='end', result_count=len(artifacts), output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage='error', error=str(exc))
            raise

    @tool
    def artifact_read(artifact_id: str) -> str:
        """Read a saved text artifact by filename or artifact id."""
        tool_name = 'artifact_read'
        emit_tool_event(tool_name=tool_name, stage='start', artifact_id=artifact_id)
        try:
            path = _resolve_artifact_path(artifact_dir=artifact_dir, artifact_id=artifact_id)
            repo = _get_artifact_metadata_repo()
            if repo is not None:
                try:
                    metadata_record = repo.get_by_artifact_id(artifact_id)
                except Exception as exc:  # noqa: BLE001
                    emit_tool_event(
                        tool_name=tool_name,
                        stage='delta',
                        message='Artifact metadata lookup failed; reading from filesystem path.',
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
            emit_tool_event(tool_name=tool_name, stage='end', output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), artifact_id=artifact_id)
            raise

    @tool
    def artifact_update(artifact_id: str, body: str, mode: str = "replace") -> str:
        """Replace, append to, or prepend content in an existing text artifact."""
        tool_name = 'artifact_update'
        emit_tool_event(tool_name=tool_name, stage='start', artifact_id=artifact_id, mode=mode)
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
            emit_tool_event(tool_name=tool_name, stage='end', output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage='error', error=str(exc), artifact_id=artifact_id)
            raise

    return (
        {
            "write_text_artifact": write_text_artifact,
            "artifact_list": artifact_list,
            "artifact_read": artifact_read,
            "artifact_update": artifact_update,
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
        },
    )
