from __future__ import annotations

from typing import Any
from uuid import uuid4

from focus_agent.core.productivity import (
    FocusNote,
    FocusNoteStatus,
    FocusTask,
    FocusTaskEventKind,
    FocusTaskStatus,
)
from focus_agent.repositories.productivity_repository import (
    ProductivityRepository,
    _format_time,
    _normalize_tags,
    _task_event,
)


class ProductivityService:
    def __init__(self, repository: ProductivityRepository):
        self.repository = repository

    def create_note(
        self,
        *,
        user_id: str,
        title: str,
        body: str = "",
        tags: list[str] | None = None,
        source_thread_id: str | None = None,
        source_artifact_id: str | None = None,
        source_kind: str | None = None,
        source_id: str | None = None,
        source_url: str | None = None,
        pinned_context: dict[str, object] | None = None,
        captured_from: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> FocusNote:
        now = _format_time()
        note = FocusNote(
            note_id=f"note-{uuid4().hex}",
            user_id=user_id,
            title=_require_title(title),
            body=str(body or ""),
            tags=_normalize_tags(tags),
            source_thread_id=_normalize_optional_id(source_thread_id),
            source_artifact_id=_normalize_optional_id(source_artifact_id),
            source_kind=_normalize_optional_id(source_kind),
            source_id=_normalize_optional_id(source_id),
            source_url=_normalize_optional_id(source_url),
            pinned_context=dict(pinned_context or {}),
            captured_from=_normalize_optional_id(captured_from),
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )
        self.repository.create_note(note)
        return note

    def update_note(
        self,
        *,
        note_id: str,
        user_id: str,
        title: str | None = None,
        body: str | None = None,
        tags: list[str] | None = None,
        status: FocusNoteStatus | str | None = None,
        source_thread_id: str | None = None,
        source_artifact_id: str | None = None,
        source_kind: str | None = None,
        source_id: str | None = None,
        source_url: str | None = None,
        pinned_context: dict[str, object] | None = None,
        captured_from: str | None = None,
        is_archived: bool | None = None,
        metadata: dict[str, object] | None = None,
    ) -> FocusNote | None:
        note = self.repository.get_note(note_id=note_id, user_id=user_id)
        if note is None:
            return None
        normalized_status = FocusNoteStatus(status) if status is not None else note.status
        if is_archived is not None:
            normalized_status = FocusNoteStatus.ARCHIVED if is_archived else FocusNoteStatus.ACTIVE
        next_is_archived = normalized_status == FocusNoteStatus.ARCHIVED
        archived_at = note.archived_at
        if next_is_archived and not note.is_archived:
            archived_at = _format_time()
        elif not next_is_archived:
            archived_at = None
        updated = note.model_copy(
            update={
                key: value
                for key, value in {
                    "title": _require_title(title) if title is not None else None,
                    "body": str(body) if body is not None else None,
                    "tags": _normalize_tags(tags) if tags is not None else None,
                    "status": normalized_status if (status is not None or is_archived is not None) else None,
                    "source_thread_id": _normalize_optional_id(source_thread_id)
                    if source_thread_id is not None
                    else None,
                    "source_artifact_id": _normalize_optional_id(source_artifact_id)
                    if source_artifact_id is not None
                    else None,
                    "source_kind": _normalize_optional_id(source_kind)
                    if source_kind is not None
                    else None,
                    "source_id": _normalize_optional_id(source_id) if source_id is not None else None,
                    "source_url": _normalize_optional_id(source_url)
                    if source_url is not None
                    else None,
                    "pinned_context": dict(pinned_context or {})
                    if pinned_context is not None
                    else None,
                    "captured_from": _normalize_optional_id(captured_from)
                    if captured_from is not None
                    else None,
                    "is_archived": next_is_archived if (status is not None or is_archived is not None) else None,
                    "metadata": dict(metadata or {}) if metadata is not None else None,
                    "archived_at": archived_at,
                    "updated_at": _format_time(),
                }.items()
                if value is not None
            }
        )
        self.repository.save_note(updated)
        return updated

    def create_task(
        self,
        *,
        user_id: str,
        title: str,
        description: str = "",
        due_at: str | None = None,
        priority: int | None = None,
        source_thread_id: str | None = None,
        source_note_id: str | None = None,
        source_artifact_id: str | None = None,
        source_kind: str | None = None,
        source_id: str | None = None,
        source_url: str | None = None,
        pinned_context: dict[str, object] | None = None,
        captured_from: str | None = None,
        assignee_user_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> FocusTask:
        now = _format_time()
        task = FocusTask(
            task_id=f"task-{uuid4().hex}",
            user_id=user_id,
            title=_require_title(title),
            description=str(description or ""),
            due_at=due_at,
            priority=priority,
            source_thread_id=_normalize_optional_id(source_thread_id),
            source_note_id=_normalize_optional_id(source_note_id),
            source_artifact_id=_normalize_optional_id(source_artifact_id),
            source_kind=_normalize_optional_id(source_kind),
            source_id=_normalize_optional_id(source_id),
            source_url=_normalize_optional_id(source_url),
            pinned_context=dict(pinned_context or {}),
            captured_from=_normalize_optional_id(captured_from),
            assignee_user_id=_normalize_optional_id(assignee_user_id),
            tags=_normalize_tags(tags),
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )
        self.repository.create_task(task)
        return task

    def update_task(
        self,
        *,
        task_id: str,
        user_id: str,
        title: str | None = None,
        description: str | None = None,
        status: FocusTaskStatus | str | None = None,
        due_at: str | None = None,
        priority: int | None = None,
        source_thread_id: str | None = None,
        source_note_id: str | None = None,
        source_artifact_id: str | None = None,
        source_kind: str | None = None,
        source_id: str | None = None,
        source_url: str | None = None,
        pinned_context: dict[str, object] | None = None,
        captured_from: str | None = None,
        assignee_user_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> FocusTask | None:
        task = self.repository.get_task(task_id=task_id, user_id=user_id)
        if task is None:
            return None
        normalized_status = FocusTaskStatus(status) if status is not None else task.status
        now = _format_time()
        updated = task.model_copy(
            update={
                key: value
                for key, value in {
                    "title": _require_title(title) if title is not None else None,
                    "description": str(description) if description is not None else None,
                    "status": normalized_status if status is not None else None,
                    "due_at": due_at,
                    "priority": priority,
                    "source_thread_id": _normalize_optional_id(source_thread_id)
                    if source_thread_id is not None
                    else None,
                    "source_note_id": _normalize_optional_id(source_note_id)
                    if source_note_id is not None
                    else None,
                    "source_artifact_id": _normalize_optional_id(source_artifact_id)
                    if source_artifact_id is not None
                    else None,
                    "source_kind": _normalize_optional_id(source_kind)
                    if source_kind is not None
                    else None,
                    "source_id": _normalize_optional_id(source_id) if source_id is not None else None,
                    "source_url": _normalize_optional_id(source_url)
                    if source_url is not None
                    else None,
                    "pinned_context": dict(pinned_context or {})
                    if pinned_context is not None
                    else None,
                    "captured_from": _normalize_optional_id(captured_from)
                    if captured_from is not None
                    else None,
                    "assignee_user_id": _normalize_optional_id(assignee_user_id)
                    if assignee_user_id is not None
                    else None,
                    "tags": _normalize_tags(tags) if tags is not None else None,
                    "metadata": dict(metadata or {}) if metadata is not None else None,
                    "completed_at": now if normalized_status == FocusTaskStatus.COMPLETED else task.completed_at,
                    "archived_at": now if normalized_status == FocusTaskStatus.ARCHIVED else task.archived_at,
                    "updated_at": now,
                }.items()
                if value is not None
            }
        )
        self.repository.save_task(updated, event=_task_event(updated, FocusTaskEventKind.UPDATED))
        return updated

    def complete_task(self, *, task_id: str, user_id: str) -> FocusTask | None:
        task = self.repository.get_task(task_id=task_id, user_id=user_id)
        if task is None:
            return None
        now = _format_time()
        updated = task.model_copy(
            update={
                "status": FocusTaskStatus.COMPLETED,
                "completed_at": task.completed_at or now,
                "updated_at": now,
            }
        )
        self.repository.save_task(updated, event=_task_event(updated, FocusTaskEventKind.COMPLETED))
        return updated

    def archive_task(self, *, task_id: str, user_id: str) -> FocusTask | None:
        task = self.repository.get_task(task_id=task_id, user_id=user_id)
        if task is None:
            return None
        now = _format_time()
        updated = task.model_copy(
            update={
                "status": FocusTaskStatus.ARCHIVED,
                "archived_at": task.archived_at or now,
                "updated_at": now,
            }
        )
        self.repository.save_task(updated, event=_task_event(updated, FocusTaskEventKind.ARCHIVED))
        return updated

    def capture_note(
        self,
        *,
        user_id: str,
        source_kind: str,
        payload: dict[str, Any] | None = None,
        title: str | None = None,
        body: str | None = None,
        tags: list[str] | None = None,
        source_id: str | None = None,
        source_url: str | None = None,
        source_thread_id: str | None = None,
        source_artifact_id: str | None = None,
        pinned_context: dict[str, object] | None = None,
        captured_from: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> FocusNote:
        payload_data = dict(payload or {})
        capture_source_kind = _require_title(source_kind)
        resolved_body = body if body is not None else _capture_text(payload_data)
        resolved_title = title if title is not None else _capture_title(payload_data, "Captured note")
        return self.create_note(
            user_id=user_id,
            title=resolved_title,
            body=resolved_body,
            tags=tags,
            source_thread_id=source_thread_id or _payload_string(payload_data, "thread_id"),
            source_artifact_id=source_artifact_id or _payload_string(payload_data, "artifact_id"),
            source_kind=capture_source_kind,
            source_id=source_id or _payload_string(payload_data, "id"),
            source_url=source_url or _payload_string(payload_data, "url"),
            pinned_context=pinned_context or _payload_context(payload_data),
            captured_from=captured_from or _payload_string(payload_data, "captured_from"),
            metadata=_merge_capture_metadata(metadata, payload_data, capture_source_kind),
        )

    def capture_task(
        self,
        *,
        user_id: str,
        source_kind: str,
        payload: dict[str, Any] | None = None,
        title: str | None = None,
        description: str | None = None,
        due_at: str | None = None,
        priority: int | None = None,
        source_id: str | None = None,
        source_url: str | None = None,
        source_thread_id: str | None = None,
        source_note_id: str | None = None,
        source_artifact_id: str | None = None,
        assignee_user_id: str | None = None,
        tags: list[str] | None = None,
        pinned_context: dict[str, object] | None = None,
        captured_from: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> FocusTask:
        payload_data = dict(payload or {})
        capture_source_kind = _require_title(source_kind)
        resolved_description = (
            description if description is not None else _capture_text(payload_data)
        )
        resolved_title = title if title is not None else _capture_title(payload_data, "Captured task")
        return self.create_task(
            user_id=user_id,
            title=resolved_title,
            description=resolved_description,
            due_at=due_at or _payload_string(payload_data, "due_at"),
            priority=priority,
            source_thread_id=source_thread_id or _payload_string(payload_data, "thread_id"),
            source_note_id=source_note_id or _payload_string(payload_data, "note_id"),
            source_artifact_id=source_artifact_id or _payload_string(payload_data, "artifact_id"),
            source_kind=capture_source_kind,
            source_id=source_id or _payload_string(payload_data, "id"),
            source_url=source_url or _payload_string(payload_data, "url"),
            pinned_context=pinned_context or _payload_context(payload_data),
            captured_from=captured_from or _payload_string(payload_data, "captured_from"),
            assignee_user_id=assignee_user_id,
            tags=tags,
            metadata=_merge_capture_metadata(metadata, payload_data, capture_source_kind),
        )


def _require_title(value: str | None) -> str:
    title = str(value or "").strip()
    if not title:
        raise ValueError("title must not be empty.")
    return title


def _normalize_optional_id(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _payload_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str):
        return _normalize_optional_id(value)
    return None


def _payload_context(payload: dict[str, Any]) -> dict[str, object]:
    value = payload.get("pinned_context")
    return dict(value) if isinstance(value, dict) else {}


def _capture_text(payload: dict[str, Any]) -> str:
    for key in ("body", "description", "answer", "content", "output", "summary", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    if not payload:
        return ""
    return str({key: payload[key] for key in sorted(payload)})


def _capture_title(payload: dict[str, Any], fallback: str) -> str:
    for key in ("title", "headline", "summary", "task_title", "note_title"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.splitlines()[0][:160]
    text = _capture_text(payload).strip()
    if text:
        return text.splitlines()[0][:160]
    return fallback


def _merge_capture_metadata(
    metadata: dict[str, object] | None,
    payload: dict[str, Any],
    source_kind: str,
) -> dict[str, object]:
    merged = dict(metadata or {})
    merged.setdefault(
        "capture",
        {
            "source_kind": source_kind,
            "payload_keys": sorted(str(key) for key in payload),
        },
    )
    return merged


__all__ = ["ProductivityService"]
