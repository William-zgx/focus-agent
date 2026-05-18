from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain.tools import tool


def _extract_checkpoint_state(checkpoint: dict[str, Any] | None) -> dict[str, Any]:
    if not checkpoint:
        return {}
    values = checkpoint.get("channel_values") or {}
    if isinstance(values, dict):
        root = values.get("__root__")
        if isinstance(root, dict):
            return dict(root)
        return dict(values)
    return {}


def _message_role(message: Any) -> str:
    role = getattr(message, "type", None) or getattr(message, "role", None)
    return str(role or type(message).__name__).replace("Message", "").lower()


def _message_content(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def build_conversation_tools(
    *,
    checkpointer: Any,
    tool_catalog: Any,
    emit_tool_event: Callable[..., None],
    get_current_thread_id: Callable[[], str | None],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    @tool
    def conversation_summary(thread_id: str = "", recent_messages: int | None = None) -> str:
        """Return the latest saved rolling summary and recent messages for a thread."""
        tool_name = "conversation_summary"
        emit_tool_event(
            tool_name=tool_name, stage="start", thread_id=thread_id, recent_messages=recent_messages
        )
        try:
            if checkpointer is None:
                raise RuntimeError("Conversation checkpointer is not configured.")
            effective_thread_id = thread_id.strip() or get_current_thread_id()
            if not effective_thread_id:
                raise ValueError("thread_id is required outside an active graph run.")
            requested_messages = (
                tool_catalog.conversation_summary.default_recent_messages
                if recent_messages is None
                else int(recent_messages)
            )
            capped_messages = max(
                0,
                min(requested_messages, tool_catalog.conversation_summary.max_recent_messages),
            )
            checkpoint = checkpointer.get({"configurable": {"thread_id": effective_thread_id}})
            state = _extract_checkpoint_state(checkpoint)
            messages = list(state.get("messages", []) or [])
            recent = [
                {
                    "role": _message_role(message),
                    "content": _message_content(message)[:1200],
                }
                for message in messages[-capped_messages:]
            ]
            payload = {
                "thread_id": effective_thread_id,
                "rolling_summary": state.get("rolling_summary", ""),
                "task_brief": state.get("task_brief", ""),
                "branch_meta": state.get("branch_meta"),
                "active_skill_ids": state.get("active_skill_ids", []),
                "message_count": len(messages),
                "recent_messages": recent,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), thread_id=thread_id)
            raise

    return (
        {"conversation_summary": conversation_summary},
        {
            "conversation_summary": {
                "parallel_safe": True,
                "cacheable": True,
                "cache_scope": "thread",
                "max_observation_chars": 4000,
            },
        },
    )
