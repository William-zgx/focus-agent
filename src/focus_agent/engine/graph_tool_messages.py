"""Shared helpers for reading tool calls and tool results out of message history."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from langchain.messages import ToolMessage


def _tool_calls(message: Any) -> Iterator[tuple[str, Mapping[str, Any]]]:
    for call in getattr(message, "tool_calls", None) or ():
        if not isinstance(call, Mapping):
            continue
        call_id = str(call.get("id") or "").strip()
        if call_id:
            yield call_id, call


def tool_call_names_by_id(messages: Iterable[Any]) -> dict[str, str]:
    """Map tool-call id to tool name for every named tool call in ``messages``."""

    names: dict[str, str] = {}
    for message in messages:
        for call_id, call in _tool_calls(message):
            name = str(call.get("name") or "").strip()
            if name:
                names[call_id] = name
    return names


def iter_tool_results(
    messages: Iterable[Any],
) -> Iterator[tuple[ToolMessage, str, Mapping[str, Any]]]:
    """Yield ``(tool_message, tool_name, tool_args)`` in message order.

    Each result is matched against the tool calls seen *before* it. Results
    without a matching named call yield an empty name and empty args.
    """

    calls: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for message in messages:
        for call_id, call in _tool_calls(message):
            name = str(call.get("name") or "").strip()
            if name:
                args = call.get("args")
                calls[call_id] = (name, args if isinstance(args, Mapping) else {})
        if isinstance(message, ToolMessage):
            call_id = str(getattr(message, "tool_call_id", "") or "").strip()
            name, args = calls.get(call_id, ("", {}))
            yield message, name, args


def tool_message_json(message: Any) -> Any:
    """Return the JSON value carried by a tool message, or ``None`` if it has none.

    Structured (list/dict) content is returned as-is; string content is parsed.
    """

    content = getattr(message, "content", "")
    if isinstance(content, (dict, list)):
        return content
    if not isinstance(content, str):
        return None
    try:
        return json.loads(content)
    except ValueError:
        return None


__all__ = ["iter_tool_results", "tool_call_names_by_id", "tool_message_json"]
