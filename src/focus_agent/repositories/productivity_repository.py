from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from focus_agent.core.productivity import (
    FocusNote,
    FocusTask,
    FocusTaskEvent,
    FocusTaskEventKind,
    FocusTaskStatus,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _format_time(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _normalize_tags(tags: list[str] | tuple[str, ...] | None) -> list[str]:
    return list(dict.fromkeys(str(tag).strip() for tag in (tags or ()) if str(tag).strip()))


class ProductivityRepository(ABC):
    @abstractmethod
    def create_note(self, note: FocusNote) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_note(self, note: FocusNote) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_note(self, *, note_id: str, user_id: str) -> FocusNote | None:
        raise NotImplementedError

    @abstractmethod
    def list_notes(
        self,
        *,
        user_id: str,
        query: str | None = None,
        tags: list[str] | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FocusNote]:
        raise NotImplementedError

    @abstractmethod
    def create_task(self, task: FocusTask) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_task(self, task: FocusTask, *, event: FocusTaskEvent | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_task(self, *, task_id: str, user_id: str) -> FocusTask | None:
        raise NotImplementedError

    @abstractmethod
    def list_tasks(
        self,
        *,
        user_id: str,
        status: FocusTaskStatus | str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FocusTask]:
        raise NotImplementedError

    @abstractmethod
    def list_task_events(self, *, task_id: str, user_id: str) -> list[FocusTaskEvent]:
        raise NotImplementedError


class InMemoryProductivityRepository(ProductivityRepository):
    def __init__(self) -> None:
        self._lock = RLock()
        self._notes: dict[str, FocusNote] = {}
        self._tasks: dict[str, FocusTask] = {}
        self._events: dict[str, list[FocusTaskEvent]] = {}

    def create_note(self, note: FocusNote) -> None:
        with self._lock:
            self._notes[note.note_id] = note

    def save_note(self, note: FocusNote) -> None:
        with self._lock:
            self._notes[note.note_id] = note

    def get_note(self, *, note_id: str, user_id: str) -> FocusNote | None:
        with self._lock:
            note = self._notes.get(note_id)
        if note is None or note.user_id != user_id:
            return None
        return note

    def list_notes(
        self,
        *,
        user_id: str,
        query: str | None = None,
        tags: list[str] | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FocusNote]:
        tag_filter = set(_normalize_tags(tags))
        query_text = str(query or "").strip().casefold()
        with self._lock:
            notes = [note for note in self._notes.values() if note.user_id == user_id]
        if not include_archived:
            notes = [note for note in notes if not note.is_archived]
        if tag_filter:
            notes = [note for note in notes if tag_filter.issubset(set(note.tags))]
        if query_text:
            notes = [
                note for note in notes if query_text in f"{note.title}\n{note.body}".casefold()
            ]
        notes.sort(key=lambda item: (item.updated_at, item.note_id), reverse=True)
        return notes[max(0, offset) : max(0, offset) + max(0, limit)]

    def create_task(self, task: FocusTask) -> None:
        with self._lock:
            self._tasks[task.task_id] = task
            self._events.setdefault(task.task_id, []).append(
                _task_event(task, FocusTaskEventKind.CREATED)
            )

    def save_task(self, task: FocusTask, *, event: FocusTaskEvent | None = None) -> None:
        with self._lock:
            self._tasks[task.task_id] = task
            if event is not None:
                self._events.setdefault(task.task_id, []).append(event)

    def get_task(self, *, task_id: str, user_id: str) -> FocusTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None or task.user_id != user_id:
            return None
        return task

    def list_tasks(
        self,
        *,
        user_id: str,
        status: FocusTaskStatus | str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FocusTask]:
        normalized_status = FocusTaskStatus(status) if status else None
        with self._lock:
            tasks = [task for task in self._tasks.values() if task.user_id == user_id]
        if normalized_status is not None:
            tasks = [task for task in tasks if task.status == normalized_status]
        elif not include_archived:
            tasks = [task for task in tasks if task.status != FocusTaskStatus.ARCHIVED]
        tasks.sort(key=lambda item: (item.updated_at, item.task_id), reverse=True)
        return tasks[max(0, offset) : max(0, offset) + max(0, limit)]

    def list_task_events(self, *, task_id: str, user_id: str) -> list[FocusTaskEvent]:
        task = self.get_task(task_id=task_id, user_id=user_id)
        if task is None:
            return []
        with self._lock:
            events = list(self._events.get(task_id, []))
        return sorted(events, key=lambda item: (item.created_at, item.event_id))


def _task_event(
    task: FocusTask,
    kind: FocusTaskEventKind,
    *,
    data: dict[str, object] | None = None,
) -> FocusTaskEvent:
    return FocusTaskEvent(
        event_id=f"task-event-{uuid4().hex}",
        task_id=task.task_id,
        user_id=task.user_id,
        kind=kind,
        data=dict(data or {}),
        created_at=_format_time(),
    )


__all__ = [
    "InMemoryProductivityRepository",
    "ProductivityRepository",
    "_format_time",
    "_normalize_tags",
    "_now",
    "_task_event",
]
