from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from focus_agent.core.productivity import (
    FocusNote,
    FocusNoteStatus,
    FocusTask,
    FocusTaskEvent,
    FocusTaskStatus,
)


class CreateNoteRequest(BaseModel):
    title: str
    body: str = ""
    tags: list[str] = Field(default_factory=list)
    source_thread_id: str | None = None
    source_artifact_id: str | None = None
    source_kind: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    pinned_context: dict[str, Any] | None = None
    captured_from: str | None = None
    metadata: dict[str, Any] | None = None


class UpdateNoteRequest(BaseModel):
    title: str | None = None
    body: str | None = None
    tags: list[str] | None = None
    status: FocusNoteStatus | None = None
    source_thread_id: str | None = None
    source_artifact_id: str | None = None
    source_kind: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    pinned_context: dict[str, Any] | None = None
    captured_from: str | None = None
    is_archived: bool | None = None
    metadata: dict[str, Any] | None = None


class NoteResponse(BaseModel):
    note: FocusNote


class NoteListResponse(BaseModel):
    items: list[FocusNote] = Field(default_factory=list)
    count: int


class CreateTaskRequest(BaseModel):
    title: str
    description: str = ""
    due_at: str | None = None
    priority: int | None = None
    source_thread_id: str | None = None
    source_note_id: str | None = None
    source_artifact_id: str | None = None
    source_kind: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    pinned_context: dict[str, Any] | None = None
    captured_from: str | None = None
    assignee_user_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class UpdateTaskRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: FocusTaskStatus | None = None
    due_at: str | None = None
    priority: int | None = None
    source_thread_id: str | None = None
    source_note_id: str | None = None
    source_artifact_id: str | None = None
    source_kind: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    pinned_context: dict[str, Any] | None = None
    captured_from: str | None = None
    assignee_user_id: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class TaskResponse(BaseModel):
    task: FocusTask


class TaskListResponse(BaseModel):
    items: list[FocusTask] = Field(default_factory=list)
    count: int


class TaskEventListResponse(BaseModel):
    items: list[FocusTaskEvent] = Field(default_factory=list)
    count: int


class CaptureNoteRequest(BaseModel):
    source_kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    title: str | None = None
    body: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_id: str | None = None
    source_url: str | None = None
    source_thread_id: str | None = None
    source_artifact_id: str | None = None
    pinned_context: dict[str, Any] | None = None
    captured_from: str | None = None
    metadata: dict[str, Any] | None = None


class CaptureTaskRequest(BaseModel):
    source_kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    title: str | None = None
    description: str | None = None
    due_at: str | None = None
    priority: int | None = None
    source_id: str | None = None
    source_url: str | None = None
    source_thread_id: str | None = None
    source_note_id: str | None = None
    source_artifact_id: str | None = None
    assignee_user_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    pinned_context: dict[str, Any] | None = None
    captured_from: str | None = None
    metadata: dict[str, Any] | None = None


__all__ = [
    "CaptureNoteRequest",
    "CaptureTaskRequest",
    "CreateNoteRequest",
    "CreateTaskRequest",
    "NoteListResponse",
    "NoteResponse",
    "TaskEventListResponse",
    "TaskListResponse",
    "TaskResponse",
    "UpdateNoteRequest",
    "UpdateTaskRequest",
]
