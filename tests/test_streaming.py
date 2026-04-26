from focus_agent.transport.stream_events import (
    extract_reasoning_delta,
    extract_tool_call_chunks,
    extract_tool_requests_from_updates,
    extract_visible_text_delta,
    map_custom_payload_to_event,
    sanitize_stream_metadata,
)


class DummyChunk:
    def __init__(self, content=None, content_blocks=None, message_type=None, tool_call_chunks=None):
        self.content = content
        self.content_blocks = content_blocks
        self.type = message_type
        self.tool_call_chunks = tool_call_chunks or []


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


def test_extract_visible_text_delta_ignores_tool_messages():
    chunk = DummyChunk(content='{"provider":"tavily"}', message_type='tool')
    assert extract_visible_text_delta(chunk) == ''


def test_extract_visible_text_delta_ignores_human_messages():
    chunk = DummyChunk(content='hello from the user', message_type='human')
    assert extract_visible_text_delta(chunk) == ''


def test_extract_visible_text_delta_ignores_textual_tool_call_string_payload():
    chunk = DummyChunk(content='<｜DSML｜function_calls><｜DSML｜invoke name="read_file"></｜DSML｜invoke>')
    assert extract_visible_text_delta(chunk) == ''


def test_extract_visible_text_delta_ignores_bracket_tool_marker_string_payload():
    chunk = DummyChunk(content='[web_fetch] 尝试获取沪指（000001）本周逐日行情数据，请稍等。')
    assert extract_visible_text_delta(chunk) == ''


def test_extract_visible_text_delta_keeps_plain_bracket_text():
    chunk = DummyChunk(content='[背景] 沪指本周围绕关键点位震荡。')
    assert extract_visible_text_delta(chunk) == '[背景] 沪指本周围绕关键点位震荡。'


def test_extract_visible_text_delta_ignores_textual_tool_call_text_blocks():
    chunk = DummyChunk(
        content=[
            {'type': 'text', 'text': '<｜DSML｜function_calls>'},
            {'type': 'text_delta', 'text': '<｜DSML｜invoke name="read_file">'},
            {'type': 'text_delta', 'text': 'OK'},
        ]
    )
    assert extract_visible_text_delta(chunk) == 'OK'


def test_extract_visible_text_delta_ignores_input_text_blocks():
    chunk = DummyChunk(
        content=[
            {'type': 'input_text', 'text': 'prompt text'},
            {'type': 'input_text_delta', 'text': ' more prompt text'},
            {'type': 'output_text_delta', 'text': 'final answer'},
        ]
    )
    assert extract_visible_text_delta(chunk) == 'final answer'


def test_extract_reasoning_delta_from_content_blocks():
    chunk = DummyChunk(
        content=[
            {'type': 'reasoning', 'reasoning': 'Think step 1. '},
            {'type': 'reasoning_delta', 'text': 'Think step 2.'},
            {'type': 'text', 'text': 'final answer'},
        ]
    )
    assert extract_reasoning_delta(chunk) == 'Think step 1. Think step 2.'


def test_extract_reasoning_delta_from_reasoning_content_blocks():
    chunk = DummyChunk(
        content=[
            {'type': 'reasoning_content', 'reasoning_content': 'Keep tool-call rationale.'},
            {'type': 'text', 'text': 'final answer'},
        ]
    )
    assert extract_reasoning_delta(chunk) == 'Keep tool-call rationale.'


def test_extract_reasoning_delta_from_reasoningcontent_blocks():
    chunk = DummyChunk(
        content=[
            {'type': 'reasoningcontent', 'reasoningcontent': 'Keep normalized reasoning.'},
            {'type': 'text', 'text': 'final answer'},
        ]
    )
    assert extract_reasoning_delta(chunk) == 'Keep normalized reasoning.'


def test_extract_reasoning_delta_from_additional_kwargs():
    chunk = DummyChunk(content="", content_blocks=None)
    chunk.additional_kwargs = {"reasoning_content": "Keep provider-specific reasoning."}
    assert extract_reasoning_delta(chunk) == "Keep provider-specific reasoning."


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


def test_extract_tool_call_chunks_from_chunk_attributes():
    chunk = DummyChunk(
        content="",
        tool_call_chunks=[
            {"id": "call-2", "name": "web_search", "args": '{"query":"power"}'},
        ],
    )

    assert extract_tool_call_chunks(chunk) == [
        {
            "id": "call-2",
            "name": "web_search",
            "args_delta": '{"query":"power"}',
            "raw": {"id": "call-2", "name": "web_search", "args": '{"query":"power"}'},
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
