from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from ..transport.stream_events import (
    extract_visible_text_delta,
    sanitize_stream_visible_text,
)


def _message_type_name(message: Any) -> str:
    return str(
        getattr(message, 'type', message.__class__.__name__.replace('Message', '').lower()) or ''
    ).strip().lower()


def is_ai_message_type(message_type: Any) -> bool:
    return str(message_type or '').strip().lower() in {'ai', 'assistant'}


def _list_content_to_visible_text(content: list[Any]) -> str:
    return extract_visible_text_delta(SimpleNamespace(content=content, type='ai'))


def message_content_to_text(content: Any) -> str:
    if content is None:
        return ''
    if isinstance(content, list):
        return _list_content_to_visible_text(content)
    return str(content)


def confirmed_visible_ai_text(content: Any) -> str:
    return sanitize_stream_visible_text(message_content_to_text(content))


def json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if hasattr(value, 'content') or hasattr(value, 'tool_calls'):
        message_type = _message_type_name(value)
        tool_calls = json_safe(getattr(value, 'tool_calls', None))
        content = message_content_to_text(getattr(value, 'content', ''))
        if is_ai_message_type(message_type):
            content = '' if tool_calls else confirmed_visible_ai_text(getattr(value, 'content', ''))
        return {
            'type': message_type,
            'content': content,
            'tool_calls': tool_calls,
            'name': getattr(value, 'name', None),
            'id': getattr(value, 'id', None),
        }
    return str(value)


def sse_frame(*, event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(json_safe(data), ensure_ascii=False)
    lines = [f'event: {event}']
    for line in payload.splitlines() or ['']:
        lines.append(f'data: {line}')
    return '\n'.join(lines) + '\n\n'


def serialize_message(message: Any) -> dict[str, Any]:
    message_type = _message_type_name(message)
    tool_calls = getattr(message, 'tool_calls', None)
    content = message_content_to_text(getattr(message, 'content', ''))
    if is_ai_message_type(message_type):
        content = '' if tool_calls else confirmed_visible_ai_text(getattr(message, 'content', ''))
    return {
        'type': message_type,
        'content': content,
        'tool_calls': tool_calls,
        'name': getattr(message, 'name', None),
        'id': getattr(message, 'id', None),
        'usage_metadata': json_safe(getattr(message, 'usage_metadata', None)),
    }


def _thread_state_visible_message(message: Any) -> dict[str, Any] | None:
    payload = serialize_message(message)
    message_type = str(payload.get('type') or '').strip().lower()
    if not is_ai_message_type(message_type):
        return payload

    if payload.get('content'):
        return payload

    return payload if payload.get('tool_calls') else None


def thread_state_messages(messages: list[Any], *, limit: int) -> list[dict[str, Any]]:
    if not messages:
        return []
    payloads: list[dict[str, Any]] = []
    for message in messages[-limit:]:
        payload = _thread_state_visible_message(message)
        if payload is not None:
            payloads.append(payload)
    return payloads
