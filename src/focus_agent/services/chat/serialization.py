"""Pure message/state serialization helpers for chat thread payloads and SSE frames."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from ...core.message_utils import (
    is_ai_message_type,
    is_human_message_type,
    is_tool_message_type,
    message_type_name,
)
from ...core.token_usage import message_token_usage
from ...transport.stream_events import (
    extract_visible_text_delta,
    sanitize_completed_visible_text,
)


def _list_content_to_visible_text(content: list[Any]) -> str:
    return extract_visible_text_delta(SimpleNamespace(content=content, type="ai"))


def message_content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, dict):
        for key in ("text", "content"):
            if key in content:
                return message_content_to_text(content.get(key))
        return json.dumps(json_safe(content), ensure_ascii=False)
    if isinstance(content, list):
        return _list_content_to_visible_text(content)
    return str(content)


def confirmed_visible_ai_text(content: Any) -> str:
    return sanitize_completed_visible_text(message_content_to_text(content))


def json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if hasattr(value, "content") or hasattr(value, "tool_calls"):
        message_type = message_type_name(value)
        tool_calls = json_safe(getattr(value, "tool_calls", None))
        content = message_content_to_text(getattr(value, "content", ""))
        if is_ai_message_type(message_type):
            content = "" if tool_calls else confirmed_visible_ai_text(getattr(value, "content", ""))
        return {
            "type": message_type,
            "content": content,
            "tool_calls": tool_calls,
            "name": getattr(value, "name", None),
            "id": getattr(value, "id", None),
            "usage_metadata": json_safe(message_token_usage(value)),
        }
    return str(value)


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _turn_metadata_from_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    active_skill_ids = _normalize_string_list(
        value.get("active_skill_ids") or value.get("skill_ids")
    )
    prompt_mode = str(value.get("prompt_mode") or "").strip()
    selection_source = str(value.get("selection_source") or "").strip()
    matched_triggers = _normalize_string_list(value.get("matched_triggers"))
    metadata: dict[str, Any] = {}
    if active_skill_ids:
        metadata["active_skill_ids"] = active_skill_ids
    if prompt_mode:
        metadata["prompt_mode"] = prompt_mode
    if selection_source:
        metadata["selection_source"] = selection_source
    if matched_triggers:
        metadata["matched_triggers"] = matched_triggers
    confidence = value.get("confidence")
    if isinstance(confidence, (int, float)) and confidence > 0:
        metadata["confidence"] = round(float(confidence), 4)
    for key in ("skill_execution_plan", "execution_contract", "answer_verification"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            metadata[key] = json_safe(dict(nested))
    return metadata


def _turn_metadata_from_response_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return _turn_metadata_from_mapping(value.get("focus_agent"))


def _message_turn_metadata(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        direct = _turn_metadata_from_mapping(message.get("turn_metadata"))
        if direct:
            return direct
        additional_kwargs = message.get("additional_kwargs")
        if isinstance(additional_kwargs, Mapping):
            focus_agent = _turn_metadata_from_mapping(additional_kwargs.get("focus_agent"))
            if focus_agent:
                return focus_agent
            direct = _turn_metadata_from_mapping(additional_kwargs.get("turn_metadata"))
            if direct:
                return direct
        response_metadata = _turn_metadata_from_response_metadata(message.get("response_metadata"))
        if response_metadata:
            return response_metadata
        return _turn_metadata_from_mapping(message.get("focus_agent"))

    additional_kwargs = getattr(message, "additional_kwargs", None)
    if isinstance(additional_kwargs, Mapping):
        focus_agent = _turn_metadata_from_mapping(additional_kwargs.get("focus_agent"))
        if focus_agent:
            return focus_agent
        direct = _turn_metadata_from_mapping(additional_kwargs.get("turn_metadata"))
        if direct:
            return direct
    response_metadata = _turn_metadata_from_response_metadata(
        getattr(message, "response_metadata", None)
    )
    if response_metadata:
        return response_metadata
    return {}


def sse_frame(*, event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(json_safe(data), ensure_ascii=False)
    lines = [f"event: {event}"]
    for line in payload.splitlines() or [""]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def serialize_message(message: Any) -> dict[str, Any]:
    message_type = message_type_name(message)
    if isinstance(message, dict):
        raw_content = message.get("content", "")
        tool_calls = message.get("tool_calls")
        content = message_content_to_text(raw_content)
        if is_ai_message_type(message_type):
            content = "" if tool_calls else confirmed_visible_ai_text(raw_content)
        payload = {
            "type": message_type,
            "content": content,
            "tool_calls": json_safe(tool_calls),
            "name": message.get("name"),
            "id": message.get("id"),
            "usage_metadata": json_safe(message.get("usage_metadata")),
        }
        if is_tool_message_type(message_type):
            payload["tool_call_id"] = message.get("tool_call_id")
            payload["status"] = message.get("status")
        turn_metadata = _message_turn_metadata(message)
        if turn_metadata:
            payload["turn_metadata"] = turn_metadata
        metadata = _message_metadata(message)
        if metadata:
            payload["metadata"] = metadata
        return payload

    tool_calls = getattr(message, "tool_calls", None)
    content = message_content_to_text(getattr(message, "content", ""))
    if is_ai_message_type(message_type):
        content = "" if tool_calls else confirmed_visible_ai_text(getattr(message, "content", ""))
    payload = {
        "type": message_type,
        "content": content,
        "tool_calls": tool_calls,
        "name": getattr(message, "name", None),
        "id": getattr(message, "id", None),
        "usage_metadata": json_safe(message_token_usage(message)),
    }
    if is_tool_message_type(message_type):
        payload["tool_call_id"] = getattr(message, "tool_call_id", None)
        payload["status"] = getattr(message, "status", None)
    turn_metadata = _message_turn_metadata(message)
    if turn_metadata:
        payload["turn_metadata"] = turn_metadata
    metadata = _message_metadata(message)
    if metadata:
        payload["metadata"] = metadata
    return payload


def _message_metadata(message: Any) -> dict[str, Any] | None:
    if isinstance(message, dict):
        metadata = message.get("metadata")
        if isinstance(metadata, Mapping):
            return json_safe(dict(metadata))
        response_metadata = message.get("response_metadata")
    else:
        response_metadata = getattr(message, "response_metadata", None)
    if not isinstance(response_metadata, Mapping):
        return None
    focus_agent_metadata = response_metadata.get("focus_agent")
    if isinstance(focus_agent_metadata, Mapping):
        nested_metadata = focus_agent_metadata.get("metadata")
        if isinstance(nested_metadata, Mapping):
            return json_safe(dict(nested_metadata))
        return json_safe(dict(focus_agent_metadata))
    return None


def _thread_state_visible_message(message: Any) -> dict[str, Any] | None:
    payload = serialize_message(message)
    message_type = str(payload.get("type") or "").strip().lower()
    if not is_ai_message_type(message_type):
        return payload

    if payload.get("content"):
        return payload

    return payload if payload.get("tool_calls") else None


def _is_followed_by_tool_activity_before_next_user(
    messages: list[Any],
    *,
    index: int,
) -> bool:
    for later in messages[index + 1 :]:
        message_type = message_type_name(later)
        if is_human_message_type(message_type):
            return False
        if is_tool_message_type(message_type):
            return True
        if is_ai_message_type(message_type) and getattr(later, "tool_calls", None):
            return True
        if isinstance(later, dict) and is_ai_message_type(message_type) and later.get("tool_calls"):
            return True
    return False


def _turn_metadata_from_plan_meta(plan_meta: Any) -> dict[str, Any]:
    if not isinstance(plan_meta, Mapping):
        return {}
    metadata: dict[str, Any] = {}
    intent_plan = plan_meta.get("tool_intent_plan")
    if isinstance(intent_plan, Mapping):
        skill_execution_plan = intent_plan.get("skill_execution_plan")
        if isinstance(skill_execution_plan, Mapping):
            metadata["skill_execution_plan"] = json_safe(dict(skill_execution_plan))
    for key in ("execution_contract", "answer_verification"):
        nested = plan_meta.get(key)
        if isinstance(nested, Mapping):
            metadata[key] = json_safe(dict(nested))
    return metadata


def thread_state_messages(
    messages: list[Any],
    *,
    limit: int,
    turn_metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not messages:
        return []
    payloads: list[dict[str, Any]] = []
    visible_window = messages[-limit:]
    for index, message in enumerate(visible_window):
        payload = _thread_state_visible_message(message)
        if payload is not None:
            message_type = str(payload.get("type") or "").strip().lower()
            if (
                is_ai_message_type(message_type)
                and payload.get("content")
                and not payload.get("tool_calls")
                and _is_followed_by_tool_activity_before_next_user(visible_window, index=index)
            ):
                continue
            payloads.append(payload)
    if turn_metadata:
        for payload in reversed(payloads):
            if not is_ai_message_type(payload.get("type")):
                continue
            existing = payload.get("turn_metadata")
            if not isinstance(existing, Mapping):
                existing = {}
            payload["turn_metadata"] = {
                **json_safe(dict(turn_metadata)),
                **json_safe(dict(existing)),
            }
            break
    return payloads


def latest_final_ai_text(
    messages: list[Any], *, message_content_to_text: Callable[[Any], str]
) -> str | None:
    del message_content_to_text
    for message in reversed(messages):
        message_type = getattr(
            message, "type", message.__class__.__name__.replace("Message", "").lower()
        )
        if is_human_message_type(message_type):
            return None
        if is_tool_message_type(message_type):
            return None
        if is_ai_message_type(message_type) and not getattr(message, "tool_calls", None):
            text = confirmed_visible_ai_text(getattr(message, "content", ""))
            if text:
                return text
            continue
        if is_ai_message_type(message_type) and getattr(message, "tool_calls", None):
            return None
    return None


__all__ = [
    "confirmed_visible_ai_text",
    "is_ai_message_type",
    "is_human_message_type",
    "is_tool_message_type",
    "json_safe",
    "latest_final_ai_text",
    "message_content_to_text",
    "serialize_message",
    "sse_frame",
    "thread_state_messages",
]
