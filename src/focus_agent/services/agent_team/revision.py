"""Immutable Agent Team revision data transfer objects."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class AgentTeamRevisionError(Exception):
    """Base exception for immutable Agent Team revision operations."""


class RevisionConstructionError(AgentTeamRevisionError):
    """Raised when a revision DTO cannot be constructed safely."""


class UnknownRevisionTaskError(AgentTeamRevisionError):
    """Raised when a requested task is absent from a revision."""


class RevisionTaskStatus(StrEnum):
    """Status values compatible with the existing Agent Team task lifecycle."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


FrozenValue = (
    str | int | float | bool | None | tuple["FrozenValue", ...] | Mapping[str, "FrozenValue"]
)


def _freeze_value(value: Any) -> FrozenValue:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})
    if isinstance(value, str | bytes):
        return str(value)
    if isinstance(value, Iterable):
        return tuple(_freeze_value(item) for item in value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _freeze_mapping(
    value: Mapping[str, Any] | None, *, field_name: str
) -> Mapping[str, FrozenValue]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise RevisionConstructionError(f"{field_name} must be a mapping.")
    return MappingProxyType({str(key): _freeze_value(item) for key, item in value.items()})


def _string_tuple(value: Iterable[Any] | str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    values = (value,) if isinstance(value, str) else value
    return tuple(str(item).strip() for item in values if str(item).strip())


@dataclass(frozen=True, slots=True)
class AgentTeamRevisionTask:
    """A task and its state as captured by one immutable revision."""

    task_id: str
    dependencies: tuple[str, ...] = ()
    input_contract: Mapping[str, FrozenValue] = field(default_factory=lambda: MappingProxyType({}))
    write_scope: tuple[str, ...] = ()
    resource_claims: tuple[str, ...] = ()
    task_kind: str | None = None
    writes: bool = False
    status: RevisionTaskStatus = RevisionTaskStatus.PENDING
    last_error: str | None = None

    def __post_init__(self) -> None:
        task_id = str(self.task_id).strip()
        if not task_id:
            raise RevisionConstructionError("task_id is required.")
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "dependencies", _string_tuple(self.dependencies))
        object.__setattr__(self, "write_scope", _string_tuple(self.write_scope))
        object.__setattr__(self, "resource_claims", _string_tuple(self.resource_claims))
        object.__setattr__(
            self,
            "input_contract",
            _freeze_mapping(self.input_contract, field_name="input_contract"),
        )
        object.__setattr__(self, "task_kind", _optional_text(self.task_kind))
        object.__setattr__(self, "writes", bool(self.writes))
        try:
            status = RevisionTaskStatus(self.status)
        except ValueError as exc:
            raise RevisionConstructionError(f"Unsupported task status: {self.status!r}.") from exc
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "last_error", _optional_text(self.last_error))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AgentTeamRevisionTask:
        """Create a snapshot task from current Agent Team-shaped data."""
        input_contract = value.get("input_contract") or {}
        task_kind = value.get("task_kind") or value.get("task_type")
        write_scope = value.get("write_scope")
        writes = value.get("writes")
        if writes is None:
            writes = str(task_kind or "").strip().lower() in {
                "implementation",
                "write",
                "writing",
                "code_change",
            }
        return cls(
            task_id=str(value.get("task_id") or value.get("key") or ""),
            dependencies=_string_tuple(value.get("dependencies")),
            input_contract=input_contract if isinstance(input_contract, Mapping) else {},
            write_scope=_string_tuple(write_scope),
            resource_claims=_string_tuple(value.get("resource_claims")),
            task_kind=_optional_text(task_kind),
            writes=bool(writes),
            status=value.get("status") or RevisionTaskStatus.PENDING,
            last_error=_optional_text(value.get("last_error")),
        )

    @property
    def is_write_task(self) -> bool:
        """Return whether the task must carry explicit write ownership metadata."""
        return self.writes or bool(self.write_scope) or bool(self.resource_claims)


@dataclass(frozen=True, slots=True)
class AgentTeamRevision:
    """A complete, immutable snapshot of an Agent Team task DAG."""

    revision_id: str
    session_id: str
    sequence: int
    tasks: tuple[AgentTeamRevisionTask, ...]
    parent_revision_id: str | None = None
    metadata: Mapping[str, FrozenValue] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        revision_id = str(self.revision_id).strip()
        session_id = str(self.session_id).strip()
        if not revision_id:
            raise RevisionConstructionError("revision_id is required.")
        if not session_id:
            raise RevisionConstructionError("session_id is required.")
        if int(self.sequence) < 0:
            raise RevisionConstructionError("sequence must be non-negative.")
        tasks = tuple(self.tasks)
        if not all(isinstance(task, AgentTeamRevisionTask) for task in tasks):
            raise RevisionConstructionError("tasks must contain AgentTeamRevisionTask values.")
        object.__setattr__(self, "revision_id", revision_id)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "sequence", int(self.sequence))
        object.__setattr__(self, "tasks", tasks)
        object.__setattr__(self, "parent_revision_id", _optional_text(self.parent_revision_id))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata, field_name="metadata"))

    @classmethod
    def from_task_mappings(
        cls,
        *,
        revision_id: str,
        session_id: str,
        sequence: int,
        tasks: Iterable[Mapping[str, Any]],
        parent_revision_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentTeamRevision:
        """Build a revision from existing task-shaped mappings without mutating them."""
        return cls(
            revision_id=revision_id,
            session_id=session_id,
            sequence=sequence,
            tasks=tuple(AgentTeamRevisionTask.from_mapping(task) for task in tasks),
            parent_revision_id=parent_revision_id,
            metadata=metadata or {},
        )

    def task_by_id(self, task_id: str) -> AgentTeamRevisionTask:
        """Return one task from this snapshot."""
        normalized_task_id = str(task_id).strip()
        for task in self.tasks:
            if task.task_id == normalized_task_id:
                return task
        raise UnknownRevisionTaskError(
            f"Task {normalized_task_id!r} does not exist in revision {self.revision_id!r}."
        )


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


__all__ = [
    "AgentTeamRevision",
    "AgentTeamRevisionError",
    "AgentTeamRevisionTask",
    "FrozenValue",
    "RevisionConstructionError",
    "RevisionTaskStatus",
    "UnknownRevisionTaskError",
]
