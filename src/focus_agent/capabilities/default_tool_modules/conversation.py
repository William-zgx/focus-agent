from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from langchain.tools import tool

from ..ask_user_question import ASK_USER_QUESTION_TOOL_NAME


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
    if isinstance(message, Mapping):
        role = message.get("type") or message.get("role")
    else:
        role = getattr(message, "type", None) or getattr(message, "role", None)
    return str(role or type(message).__name__).replace("Message", "").lower()


def _message_content(message: Any) -> str:
    content = (
        message.get("content", message)
        if isinstance(message, Mapping)
        else getattr(message, "content", message)
    )
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


def _message_source_id(message: Any) -> str | None:
    if isinstance(message, Mapping):
        value = message.get("id") or message.get("message_id")
    else:
        value = getattr(message, "id", None) or getattr(message, "message_id", None)
    source_id = str(value or "").strip()
    return source_id or None


def _message_tool_call_id(message: Any) -> str | None:
    value = (
        message.get("tool_call_id")
        if isinstance(message, Mapping)
        else getattr(message, "tool_call_id", None)
    )
    tool_call_id = str(value or "").strip()
    return tool_call_id or None


def _render_source_message(
    message: Any,
    *,
    index: int,
    query: str = "",
    char_offset: int | None = None,
) -> dict[str, Any]:
    source_id = _message_source_id(message)
    content = _message_content(message)
    query_offset = content.casefold().find(query.casefold()) if query else -1
    if char_offset is not None:
        content_offset = min(max(char_offset, 0), len(content))
    elif query_offset >= 0:
        window_size = 1200
        content_offset = max(0, min(query_offset - window_size // 2, len(content) - window_size))
    else:
        content_offset = 0
    bounded_content = content[content_offset : content_offset + 1200]
    rendered = {
        "index": index,
        "id": source_id,
        "role": _message_role(message),
        "content": bounded_content,
        "content_offset": content_offset,
        "content_truncated": content_offset > 0
        or content_offset + len(bounded_content) < len(content),
    }
    tool_call_id = _message_tool_call_id(message)
    if tool_call_id is not None:
        rendered["tool_call_id"] = tool_call_id
    return rendered


def build_conversation_tools(
    *,
    checkpointer: Any,
    tool_catalog: Any,
    emit_tool_event: Callable[..., None],
    get_current_thread_id: Callable[[], str | None],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    @tool
    def conversation_summary(
        thread_id: str = "",
        recent_messages: int | None = None,
        query: str = "",
        offset: int = 0,
        anchor: str | None = None,
        char_offset: int | None = None,
    ) -> str:
        """Return the rolling summary and a bounded page of source messages."""
        tool_name = "conversation_summary"
        emit_tool_event(
            tool_name=tool_name,
            stage="start",
            thread_id=thread_id,
            recent_messages=recent_messages,
            query=query,
            offset=offset,
            anchor=anchor,
            char_offset=char_offset,
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
            if isinstance(offset, bool) or int(offset) != offset or int(offset) < 0:
                raise ValueError("offset must be a non-negative integer.")
            requested_offset = int(offset)
            normalized_query = str(query or "").strip()
            normalized_anchor = str(anchor or "").strip() or None
            if char_offset is not None and (
                isinstance(char_offset, bool)
                or int(char_offset) != char_offset
                or int(char_offset) < 0
            ):
                raise ValueError("char_offset must be a non-negative integer.")
            requested_char_offset = None if char_offset is None else int(char_offset)
            if requested_char_offset is not None and normalized_anchor is None:
                raise ValueError("char_offset requires an anchor.")
            checkpoint = checkpointer.get({"configurable": {"thread_id": effective_thread_id}})
            state = _extract_checkpoint_state(checkpoint)
            messages = list(state.get("messages", []) or [])
            candidate_indices = list(range(len(messages)))
            if normalized_query:
                query_folded = normalized_query.casefold()
                candidate_indices = [
                    index
                    for index, message in enumerate(messages)
                    if query_folded in _message_content(message).casefold()
                ]

            anchor_position = None
            if normalized_anchor is not None:
                for position, index in enumerate(candidate_indices):
                    source_id = _message_source_id(messages[index])
                    stable_id = source_id or f"cursor:{index}"
                    if normalized_anchor in {source_id, stable_id}:
                        anchor_position = position
                        break
                if anchor_position is None:
                    raise ValueError(
                        f"anchor {normalized_anchor!r} was not found in the source messages."
                    )

            if capped_messages == 0:
                selected_indices: list[int] = []
                next_offset = None
                next_anchor = None
            elif normalized_query or normalized_anchor is not None:
                start = anchor_position if anchor_position is not None else requested_offset
                selected_indices = candidate_indices[start : start + capped_messages]
                next_offset = (
                    start + len(selected_indices)
                    if start + len(selected_indices) < len(candidate_indices)
                    else None
                )
                next_anchor = (
                    _message_source_id(messages[selected_indices[-1]])
                    or f"cursor:{selected_indices[-1]}"
                    if selected_indices
                    else None
                )
            else:
                end = max(0, len(candidate_indices) - requested_offset)
                start = max(0, end - capped_messages)
                selected_indices = candidate_indices[start:end]
                next_offset = requested_offset + len(selected_indices) if start > 0 else None
                next_anchor = None

            source_messages = [
                _render_source_message(
                    messages[index],
                    index=index,
                    query=normalized_query,
                    char_offset=(
                        requested_char_offset
                        if normalized_anchor is not None
                        and index == candidate_indices[anchor_position]
                        else None
                    ),
                )
                for index in selected_indices
            ]
            continuation = None
            if next_offset is not None:
                continuation_anchor = None
                if normalized_anchor is not None and next_offset < len(candidate_indices):
                    continuation_index = candidate_indices[next_offset]
                    continuation_anchor = (
                        _message_source_id(messages[continuation_index])
                        or f"cursor:{continuation_index}"
                    )
                continuation = {
                    "thread_id": effective_thread_id,
                    "query": normalized_query,
                    "offset": next_offset,
                    "recent_messages": capped_messages,
                    "anchor": continuation_anchor,
                }
            payload = {
                "thread_id": effective_thread_id,
                "rolling_summary": state.get("rolling_summary", ""),
                "rolling_summary_source": "checkpoint.rolling_summary",
                "source_kind": "checkpoint_messages",
                "task_brief": state.get("task_brief", ""),
                "branch_meta": state.get("branch_meta"),
                "active_skill_ids": state.get("active_skill_ids", []),
                "message_count": len(messages),
                "recent_messages": source_messages,
                "message_query": normalized_query,
                "message_offset": requested_offset,
                "message_anchor": normalized_anchor,
                "next_offset": next_offset,
                "next_anchor": next_anchor,
                "truncated": continuation is not None,
                "continuation": continuation,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), thread_id=thread_id)
            raise

    @tool
    def ask_user_question(questions: list[dict[str, Any]]) -> str:
        """Collect structured multiple-choice answers from the user and pause until they reply."""
        # Runtime path: graph tool_executor interrupts for human input and never
        # auto-executes this function. Direct invoke is rejected.
        _ = questions
        raise RuntimeError(
            "ask_user_question requires a human answer and cannot be executed automatically."
        )

    return (
        {
            "conversation_summary": conversation_summary,
            ASK_USER_QUESTION_TOOL_NAME: ask_user_question,
        },
        {
            "conversation_summary": {
                "parallel_safe": True,
                "cacheable": True,
                "cache_scope": "thread",
                "max_observation_chars": 4000,
            },
            ASK_USER_QUESTION_TOOL_NAME: {
                "parallel_safe": False,
                "cacheable": False,
                "side_effect": True,
                "side_effect_kind": "human_input",
                "requires_approval": False,
                "risk_level": "low",
                "max_calls_per_turn": 1,
                "max_observation_chars": 8000,
                "toolset": "conversation",
                "intent_policies": ("planning", "execution"),
                "intent_tags": ("human_input", "clarification"),
            },
        },
    )
