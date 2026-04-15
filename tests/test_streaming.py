from focus_agent.transport.stream_events import (
    extract_reasoning_delta,
    extract_tool_call_chunks,
    extract_tool_requests_from_updates,
    extract_visible_text_delta,
    map_custom_payload_to_event,
    sanitize_stream_metadata,
)


class DummyChunk:
    def __init__(self, content=None, content_blocks=None):
        self.content = content
        self.content_blocks = content_blocks


class DummyMessage:
    def __init__(self, tool_calls=None):
        self.tool_calls = tool_calls or []


def test_extract_visible_text_delta_from_string_content():
    chunk = DummyChunk(content='hello world')
    assert extract_visible_text_delta(chunk) == 'hello world'


def test_extract_visible_text_delta_from_content_blocks():
    chunk = DummyChunk(
        content=[
            {'type': 'reasoning', 'reasoning': 'hidden plan'},
            {'type': 'text', 'text': 'hello '},
            {'type': 'tool_call_chunk', 'name': 'search', 'args': '{'},
            {'type': 'text_delta', 'text': 'world'},
        ]
    )
    assert extract_visible_text_delta(chunk) == 'hello world'


def test_extract_reasoning_delta_from_content_blocks():
    chunk = DummyChunk(
        content=[
            {'type': 'reasoning', 'reasoning': 'Think step 1. '},
            {'type': 'reasoning_delta', 'text': 'Think step 2.'},
            {'type': 'text', 'text': 'final answer'},
        ]
    )
    assert extract_reasoning_delta(chunk) == 'Think step 1. Think step 2.'


def test_extract_tool_call_chunks():
    chunk = DummyChunk(
        content=[
            {'type': 'tool_call_chunk', 'id': 'call-1', 'name': 'search_web', 'args': '{"q":"agent"}'},
        ]
    )
    assert extract_tool_call_chunks(chunk) == [
        {
            'id': 'call-1',
            'name': 'search_web',
            'args_delta': '{"q":"agent"}',
            'raw': {'type': 'tool_call_chunk', 'id': 'call-1', 'name': 'search_web', 'args': '{"q":"agent"}'},
        }
    ]


def test_map_custom_payload_to_tool_event():
    event_name, payload = map_custom_payload_to_event(
        {'event': 'tool', 'tool_name': 'write_text_artifact', 'stage': 'end', 'output': 'artifact_saved:/tmp/a.md'}
    )
    assert event_name == 'tool.end'
    assert payload['tool_name'] == 'write_text_artifact'


def test_extract_tool_requests_from_updates():
    updates = {
        'agent_loop': {
            'messages': [
                DummyMessage(
                    tool_calls=[
                        {'id': 'call-1', 'name': 'search_web', 'args': {'q': 'branch tree'}},
                    ]
                )
            ]
        }
    }
    assert extract_tool_requests_from_updates(updates) == [
        {
            'node': 'agent_loop',
            'tool_name': 'search_web',
            'tool_call_id': 'call-1',
            'args': {'q': 'branch tree'},
        }
    ]


def test_sanitize_stream_metadata():
    cleaned = sanitize_stream_metadata(
        {
            'langgraph_node': 'agent_loop',
            'tags': ['demo'],
            'secret': 'ignore-me',
        }
    )
    assert cleaned == {'langgraph_node': 'agent_loop', 'tags': ['demo']}
