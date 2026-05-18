from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain.tools import tool

from ...core.productivity import FocusTaskStatus
from ...repositories.productivity_repository import ProductivityRepository
from ...services.productivity import ProductivityService


def build_productivity_tools(
    *,
    productivity_repository: ProductivityRepository | None,
    emit_tool_event: Callable[..., None],
    get_current_thread_id: Callable[[], str | None],
    get_current_user_id: Callable[[], str | None],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    def _service() -> ProductivityService:
        return ProductivityService(_repository())

    def _repository() -> ProductivityRepository:
        if productivity_repository is None:
            raise RuntimeError("Productivity repository is not configured.")
        return productivity_repository

    def _user_id() -> str:
        user_id = get_current_user_id()
        if not user_id:
            raise RuntimeError("Productivity tools require an authenticated user context.")
        return user_id

    @tool
    def notes_create(
        title: str,
        body: str = "",
        tags: list[str] | None = None,
        source_thread_id: str | None = None,
        source_artifact_id: str | None = None,
        source_kind: str | None = None,
        source_id: str | None = None,
        source_url: str | None = None,
        pinned_context: dict[str, Any] | None = None,
        captured_from: str | None = None,
    ) -> str:
        """Create a personal note owned by the current user."""
        tool_name = "notes_create"
        emit_tool_event(tool_name=tool_name, stage="start")
        try:
            note = _service().create_note(
                user_id=_user_id(),
                title=title,
                body=body,
                tags=tags,
                source_thread_id=source_thread_id or get_current_thread_id(),
                source_artifact_id=source_artifact_id,
                source_kind=source_kind,
                source_id=source_id,
                source_url=source_url,
                pinned_context=pinned_context,
                captured_from=captured_from,
            )
            output = _json({"note": note.model_dump(mode="json")})
            emit_tool_event(tool_name=tool_name, stage="end", output=output)
            return output
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc))
            raise

    @tool
    def notes_search(
        query: str = "",
        tags: list[str] | None = None,
        include_archived: bool = False,
        limit: int = 20,
    ) -> str:
        """Search personal notes owned by the current user."""
        tool_name = "notes_search"
        emit_tool_event(tool_name=tool_name, stage="start")
        try:
            items = _repository().list_notes(
                user_id=_user_id(),
                query=query,
                tags=tags,
                include_archived=include_archived,
                limit=max(0, min(int(limit), 50)),
            )
            output = _json(
                {"items": [item.model_dump(mode="json") for item in items], "count": len(items)}
            )
            emit_tool_event(tool_name=tool_name, stage="end", output=output)
            return output
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc))
            raise

    @tool
    def notes_update(
        note_id: str,
        title: str | None = None,
        body: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        is_archived: bool | None = None,
    ) -> str:
        """Update a personal note owned by the current user."""
        tool_name = "notes_update"
        emit_tool_event(tool_name=tool_name, stage="start")
        try:
            note = _service().update_note(
                note_id=note_id,
                user_id=_user_id(),
                title=title,
                body=body,
                tags=tags,
                status=status,
                is_archived=is_archived,
            )
            if note is None:
                raise LookupError(f"Note not found: {note_id}")
            output = _json({"note": note.model_dump(mode="json")})
            emit_tool_event(tool_name=tool_name, stage="end", output=output)
            return output
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc))
            raise

    @tool
    def tasks_create(
        title: str,
        description: str = "",
        priority: int | None = None,
        due_at: str | None = None,
        source_note_id: str | None = None,
        source_thread_id: str | None = None,
        source_artifact_id: str | None = None,
        source_kind: str | None = None,
        source_id: str | None = None,
        source_url: str | None = None,
        pinned_context: dict[str, Any] | None = None,
        captured_from: str | None = None,
        assignee_user_id: str | None = None,
    ) -> str:
        """Create a personal task owned by the current user."""
        tool_name = "tasks_create"
        emit_tool_event(tool_name=tool_name, stage="start")
        try:
            task = _service().create_task(
                user_id=_user_id(),
                title=title,
                description=description,
                priority=priority,
                due_at=due_at,
                source_note_id=source_note_id,
                source_thread_id=source_thread_id or get_current_thread_id(),
                source_artifact_id=source_artifact_id,
                source_kind=source_kind,
                source_id=source_id,
                source_url=source_url,
                pinned_context=pinned_context,
                captured_from=captured_from,
                assignee_user_id=assignee_user_id,
            )
            output = _json({"task": task.model_dump(mode="json")})
            emit_tool_event(tool_name=tool_name, stage="end", output=output)
            return output
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc))
            raise

    @tool
    def tasks_list(
        status: str | None = None,
        include_archived: bool = False,
        limit: int = 20,
    ) -> str:
        """List personal tasks owned by the current user."""
        tool_name = "tasks_list"
        emit_tool_event(tool_name=tool_name, stage="start")
        try:
            normalized_status = FocusTaskStatus(status) if status else None
            items = _repository().list_tasks(
                user_id=_user_id(),
                status=normalized_status,
                include_archived=include_archived,
                limit=max(0, min(int(limit), 50)),
            )
            output = _json(
                {"items": [item.model_dump(mode="json") for item in items], "count": len(items)}
            )
            emit_tool_event(tool_name=tool_name, stage="end", output=output)
            return output
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc))
            raise

    @tool
    def tasks_update(
        task_id: str,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: int | None = None,
        due_at: str | None = None,
    ) -> str:
        """Update a personal task owned by the current user."""
        tool_name = "tasks_update"
        emit_tool_event(tool_name=tool_name, stage="start")
        try:
            task = _service().update_task(
                task_id=task_id,
                user_id=_user_id(),
                title=title,
                description=description,
                status=status,
                priority=priority,
                due_at=due_at,
            )
            if task is None:
                raise LookupError(f"Task not found: {task_id}")
            output = _json({"task": task.model_dump(mode="json")})
            emit_tool_event(tool_name=tool_name, stage="end", output=output)
            return output
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc))
            raise

    @tool
    def productivity_capture(
        capture_type: str,
        source_kind: str,
        title: str | None = None,
        content: str = "",
        payload_json: str = "",
        tags: list[str] | None = None,
        source_id: str | None = None,
        source_url: str | None = None,
        source_thread_id: str | None = None,
        source_artifact_id: str | None = None,
        source_note_id: str | None = None,
        captured_from: str | None = None,
    ) -> str:
        """Capture a chat or Agent Team payload as an explicit note or task."""
        tool_name = "productivity_capture"
        emit_tool_event(tool_name=tool_name, stage="start")
        try:
            payload = _payload_from_json(payload_json)
            if content:
                payload.setdefault("content", content)
            normalized_type = str(capture_type or "").strip().lower()
            if normalized_type == "note":
                note = _service().capture_note(
                    user_id=_user_id(),
                    source_kind=source_kind,
                    payload=payload,
                    title=title,
                    body=content or None,
                    tags=tags,
                    source_id=source_id,
                    source_url=source_url,
                    source_thread_id=source_thread_id or get_current_thread_id(),
                    source_artifact_id=source_artifact_id,
                    captured_from=captured_from,
                )
                output = _json({"capture_type": "note", "note": note.model_dump(mode="json")})
            elif normalized_type == "task":
                task = _service().capture_task(
                    user_id=_user_id(),
                    source_kind=source_kind,
                    payload=payload,
                    title=title,
                    description=content or None,
                    tags=tags,
                    source_id=source_id,
                    source_url=source_url,
                    source_thread_id=source_thread_id or get_current_thread_id(),
                    source_note_id=source_note_id,
                    source_artifact_id=source_artifact_id,
                    captured_from=captured_from,
                )
                output = _json({"capture_type": "task", "task": task.model_dump(mode="json")})
            else:
                raise ValueError("capture_type must be 'note' or 'task'.")
            emit_tool_event(tool_name=tool_name, stage="end", output=output)
            return output
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc))
            raise

    return (
        {
            "notes_create": notes_create,
            "notes_search": notes_search,
            "notes_update": notes_update,
            "tasks_create": tasks_create,
            "tasks_list": tasks_list,
            "tasks_update": tasks_update,
            "productivity_capture": productivity_capture,
        },
        {
            "notes_create": _side_effect_meta(),
            "notes_update": _side_effect_meta(),
            "tasks_create": _side_effect_meta(),
            "tasks_update": _side_effect_meta(),
            "productivity_capture": _side_effect_meta(),
            "notes_search": _read_meta(),
            "tasks_list": _read_meta(),
        },
    )


def _side_effect_meta() -> dict[str, Any]:
    return {
        "toolset": "productivity",
        "side_effect": True,
        "risk_level": "medium",
        "max_observation_chars": 6000,
        "intent_policies": ("execution",),
    }


def _read_meta() -> dict[str, Any]:
    return {
        "toolset": "productivity",
        "parallel_safe": True,
        "max_observation_chars": 6000,
        "intent_policies": ("workspace_lookup", "execution"),
    }


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _payload_from_json(value: str) -> dict[str, Any]:
    if not str(value or "").strip():
        return {}
    payload = json.loads(value)
    if not isinstance(payload, dict):
        raise ValueError("payload_json must decode to an object.")
    return payload


__all__ = ["build_productivity_tools"]
