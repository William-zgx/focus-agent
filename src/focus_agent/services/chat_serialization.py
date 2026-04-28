from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


def message_content_to_text(content: Any) -> str:
    if isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


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
        return {
            'type': getattr(value, 'type', value.__class__.__name__.replace('Message', '').lower()),
            'content': message_content_to_text(getattr(value, 'content', '')),
            'tool_calls': json_safe(getattr(value, 'tool_calls', None)),
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
    return {
        'type': getattr(message, 'type', message.__class__.__name__.replace('Message', '').lower()),
        'content': message_content_to_text(getattr(message, 'content', '')),
        'tool_calls': getattr(message, 'tool_calls', None),
        'name': getattr(message, 'name', None),
        'id': getattr(message, 'id', None),
        'usage_metadata': json_safe(getattr(message, 'usage_metadata', None)),
    }


def thread_state_messages(messages: list[Any], *, limit: int) -> list[dict[str, Any]]:
    if not messages:
        return []
    return [serialize_message(message) for message in messages[-limit:]]
