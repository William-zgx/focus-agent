"""Data models and dependency protocols for Agent Team task execution."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from threading import Event
from types import MappingProxyType
from typing import Any, Protocol, TypeAlias


class TaskRunStatus(StrEnum):
    COMPLETED = "completed"
    PAUSED_FOR_APPROVAL = "paused_for_approval"
    CANCELLED = "cancelled"
    FAILED = "failed"
    MAX_ROUNDS_REACHED = "max_rounds_reached"


class TaskExecutionEventType(StrEnum):
    MODEL_RESPONSE = "model_response"
    TOOL_RESULT = "tool_result"
    AWAITING_APPROVAL = "awaiting_approval"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    MAX_ROUNDS_REACHED = "max_rounds_reached"


@dataclass(frozen=True, slots=True)
class TaskExecutionScope:
    """Immutable execution boundary for a single Agent Team task."""

    task_id: str
    session_id: str
    user_id: str
    workspace_path: str | None = None
    allowed_tool_names: frozenset[str] = field(default_factory=frozenset)
    write_scope: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _required_identifier(self.task_id, "task_id"))
        object.__setattr__(self, "session_id", _required_identifier(self.session_id, "session_id"))
        object.__setattr__(self, "user_id", _required_identifier(self.user_id, "user_id"))
        object.__setattr__(
            self,
            "workspace_path",
            _optional_identifier(self.workspace_path),
        )
        object.__setattr__(
            self,
            "allowed_tool_names",
            frozenset(
                name
                for name in (_normalized_name(value) for value in self.allowed_tool_names)
                if name
            ),
        )
        object.__setattr__(
            self,
            "write_scope",
            tuple(value for value in (str(item).strip() for item in self.write_scope) if value),
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

    def allows_tool(self, tool_name: str) -> bool:
        return _normalized_name(tool_name) in self.allowed_tool_names

    def model_context(self) -> dict[str, Any]:
        """Return a JSON-friendly, explicit context without changing process cwd."""
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "workspace_path": self.workspace_path,
            "write_scope": list(self.write_scope),
            "metadata": dict(self.metadata),
        }


class CancellationToken:
    """Thread-safe cooperative cancellation shared by model and tools."""

    def __init__(self) -> None:
        self._event = Event()
        self._reason: str | None = None

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        return self._reason

    def cancel(self, reason: str | None = None) -> None:
        self._reason = str(reason).strip() if reason else "Task execution was cancelled."
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise TaskExecutionCancelled(self.reason or "Task execution was cancelled.")


class TaskExecutionCancelledError(RuntimeError):
    """Raised by cooperative model or tool code when a task is cancelled."""


TaskExecutionCancelled = TaskExecutionCancelledError


@dataclass(frozen=True, slots=True)
class TaskToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "call_id", _required_identifier(self.call_id, "call_id"))
        object.__setattr__(self, "name", _required_identifier(self.name, "tool name"))
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))


@dataclass(frozen=True, slots=True)
class TaskToolDefinition:
    name: str
    description: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    requires_approval: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_identifier(self.name, "tool name"))
        object.__setattr__(self, "input_schema", MappingProxyType(dict(self.input_schema)))


@dataclass(frozen=True, slots=True)
class TaskToolResult:
    call_id: str
    tool_name: str
    status: str
    output: Any = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "completed" and self.error is None


TaskToolHandler: TypeAlias = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class TaskScopedTool:
    """A tool which receives scope and cancellation explicitly on every call."""

    name: str
    handler: TaskToolHandler
    description: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    requires_approval: bool = False
    risk_level: str = "low"
    sensitive_argument_names: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_identifier(self.name, "tool name"))
        object.__setattr__(self, "input_schema", MappingProxyType(dict(self.input_schema)))
        object.__setattr__(
            self,
            "sensitive_argument_names",
            frozenset(
                name
                for name in (_normalized_name(value) for value in self.sensitive_argument_names)
                if name
            ),
        )

    @property
    def definition(self) -> TaskToolDefinition:
        return TaskToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            requires_approval=self.requires_approval,
        )

    def invoke(
        self,
        arguments: Mapping[str, Any],
        *,
        scope: TaskExecutionScope,
        cancellation_token: CancellationToken,
    ) -> Any:
        cancellation_token.raise_if_cancelled()
        return _call_compatible(
            self.handler,
            (
                (
                    (),
                    {
                        "arguments": dict(arguments),
                        "scope": scope,
                        "cancellation_token": cancellation_token,
                    },
                ),
                (
                    (),
                    {
                        "args": dict(arguments),
                        "scope": scope,
                        "cancellation_token": cancellation_token,
                    },
                ),
                ((dict(arguments), scope, cancellation_token), {}),
                ((dict(arguments), scope), {}),
                ((dict(arguments),), {}),
            ),
        )

    def redact_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        return {
            str(key): (
                "[REDACTED]"
                if _normalized_name(key) in self.sensitive_argument_names
                else _json_safe(value)
            )
            for key, value in arguments.items()
        }


@dataclass(frozen=True, slots=True)
class TaskAgentMessage:
    role: str
    content: str = ""
    tool_calls: tuple[TaskToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_status: str | None = None

    @classmethod
    def user(cls, content: str) -> TaskAgentMessage:
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, response: TaskModelResponse) -> TaskAgentMessage:
        return cls(
            role="assistant",
            content=response.content,
            tool_calls=response.tool_calls,
        )

    @classmethod
    def tool(cls, result: TaskToolResult) -> TaskAgentMessage:
        return cls(
            role="tool",
            content=_render_tool_result(result),
            tool_call_id=result.call_id,
            tool_name=result.tool_name,
            tool_status=result.status,
        )


@dataclass(frozen=True, slots=True)
class TaskModelResponse:
    content: str = ""
    tool_calls: tuple[TaskToolCall, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class TaskAgentModel(Protocol):
    def invoke(
        self,
        messages: Sequence[TaskAgentMessage],
        *,
        tools: Sequence[TaskToolDefinition],
        scope: TaskExecutionScope,
        cancellation_token: CancellationToken,
    ) -> TaskModelResponse:
        """Return one response from the task-specific model."""


@dataclass(frozen=True, slots=True)
class TaskApprovalRequest:
    request_id: str
    task_id: str
    session_id: str
    tool_call_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    risk_level: str
    round_number: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))


TaskApprovalDecider: TypeAlias = Callable[[TaskApprovalRequest], bool | None]


@dataclass(frozen=True, slots=True)
class TaskExecutionCheckpoint:
    run_id: str
    task_id: str
    session_id: str
    round_number: int
    event: TaskExecutionEventType
    payload: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class TaskExecutionEvidence:
    run_id: str
    task_id: str
    round_number: int
    kind: str
    value: Any
    tool_call_id: str | None = None
    tool_name: str | None = None


CheckpointSink: TypeAlias = Callable[[TaskExecutionCheckpoint], None]
EvidenceSink: TypeAlias = Callable[[TaskExecutionEvidence], None]


@dataclass(frozen=True, slots=True)
class TaskRunResult:
    run_id: str
    scope: TaskExecutionScope
    status: TaskRunStatus
    rounds_completed: int
    final_answer: str | None
    messages: tuple[TaskAgentMessage, ...]
    checkpoints: tuple[TaskExecutionCheckpoint, ...]
    evidence: tuple[TaskExecutionEvidence, ...]
    pending_approval: TaskApprovalRequest | None = None
    error: str | None = None


def _call_compatible(
    target: Callable[..., Any],
    candidates: Sequence[tuple[tuple[Any, ...], Mapping[str, Any]]],
) -> Any:
    """Call a dependency using the richest compatible signature without retries."""
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        arguments, keywords = candidates[0]
        return target(*arguments, **keywords)
    for arguments, keywords in candidates:
        try:
            signature.bind(*arguments, **keywords)
        except TypeError:
            continue
        return target(*arguments, **keywords)
    raise TypeError(f"Injected callable {target!r} has no supported task runtime signature.")


def _render_tool_result(result: TaskToolResult) -> str:
    return json.dumps(
        {
            "status": result.status,
            "tool": result.tool_name,
            "output": _json_safe(result.output),
            "error": result.error,
        },
        ensure_ascii=False,
        default=str,
    )


def _required_identifier(value: Any, label: str) -> str:
    normalized = _optional_identifier(value)
    if not normalized:
        raise ValueError(f"{label} must not be empty.")
    return normalized


def _optional_identifier(value: Any) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


def _normalized_name(value: Any) -> str:
    return str(value).strip()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return value
