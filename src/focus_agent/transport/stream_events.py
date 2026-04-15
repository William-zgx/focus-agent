from __future__ import annotations

import json
from typing import Any


TEXT_BLOCK_TYPES = {
    'text',
    'text_delta',
    'output_text',
    'output_text_delta',
    'input_text',
    'input_text_delta',
}

REASONING_BLOCK_TYPES = {
    'reasoning',
    'reasoning_delta',
    'thinking',
    'thinking_delta',
}

TOOL_BLOCK_TYPES = {
    'tool_call',
    'tool_call_chunk',
    'server_tool_call',
    'server_tool_call_chunk',
}


def _stringify(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return ''.join(_stringify(item) for item in value)
    if isinstance(value, dict):
        for key in ('text', 'content', 'value', 'chunk', 'reasoning', 'summary'):
            if key in value and value[key] is not None:
                return _stringify(value[key])
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _iter_blocks(message_chunk: Any) -> list[Any]:
    for attr in ('content_blocks', 'content'):
        value = getattr(message_chunk, attr, None)
        if isinstance(value, list):
            return value
    return []


def extract_visible_text_delta(message_chunk: Any) -> str:
    content = getattr(message_chunk, 'content', None)
    if isinstance(content, str):
        return content

    parts: list[str] = []
    for block in _iter_blocks(message_chunk):
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            parts.append(_stringify(block))
            continue
        block_type = str(block.get('type') or '')
        if block_type in REASONING_BLOCK_TYPES or block_type in TOOL_BLOCK_TYPES:
            continue
        if block_type in TEXT_BLOCK_TYPES or ('text' in block and block_type not in TOOL_BLOCK_TYPES):
            text = _stringify(block.get('text') or block.get('content') or block.get('value'))
            if text:
                parts.append(text)
    return ''.join(parts)


def extract_reasoning_delta(message_chunk: Any) -> str:
    parts: list[str] = []
    for block in _iter_blocks(message_chunk):
        if not isinstance(block, dict):
            continue
        block_type = str(block.get('type') or '')
        if block_type not in REASONING_BLOCK_TYPES:
            continue
        text = _stringify(
            block.get('reasoning')
            or block.get('summary')
            or block.get('text')
            or block.get('content')
            or block.get('value')
        )
        if text:
            parts.append(text)
    return ''.join(parts)


def extract_text_delta(message_chunk: Any) -> str:
    return extract_visible_text_delta(message_chunk)


def extract_tool_call_chunks(message_chunk: Any) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for block in _iter_blocks(message_chunk):
        if not isinstance(block, dict):
            continue
        block_type = str(block.get('type') or '')
        if block_type not in TOOL_BLOCK_TYPES:
            continue
        chunks.append(
            {
                'id': block.get('id') or block.get('tool_call_id') or block.get('call_id'),
                'name': block.get('name'),
                'args_delta': _stringify(block.get('args') or block.get('args_text') or block.get('input')),
                'raw': block,
            }
        )
    return chunks


def sanitize_stream_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = dict(metadata or {})
    allowed_keys = {
        'langgraph_node',
        'langgraph_path',
        'langgraph_step',
        'tags',
        'run_id',
        'model_name',
        'ls_provider',
    }
    return {key: value for key, value in metadata.items() if key in allowed_keys and value is not None}


def map_custom_payload_to_event(payload: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(payload, dict):
        if payload.get('event') == 'tool':
            stage = str(payload.get('stage') or 'delta')
            event_name = {
                'start': 'tool.start',
                'delta': 'tool.delta',
                'progress': 'tool.delta',
                'end': 'tool.end',
                'error': 'tool.error',
            }.get(stage, 'tool.delta')
            return event_name, dict(payload)
        if payload.get('event') == 'status':
            return 'status', dict(payload)
        return 'custom', dict(payload)
    return 'custom', {'value': payload}


def extract_tool_requests_from_updates(data: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for node_name, node_state in (data or {}).items():
        messages = []
        if isinstance(node_state, dict):
            messages = list(node_state.get('messages') or [])
        for message in messages:
            for tool_call in getattr(message, 'tool_calls', []) or []:
                results.append(
                    {
                        'node': node_name,
                        'tool_name': tool_call.get('name'),
                        'tool_call_id': tool_call.get('id'),
                        'args': tool_call.get('args'),
                    }
                )
    return results


def extract_tool_results_from_updates(data: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for node_name, node_state in (data or {}).items():
        messages = []
        if isinstance(node_state, dict):
            messages = list(node_state.get('messages') or [])
        for message in messages:
            message_type = getattr(message, 'type', '')
            if message_type != 'tool':
                continue
            results.append(
                {
                    'node': node_name,
                    'tool_call_id': getattr(message, 'tool_call_id', None),
                    'content': _stringify(getattr(message, 'content', '')),
                    'name': getattr(message, 'name', None),
                }
            )
    return results
