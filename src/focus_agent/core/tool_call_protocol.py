from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from langchain.messages import AIMessage, ToolMessage

DEFAULT_DANGLING_TOOL_CALL_ERROR = (
    "Tool call did not produce a result before the next model step."
)


def repair_dangling_tool_call_messages(
    messages: list[Any],
    *,
    repair_trailing: bool = True,
    error_message: str = DEFAULT_DANGLING_TOOL_CALL_ERROR,
) -> list[Any]:
    """Insert synthetic error ToolMessages for assistant tool calls without results."""

    repaired: list[Any] = []
    pending: dict[str, dict[str, Any]] = {}
    changed = False

    for message in messages:
        if isinstance(message, ToolMessage):
            call_id = tool_message_call_id(message)
            if pending and call_id not in pending:
                repaired.extend(
                    missing_tool_messages(pending.values(), error_message=error_message)
                )
                pending.clear()
                changed = True
            elif call_id in pending:
                pending.pop(call_id, None)
            repaired.append(message)
            continue

        if pending:
            repaired.extend(missing_tool_messages(pending.values(), error_message=error_message))
            pending.clear()
            changed = True

        repaired.append(message)
        if isinstance(message, AIMessage):
            pending = pending_tool_calls(message)

    if pending and repair_trailing:
        repaired.extend(missing_tool_messages(pending.values(), error_message=error_message))
        changed = True

    return repaired if changed else list(messages)


def missing_tool_messages(
    calls: Iterable[dict[str, Any]],
    *,
    error_message: str = DEFAULT_DANGLING_TOOL_CALL_ERROR,
) -> list[ToolMessage]:
    return [missing_tool_message(call, error_message=error_message) for call in calls]


def missing_tool_message(
    call: dict[str, Any],
    *,
    error_message: str = DEFAULT_DANGLING_TOOL_CALL_ERROR,
) -> ToolMessage:
    tool_name = str(call.get("name") or "tool").strip() or "tool"
    payload = {
        "status": "error",
        "tool": tool_name,
        "args": call.get("args") or {},
        "error": error_message,
    }
    return ToolMessage(
        content=json.dumps(payload, ensure_ascii=False, default=str),
        tool_call_id=str(call["id"]),
        name=tool_name,
        status="error",
        artifact={
            "runtime": {
                "dangling_tool_call_repaired": True,
                "cache_hit": False,
                "fallback_used": False,
            },
            "tool_name": tool_name,
        },
    )


def pending_tool_calls(message: AIMessage) -> dict[str, dict[str, Any]]:
    pending: dict[str, dict[str, Any]] = {}
    for index, raw_call in enumerate(getattr(message, "tool_calls", []) or []):
        if not isinstance(raw_call, dict):
            continue
        call_id = str(raw_call.get("id") or "").strip() or f"dangling-tool-call-{index + 1}"
        args = raw_call.get("args")
        if not isinstance(args, dict):
            args = {"_raw_args": args} if args is not None else {}
        pending[call_id] = {
            "id": call_id,
            "name": str(raw_call.get("name") or "tool").strip() or "tool",
            "args": args,
        }
    return pending


def tool_message_call_id(message: ToolMessage) -> str:
    return str(getattr(message, "tool_call_id", "") or "")


__all__ = [
    "DEFAULT_DANGLING_TOOL_CALL_ERROR",
    "missing_tool_message",
    "missing_tool_messages",
    "pending_tool_calls",
    "repair_dangling_tool_call_messages",
    "tool_message_call_id",
]
