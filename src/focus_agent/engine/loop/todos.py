"""``todo_write``: the task list the model keeps during multi-step work.

The list is not an AgentState field. The latest successful ``todo_write`` call in
the message history is the current list, so a branch or a replay always sees the
list that belongs to its own transcript.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import suppress
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ...core.tool_call_protocol import messages_since_latest_human
from ..tools.messages import iter_tool_results, tool_message_failed

TODO_WRITE_TOOL_NAME = "todo_write"
MAX_TODOS = 20
MAX_TODO_CHARS = 200
_STATUSES = ("pending", "in_progress", "completed")
_DESCRIPTION = (
    "Keep a task list while working through multi-step tasks. Send the complete list "
    "every time; it replaces the previous one. Keep at most one item in_progress and "
    "mark items completed as soon as they are done. Send an empty list to clear it."
)
_CARRIED_OVER_NOTE = (
    "Written in an earlier turn; continue it only if the latest request continues that work."
)


class TodoItem(BaseModel):
    content: str = Field(description="The step, as a short imperative phrase.")
    status: Literal["pending", "in_progress", "completed"]


class TodoWriteInput(BaseModel):
    todos: list[TodoItem] = Field(max_length=MAX_TODOS, description="The full updated list.")


def normalize_todos(args: Mapping[str, Any]) -> list[dict[str, str]]:
    """Validate ``todo_write`` arguments; errors are worded for the model."""
    raw = args.get("todos")
    if not isinstance(raw, list):
        raise ValueError("todos must be a list of {content, status} objects")
    if len(raw) > MAX_TODOS:
        raise ValueError(f"at most {MAX_TODOS} todos; merge small steps or drop finished ones")
    todos: list[dict[str, str]] = []
    for position, item in enumerate(raw, start=1):
        if isinstance(item, BaseModel):
            item = item.model_dump()
        if not isinstance(item, Mapping):
            raise ValueError(f"todo {position} must be an object with content and status")
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"todo {position} needs non-empty content")
        content = " ".join(content.split())
        if len(content) > MAX_TODO_CHARS:
            raise ValueError(f"todo {position} is longer than {MAX_TODO_CHARS} characters")
        status = item.get("status")
        if status not in _STATUSES:
            raise ValueError(f"todo {position} status must be pending, in_progress or completed")
        todos.append({"content": content, "status": status})
    in_progress = sum(todo["status"] == "in_progress" for todo in todos)
    if in_progress > 1:
        raise ValueError(f"{in_progress} todos are in_progress; keep at most one in progress")
    return todos


def _summary(todos: list[dict[str, str]]) -> str:
    if not todos:
        return "Todos cleared."
    counts = dict.fromkeys(_STATUSES, 0)
    for todo in todos:
        counts[todo["status"]] += 1
    return (
        f"Todos updated: {counts['completed']} completed, "
        f"{counts['in_progress']} in progress, {counts['pending']} pending."
    )


def _todo_write(todos: list[TodoItem]) -> str:
    return _summary(normalize_todos({"todos": todos}))


def build_todo_write_tool() -> StructuredTool:
    todo_write = StructuredTool.from_function(
        func=_todo_write,
        name=TODO_WRITE_TOOL_NAME,
        description=_DESCRIPTION,
        args_schema=TodoWriteInput,
    )
    todo_write.metadata = {
        "display_name": "Todos",
        "parallel_safe": True,
        "cacheable": False,
        "side_effect": False,
        "requires_approval": False,
        "risk_level": "low",
        "toolset": "planning",
        "validator": normalize_todos,
    }
    return todo_write


def todos_block(messages: Sequence[Any]) -> str:
    """``## Current todos`` for the latest list, or "" when no item is still open."""
    latest: Any = None
    todos: list[dict[str, str]] = []
    for message, tool_name, args in iter_tool_results(messages):
        if tool_name != TODO_WRITE_TOOL_NAME or tool_message_failed(message):
            continue
        # A list written under older validation rules must not break later turns.
        with suppress(ValueError):
            todos, latest = normalize_todos(args), message
    if all(todo["status"] == "completed" for todo in todos):
        return ""
    lines = ["## Current todos"]
    if not any(message is latest for message in messages_since_latest_human(list(messages))):
        lines.append(_CARRIED_OVER_NOTE)
    lines.extend(
        f"{position}. [{todo['status']}] {todo['content']}"
        for position, todo in enumerate(todos, start=1)
    )
    return "\n".join(lines)


__all__ = [
    "MAX_TODOS",
    "TODO_WRITE_TOOL_NAME",
    "build_todo_write_tool",
    "normalize_todos",
    "todos_block",
]
