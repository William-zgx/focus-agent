from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain.tools import tool

from ...core.productivity import FocusTaskStatus
from ...repositories.productivity_repository import ProductivityRepository
from ...services.productivity import ProductivityService
from .build_context import ToolBuildContext


class _ProductivityScope:
    """Per-user access to the productivity repository plus the shared tool event envelope."""

    def __init__(
        self,
        context: ToolBuildContext,
        productivity_repository: ProductivityRepository | None,
    ) -> None:
        self.context = context
        self._repository = productivity_repository

    def repository(self) -> ProductivityRepository:
        if self._repository is None:
            raise RuntimeError("Productivity repository is not configured.")
        return self._repository

    def service(self) -> ProductivityService:
        return ProductivityService(self.repository())

    def user_id(self) -> str:
        user_id = self.context.get_current_user_id()
        if not user_id:
            raise RuntimeError("Productivity tools require an authenticated user context.")
        return user_id

    def thread_id(self, explicit: str | None) -> str | None:
        return explicit or self.context.get_current_thread_id()

    def run(self, tool_name: str, action: Callable[[], dict[str, Any]]) -> str:
        emit_tool_event = self.context.emit_tool_event
        emit_tool_event(tool_name=tool_name, stage="start")
        try:
            output = _json(action())
            emit_tool_event(tool_name=tool_name, stage="end", output=output)
            return output
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc))
            raise


def _items_payload(items: list[Any]) -> dict[str, Any]:
    return {"items": [item.model_dump(mode="json") for item in items], "count": len(items)}


def _require_found(record: Any, message: str) -> Any:
    if record is None:
        raise LookupError(message)
    return record


def build_notes_create_tool(scope: _ProductivityScope) -> Any:
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

        def action() -> dict[str, Any]:
            note = scope.service().create_note(
                user_id=scope.user_id(),
                title=title,
                body=body,
                tags=tags,
                source_thread_id=scope.thread_id(source_thread_id),
                source_artifact_id=source_artifact_id,
                source_kind=source_kind,
                source_id=source_id,
                source_url=source_url,
                pinned_context=pinned_context,
                captured_from=captured_from,
            )
            return {"note": note.model_dump(mode="json")}

        return scope.run("notes_create", action)

    return notes_create


def build_notes_search_tool(scope: _ProductivityScope) -> Any:
    @tool
    def notes_search(
        query: str = "",
        tags: list[str] | None = None,
        include_archived: bool = False,
        limit: int = 20,
    ) -> str:
        """Search personal notes owned by the current user."""
        return scope.run(
            "notes_search",
            lambda: _items_payload(
                scope.repository().list_notes(
                    user_id=scope.user_id(),
                    query=query,
                    tags=tags,
                    include_archived=include_archived,
                    limit=max(0, min(int(limit), 50)),
                )
            ),
        )

    return notes_search


def build_notes_update_tool(scope: _ProductivityScope) -> Any:
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

        def action() -> dict[str, Any]:
            note = scope.service().update_note(
                note_id=note_id,
                user_id=scope.user_id(),
                title=title,
                body=body,
                tags=tags,
                status=status,
                is_archived=is_archived,
            )
            note = _require_found(note, f"Note not found: {note_id}")
            return {"note": note.model_dump(mode="json")}

        return scope.run("notes_update", action)

    return notes_update


def build_tasks_create_tool(scope: _ProductivityScope) -> Any:
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

        def action() -> dict[str, Any]:
            task = scope.service().create_task(
                user_id=scope.user_id(),
                title=title,
                description=description,
                priority=priority,
                due_at=due_at,
                source_note_id=source_note_id,
                source_thread_id=scope.thread_id(source_thread_id),
                source_artifact_id=source_artifact_id,
                source_kind=source_kind,
                source_id=source_id,
                source_url=source_url,
                pinned_context=pinned_context,
                captured_from=captured_from,
                assignee_user_id=assignee_user_id,
            )
            return {"task": task.model_dump(mode="json")}

        return scope.run("tasks_create", action)

    return tasks_create


def build_tasks_list_tool(scope: _ProductivityScope) -> Any:
    @tool
    def tasks_list(
        status: str | None = None,
        include_archived: bool = False,
        limit: int = 20,
    ) -> str:
        """List personal tasks owned by the current user."""

        def action() -> dict[str, Any]:
            normalized_status = FocusTaskStatus(status) if status else None
            return _items_payload(
                scope.repository().list_tasks(
                    user_id=scope.user_id(),
                    status=normalized_status,
                    include_archived=include_archived,
                    limit=max(0, min(int(limit), 50)),
                )
            )

        return scope.run("tasks_list", action)

    return tasks_list


def build_tasks_update_tool(scope: _ProductivityScope) -> Any:
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

        def action() -> dict[str, Any]:
            task = scope.service().update_task(
                task_id=task_id,
                user_id=scope.user_id(),
                title=title,
                description=description,
                status=status,
                priority=priority,
                due_at=due_at,
            )
            task = _require_found(task, f"Task not found: {task_id}")
            return {"task": task.model_dump(mode="json")}

        return scope.run("tasks_update", action)

    return tasks_update


def build_productivity_capture_tool(scope: _ProductivityScope) -> Any:
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

        def action() -> dict[str, Any]:
            payload = _payload_from_json(payload_json)
            if content:
                payload.setdefault("content", content)
            normalized_type = str(capture_type or "").strip().lower()
            if normalized_type == "note":
                note = scope.service().capture_note(
                    user_id=scope.user_id(),
                    source_kind=source_kind,
                    payload=payload,
                    title=title,
                    body=content or None,
                    tags=tags,
                    source_id=source_id,
                    source_url=source_url,
                    source_thread_id=scope.thread_id(source_thread_id),
                    source_artifact_id=source_artifact_id,
                    captured_from=captured_from,
                )
                return {"capture_type": "note", "note": note.model_dump(mode="json")}
            if normalized_type == "task":
                task = scope.service().capture_task(
                    user_id=scope.user_id(),
                    source_kind=source_kind,
                    payload=payload,
                    title=title,
                    description=content or None,
                    tags=tags,
                    source_id=source_id,
                    source_url=source_url,
                    source_thread_id=scope.thread_id(source_thread_id),
                    source_note_id=source_note_id,
                    source_artifact_id=source_artifact_id,
                    captured_from=captured_from,
                )
                return {"capture_type": "task", "task": task.model_dump(mode="json")}
            raise ValueError("capture_type must be 'note' or 'task'.")

        return scope.run("productivity_capture", action)

    return productivity_capture


def build_productivity_tools(
    context: ToolBuildContext,
    *,
    productivity_repository: ProductivityRepository | None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    scope = _ProductivityScope(context, productivity_repository)
    return (
        {
            "notes_create": build_notes_create_tool(scope),
            "notes_search": build_notes_search_tool(scope),
            "notes_update": build_notes_update_tool(scope),
            "tasks_create": build_tasks_create_tool(scope),
            "tasks_list": build_tasks_list_tool(scope),
            "tasks_update": build_tasks_update_tool(scope),
            "productivity_capture": build_productivity_capture_tool(scope),
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
