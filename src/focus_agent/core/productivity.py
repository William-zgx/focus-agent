from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class FocusTaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class FocusNoteStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class FocusTaskEventKind(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ProductivityCaptureKind(StrEnum):
    NOTE = "note"
    TASK = "task"


class FocusNote(BaseModel):
    note_id: str
    user_id: str
    title: str
    body: str = ""
    tags: list[str] = Field(default_factory=list)
    status: FocusNoteStatus = FocusNoteStatus.ACTIVE
    source_thread_id: str | None = None
    source_artifact_id: str | None = None
    source_kind: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    pinned_context: dict[str, Any] = Field(default_factory=dict)
    captured_from: str | None = None
    is_archived: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    archived_at: str | None = None

    @model_validator(mode="after")
    def _sync_archive_fields(self) -> FocusNote:
        if self.is_archived and self.status != FocusNoteStatus.ARCHIVED:
            self.status = FocusNoteStatus.ARCHIVED
        elif self.status == FocusNoteStatus.ARCHIVED and not self.is_archived:
            self.is_archived = True
        return self


class FocusTask(BaseModel):
    task_id: str
    user_id: str
    title: str
    description: str = ""
    status: FocusTaskStatus = FocusTaskStatus.TODO
    due_at: str | None = None
    priority: int | None = None
    source_thread_id: str | None = None
    source_note_id: str | None = None
    source_artifact_id: str | None = None
    source_kind: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    pinned_context: dict[str, Any] = Field(default_factory=dict)
    captured_from: str | None = None
    assignee_user_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    completed_at: str | None = None
    archived_at: str | None = None


class FocusTaskEvent(BaseModel):
    event_id: str
    task_id: str
    user_id: str
    kind: FocusTaskEventKind
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: str


__all__ = [
    "FocusNote",
    "FocusNoteStatus",
    "FocusTask",
    "FocusTaskEvent",
    "FocusTaskEventKind",
    "FocusTaskStatus",
    "ProductivityCaptureKind",
]
