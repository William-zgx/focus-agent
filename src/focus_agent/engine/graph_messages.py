from __future__ import annotations

import json
from typing import Any

from langchain.messages import AIMessage, HumanMessage, ToolMessage

from ..config import Settings
from ..model_registry import default_thinking_enabled, supports_thinking_mode

_REASONING_MESSAGE_BLOCK_TYPES = frozenset(
    {"reasoning", "reasoning_delta", "reasoning_content", "reasoningcontent", "thinking", "thinking_delta"}
)
_TOOL_MESSAGE_BLOCK_TYPES = frozenset(
    {"tool_call", "tool_call_chunk", "server_tool_call", "server_tool_call_chunk"}
)


def has_tool_calls(message: Any) -> bool:
    return bool(getattr(message, "tool_calls", None))


def find_trailing_tool_span_start(messages: list[Any]) -> int | None:
    if not messages:
        return None

    index = len(messages) - 1
    while index >= 0 and isinstance(messages[index], ToolMessage):
        index -= 1

    if index < 0:
        return None
    if has_tool_calls(messages[index]):
        return index
    return None


def collapse_unanswered_trailing_humans(messages: list[Any]) -> list[Any]:
    if len(messages) < 2:
        return messages

    tail_start = len(messages)
    index = len(messages) - 1
    while index >= 0 and isinstance(messages[index], HumanMessage):
        tail_start = index
        index -= 1

    trailing_human_count = len(messages) - tail_start
    if trailing_human_count <= 1:
        return messages
    return [*messages[:tail_start], messages[-1]]


def messages_for_model(state: dict[str, Any]) -> list[Any]:
    recent_messages = list(state.get("recent_messages") or [])
    messages = list(state.get("messages", []) or [])
    trailing_tool_span_start = find_trailing_tool_span_start(messages)
    if trailing_tool_span_start is None:
        selected = collapse_unanswered_trailing_humans(recent_messages or messages)
    else:
        selected = collapse_unanswered_trailing_humans([*recent_messages, *messages[trailing_tool_span_start:]])
    return [sanitize_assistant_tool_call_message(message) for message in selected]


def count_tool_call_rounds_since_latest_human(messages: list[Any]) -> int:
    rounds = 0
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            rounds += 1
    return rounds


def should_force_tool_free_answer(messages: list[Any], *, max_rounds: int) -> bool:
    if not messages or not isinstance(messages[-1], ToolMessage):
        return False
    return count_tool_call_rounds_since_latest_human(messages) >= max_rounds


def message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def stringify_message_block(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "".join(stringify_message_block(item) for item in value)
    if isinstance(value, dict):
        for key in (
            "text",
            "content",
            "value",
            "reasoning_content",
            "reasoningcontent",
            "reasoning",
            "summary",
        ):
            if value.get(key) is not None:
                return stringify_message_block(value[key])
        return ""
    return str(value)


def sanitize_assistant_tool_call_message(message: Any) -> Any:
    if not isinstance(message, AIMessage) or not getattr(message, "tool_calls", None):
        return message
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return message

    visible_parts: list[str] = []
    reasoning_parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            if block.strip():
                visible_parts.append(block)
            continue
        if not isinstance(block, dict):
            text = stringify_message_block(block).strip()
            if text:
                visible_parts.append(text)
            continue
        block_type = str(block.get("type") or "").strip().lower()
        if block_type in _REASONING_MESSAGE_BLOCK_TYPES:
            text = stringify_message_block(block).strip()
            if text:
                reasoning_parts.append(text)
            continue
        if block_type in _TOOL_MESSAGE_BLOCK_TYPES:
            continue
        text = stringify_message_block(block).strip()
        if text:
            visible_parts.append(text)

    additional_kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
    if reasoning_parts and not additional_kwargs.get("reasoning_content"):
        additional_kwargs["reasoning_content"] = "".join(reasoning_parts)

    return AIMessage(
        content="".join(visible_parts).strip(),
        additional_kwargs=additional_kwargs,
        response_metadata=dict(getattr(message, "response_metadata", {}) or {}),
        name=getattr(message, "name", None),
        id=getattr(message, "id", None),
        tool_calls=list(getattr(message, "tool_calls", []) or []),
        invalid_tool_calls=list(getattr(message, "invalid_tool_calls", []) or []),
        usage_metadata=getattr(message, "usage_metadata", None),
    )


def thinking_mode_requires_reasoning_content(
    *,
    model_id: str,
    thinking_mode: str,
    settings: Settings,
) -> bool:
    normalized = str(thinking_mode or "").strip().lower()
    if normalized == "disabled":
        return False
    if normalized == "enabled":
        return supports_thinking_mode(model_id, settings=settings)
    return default_thinking_enabled(model_id, settings=settings)


def ensure_reasoning_content_for_tool_call_history(
    messages: list[Any],
    *,
    model_id: str,
    thinking_mode: str,
    settings: Settings,
) -> list[Any]:
    if not thinking_mode_requires_reasoning_content(
        model_id=model_id,
        thinking_mode=thinking_mode,
        settings=settings,
    ):
        return messages

    fixed: list[Any] = []
    for message in messages:
        if not isinstance(message, AIMessage) or not getattr(message, "tool_calls", None):
            fixed.append(message)
            continue

        additional_kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
        if stringify_message_block(additional_kwargs.get("reasoning_content")).strip():
            fixed.append(message)
            continue

        additional_kwargs["reasoning_content"] = "Tool-call reasoning was preserved for the provider protocol."
        fixed.append(
            AIMessage(
                content=getattr(message, "content", ""),
                additional_kwargs=additional_kwargs,
                response_metadata=dict(getattr(message, "response_metadata", {}) or {}),
                name=getattr(message, "name", None),
                id=getattr(message, "id", None),
                tool_calls=list(getattr(message, "tool_calls", []) or []),
                invalid_tool_calls=list(getattr(message, "invalid_tool_calls", []) or []),
                usage_metadata=getattr(message, "usage_metadata", None),
            )
        )
    return fixed


def latest_human_message_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message_text(message)
    return ""


def latest_final_ai_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            return message_text(message)
    return ""


def latest_turn_messages(messages: list[Any]) -> list[Any]:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index:]
    return messages


def collect_tool_names_since_latest_human(messages: list[Any]) -> list[str]:
    names: list[str] = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", None) or []:
                name = call.get("name") if isinstance(call, dict) else None
                if name:
                    names.append(str(name))
    names.reverse()
    return names
