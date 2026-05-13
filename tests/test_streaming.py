from focus_agent.core.tool_protocol import safe_visible_text_transition
from focus_agent.transport.stream_events import (
    STREAM_VISIBILITY_QUARANTINE,
    STREAM_VISIBILITY_VISIBLE,
    extract_reasoning_delta,
    extract_tool_call_chunks,
    extract_tool_requests_from_updates,
    extract_visible_text_candidate_delta,
    extract_visible_text_delta,
    looks_like_potential_stream_visible_text_artifact_prefix,
    looks_like_stream_visible_text_artifact,
    map_custom_payload_to_event,
    safe_stream_visible_text_transition,
    sanitize_stream_metadata,
    stream_visibility_phase_from_metadata,
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
    chunk = DummyChunk(content="hello world")
    assert extract_visible_text_delta(chunk) == "hello world"


def test_extract_visible_text_delta_from_content_blocks():
    chunk = DummyChunk(
        content=[
            {"type": "reasoning", "reasoning": "hidden plan"},
            {"type": "text", "text": "hello "},
            {"type": "tool_call_chunk", "name": "search", "args": "{"},
            {"type": "text_delta", "text": "world"},
        ]
    )
    assert extract_visible_text_delta(chunk) == "hello world"


def test_extract_visible_text_delta_ignores_tool_messages():
    chunk = DummyChunk(content='{"provider":"tavily"}', message_type="tool")
    assert extract_visible_text_delta(chunk) == ""


def test_extract_visible_text_delta_ignores_human_messages():
    chunk = DummyChunk(content="hello from the user", message_type="human")
    assert extract_visible_text_delta(chunk) == ""


def test_extract_visible_text_delta_ignores_textual_tool_call_string_payload():
    chunk = DummyChunk(
        content='<｜DSML｜function_calls><｜DSML｜invoke name="read_file"></｜DSML｜invoke>'
    )
    assert extract_visible_text_delta(chunk) == ""


def test_extract_visible_text_delta_ignores_spaced_dsml_tool_call_payload():
    chunk = DummyChunk(
        content=(
            "让我进一步获取几个关键来源的详细内容，以便给出更有深度的回答。\n\n"
            "< | | DSML | | tool_calls>\n"
            "< | | DSML | | invoke nameweb_search\">\n"
            "< | | DSML | | parameter name=\"query\" string=\"true\">AI breakthroughs</ | | DSML | | parameter>"
        )
    )
    assert extract_visible_text_delta(chunk) == ""


def test_extract_visible_text_delta_ignores_compacted_dsml_tool_call_payload():
    assert extract_visible_text_delta(DummyChunk(content='toolcalls/invoke namewebfetch">')) == ""
    chunk = DummyChunk(
        content=(
            'toolcalls/invoke namewebfetch">\n'
            'parameter namemax_chars" string="false">8000</ | | DSML | | parameter>\n'
            'parameter nameurl" string="true">https://example.com</ | | DSML | | parameter>'
        )
    )
    assert extract_visible_text_delta(chunk) == ""


def test_extract_visible_text_delta_ignores_empty_name_dsml_tool_call_payload():
    chunk = DummyChunk(
        content=(
            "您说得对，让我把时间校准到当下，搜一下 2026 年的最新动态。\n\n"
            'invoke name">\n'
            'parameter name="" string="true">direct</ | | DSML | | parameter>\n'
            'parameter name="" string="true">https://mem0.ai/blog/state-of-ai-agent-memory-2026'
            "</ | | DSML | | parameter>\n"
            'parameter name="" string="false">2</ | | DSML | | parameter>\n'
            "</ | | DSML | | invoke>"
        )
    )

    assert extract_visible_text_delta(chunk) == ""


def test_extract_visible_text_delta_ignores_degraded_line_protocol_payload():
    chunk = DummyChunk(
        content=(
            "· invoke name 2025 trends predictions multi-agent collaboration future</ | | DSML | | parameter>\n"
            "parameter name6</ | | DSML | | parameter>\n"
            "</ | | DSML | | invoke>"
        )
    )

    assert extract_visible_text_delta(chunk) == ""


def test_extract_visible_text_delta_ignores_bare_dsml_token_payload():
    assert extract_visible_text_delta(DummyChunk(content="| | DSML | |")) == ""
    assert extract_visible_text_delta(DummyChunk(content="</｜｜DSML｜｜parameter>")) == ""
    assert extract_visible_text_delta(DummyChunk(content="DSML 是一种标记格式说明。")) == "DSML 是一种标记格式说明。"


def test_extract_visible_text_delta_ignores_degraded_xmlish_tool_c_payload():
    chunk = DummyChunk(
        content=(
            "<tool_c>\n"
            '<invoke="web_fetch">\n'
            '<parameterurl" string="true">https://vectorize.io/articles/best-ai-agent-memory-systems</parameter>\n'
            '<parametermax_chars" string="false">12000</parameter>\n'
            "</invoke>\n"
            "</tool_c>"
        )
    )

    assert extract_visible_text_delta(chunk) == ""


def test_extract_visible_text_candidate_preserves_protocol_prefix_for_stateful_filtering():
    chunk = DummyChunk(content="<tool")

    assert extract_visible_text_candidate_delta(chunk) == "<tool"
    assert extract_visible_text_delta(chunk) == "<tool"


def test_extract_visible_text_delta_ignores_orphaned_tool_protocol_tail_fragments():
    assert extract_visible_text_delta(DummyChunk(content="alls>")) == ""
    assert extract_visible_text_delta(DummyChunk(content='="web_search">')) == ""
    assert extract_visible_text_delta(DummyChunk(content='="query" string="true">AI agent predictions')) == ""
    assert extract_visible_text_delta(DummyChunk(content='="query"true">AI agent frameworks comparison')) == ""
    assert (
        extract_visible_text_delta(
            DummyChunk(content='="url"true">https://alicelabs.ai/en/insights/best-ai-agent-frameworks-2026')
        )
        == ""
    )
    assert (
        extract_visible_text_delta(
            DummyChunk(content='="web_fetch="url" string="true">https://www.gartner.com/en/articles')
        )
        == ""
    )
    assert extract_visible_text_delta(DummyChunk(content='="max_chars" stringfalse">8000')) == ""
    assert extract_visible_text_delta(DummyChunk(content='="max_chars"false">6000')) == ""
    assert extract_visible_text_delta(DummyChunk(content="https://www.shrutigupta01.com/ai-agent-frameworks-in-2026/parameter>")) == ""
    assert extract_visible_text_delta(DummyChunk(content="12000parameter>")) == ""
    assert extract_visible_text_delta(DummyChunk(content="invoke>")) == ""
    assert extract_visible_text_delta(DummyChunk(content='="max_fetch_length" stringfalse8000parameter>')) == ""
    assert (
        extract_visible_text_delta(
            DummyChunk(
                content='="read="filepath" string="true">tool-observation://webfetch/call00ljJOwoeUmsjmBzMNhkx8505'
            )
        )
        == ""
    )
    assert extract_visible_text_delta(DummyChunk(content="tool-result://web_search/call-123")) == ""


def test_safe_visible_text_transition_holds_split_tool_call_prefixes():
    visible_text, pending_text = safe_visible_text_transition("", "tool")
    assert visible_text == ""
    assert pending_text == "tool"

    visible_text, pending_text = safe_visible_text_transition(
        visible_text,
        "calls/",
        pending_text=pending_text,
    )
    assert visible_text == ""
    assert pending_text == ""

    visible_text, pending_text = safe_visible_text_transition(
        visible_text,
        'invoke namewebfetch">\nparameter namemax_chars" string="false">8000',
        pending_text=pending_text,
    )

    assert visible_text == ""
    assert pending_text == ""


def test_safe_visible_text_transition_drops_split_degraded_invoke_name():
    visible_text, pending_text = safe_visible_text_transition("", "invoke")
    assert visible_text == ""
    assert pending_text == "invoke"

    visible_text, pending_text = safe_visible_text_transition(
        visible_text,
        " name 2025 trends predictions multi-agent collaboration future",
        pending_text=pending_text,
    )

    assert visible_text == ""
    assert pending_text == ""


def test_safe_visible_text_transition_drops_split_degraded_xmlish_tool_c():
    visible_text, pending_text = safe_visible_text_transition("", "<tool")
    assert visible_text == ""
    assert pending_text == "<tool"

    visible_text, pending_text = safe_visible_text_transition(
        visible_text,
        '_c>\n<invoke="web_fetch">',
        pending_text=pending_text,
    )

    assert visible_text == ""
    assert pending_text == ""


def test_safe_visible_text_transition_drops_orphaned_protocol_tail_fragments():
    visible_text, pending_text = safe_visible_text_transition("", "alls>")
    assert visible_text == ""
    assert pending_text == ""

    visible_text, pending_text = safe_visible_text_transition("", '="web_search">')
    assert visible_text == ""
    assert pending_text == ""

    visible_text, pending_text = safe_visible_text_transition("", '="query"true">AI agent frameworks comparison')
    assert visible_text == ""
    assert pending_text == ""

    visible_text, pending_text = safe_visible_text_transition(
        "",
        '="web_fetch="url" string="true">https://www.gartner.com/en/articles',
    )
    assert visible_text == ""
    assert pending_text == ""

    visible_text, pending_text = safe_visible_text_transition("", '="max_chars" stringfalse">8000')
    assert visible_text == ""
    assert pending_text == ""

    visible_text, pending_text = safe_visible_text_transition("", '="max_chars"false">6000')
    assert visible_text == ""
    assert pending_text == ""

    visible_text, pending_text = safe_visible_text_transition(
        "",
        '="read="filepath" string="true">tool-observation://webfetch/call00ljJOwoeUmsjmBzMNhkx8505',
    )
    assert visible_text == ""
    assert pending_text == ""

    visible_text, pending_text = safe_visible_text_transition("", "tool-result://web_search/call-123")
    assert visible_text == ""
    assert pending_text == ""

    visible_text, pending_text = safe_visible_text_transition(
        "",
        "https://www.shrutigupta01.com/ai-agent-frameworks-in-2026/parameter>",
    )
    assert visible_text == ""
    assert pending_text == ""


def test_safe_visible_text_transition_holds_split_degraded_assignment_prefix():
    visible_text, pending_text = safe_visible_text_transition("", "=")
    assert visible_text == ""
    assert pending_text == "="

    visible_text, pending_text = safe_visible_text_transition(
        visible_text,
        '"read=',
        pending_text=pending_text,
    )
    assert visible_text == ""
    assert pending_text == ""

    visible_text, pending_text = safe_visible_text_transition(
        visible_text,
        '"filepath" string="true">tool-observation://webfetch/call00ljJOwoeUmsjmBzMNhkx8505',
        pending_text=pending_text,
    )
    assert visible_text == ""
    assert pending_text == ""

    visible_text, pending_text = safe_visible_text_transition("", '="url"')
    assert visible_text == ""
    assert pending_text == '="url"'

    visible_text, pending_text = safe_visible_text_transition(
        visible_text,
        'true">https://alicelabs.ai/en/insights/best-ai-agent-frameworks-2026',
        pending_text=pending_text,
    )
    assert visible_text == ""
    assert pending_text == ""

    visible_text, pending_text = safe_visible_text_transition(
        "",
        "https://example.com/article",
    )
    assert visible_text == ""
    assert pending_text == "https://example.com/article"

    visible_text, pending_text = safe_visible_text_transition(
        visible_text,
        " is a normal cited URL.",
        pending_text=pending_text,
    )
    assert visible_text == "https://example.com/article is a normal cited URL."
    assert pending_text == ""


def test_safe_visible_text_transition_holds_split_bare_dsml_prefix():
    visible_text, pending_text = safe_visible_text_transition("", "< | | ")
    assert visible_text == ""
    assert pending_text == "< | | "

    visible_text, pending_text = safe_visible_text_transition(
        visible_text,
        "DSML | | invoke nameweb_search",
        pending_text=pending_text,
    )

    assert visible_text == ""
    assert pending_text == ""


def test_safe_visible_text_transition_releases_natural_prefix_text():
    visible_text, pending_text = safe_visible_text_transition("", "function")
    assert visible_text == ""
    assert pending_text == "function"

    visible_text, pending_text = safe_visible_text_transition(
        visible_text,
        " calls are ordinary JavaScript text.",
        pending_text=pending_text,
    )

    assert visible_text == "function calls are ordinary JavaScript text."
    assert pending_text == ""


def test_degraded_invoke_name_not_hidden_inside_natural_sentence():
    visible_text, pending_text = safe_visible_text_transition("", "普通文本里提到 invoke name resolution。")

    assert visible_text == "普通文本里提到 invoke name resolution。"
    assert pending_text == ""


def test_extract_visible_text_delta_ignores_bare_tool_call_close_tag():
    chunk = DummyChunk(content="</tool_call>")
    assert extract_visible_text_delta(chunk) == ""


def test_extract_visible_text_delta_ignores_mimo_xmlish_tool_call_payload():
    chunk = DummyChunk(
        content=(
            "function=web_search>\n"
            "<parameter=query>比亚迪 002594 2026年4月 单日涨幅 最大</parameter>\n"
            "<parameter=max_results>10</parameter>\n"
            "</<function=web_search>"
        )
    )
    assert extract_visible_text_delta(chunk) == ""


def test_extract_visible_text_delta_ignores_bracket_tool_marker_string_payload():
    chunk = DummyChunk(content="[web_fetch] 尝试获取沪指（000001）本周逐日行情数据，请稍等。")
    assert extract_visible_text_delta(chunk) == ""


def test_extract_visible_text_delta_ignores_internal_search_narration():
    chunk = DummyChunk(content="让我尝试获取更详细的日线数据：我已经从搜索结果中获取到了关键信息。")
    assert extract_visible_text_delta(chunk) == ""


def test_extract_visible_text_delta_ignores_internal_continuation_loop():
    chunk = DummyChunk(
        content=(
            "我来帮你查询华钰矿业（601020）近一周的行情数据。"
            "先获取详细的历史交易数据。让我查询东方财富网的具体行情页面。"
            "如果没有新指示，我将默认继续执行。请确认是否继续。"
        )
    )
    assert extract_visible_text_delta(chunk) == ""


def test_extract_visible_text_delta_ignores_english_internal_process_narration():
    assert extract_visible_text_delta(DummyChunk(content="Let me fetch the latest tool results.")) == ""
    assert extract_visible_text_delta(DummyChunk(content="I should look up one more source first.")) == ""
    assert extract_visible_text_delta(DummyChunk(content="Wait, I need to call the search tool.")) == ""
    assert extract_visible_text_delta(DummyChunk(content="Final answer: tool call follows")) == ""


def test_extract_visible_text_candidate_keeps_english_process_for_phase_gate():
    chunk = DummyChunk(content="Let me fetch the latest tool results.")

    assert extract_visible_text_candidate_delta(chunk) == "Let me fetch the latest tool results."
    assert looks_like_stream_visible_text_artifact(chunk.content)


def test_safe_stream_visible_text_transition_holds_split_english_process_prefixes():
    visible_text, pending_text = safe_stream_visible_text_transition("", "Let")
    assert visible_text == ""
    assert pending_text == "Let"

    visible_text, pending_text = safe_stream_visible_text_transition(
        visible_text,
        " me fetch the latest source.",
        pending_text=pending_text,
    )

    assert visible_text == ""
    assert pending_text == ""


def test_safe_stream_visible_text_transition_releases_plain_i_sentence():
    visible_text, pending_text = safe_stream_visible_text_transition("", "I")
    assert visible_text == ""
    assert pending_text == "I"

    visible_text, pending_text = safe_stream_visible_text_transition(
        visible_text,
        " agree with the conclusion.",
        pending_text=pending_text,
    )

    assert visible_text == "I agree with the conclusion."
    assert pending_text == ""


def test_potential_stream_visible_artifact_prefix_includes_english_markers():
    assert looks_like_potential_stream_visible_text_artifact_prefix("Let")
    assert looks_like_potential_stream_visible_text_artifact_prefix("I should")
    assert looks_like_potential_stream_visible_text_artifact_prefix("Wait")
    assert not looks_like_potential_stream_visible_text_artifact_prefix("普通结论")


def test_extract_visible_text_delta_keeps_plain_bracket_text():
    chunk = DummyChunk(content="[背景] 沪指本周围绕关键点位震荡。")
    assert extract_visible_text_delta(chunk) == "[背景] 沪指本周围绕关键点位震荡。"


def test_extract_visible_text_delta_ignores_textual_tool_call_text_blocks():
    chunk = DummyChunk(
        content=[
            {"type": "text", "text": "<｜DSML｜function_calls>"},
            {"type": "text_delta", "text": '<｜DSML｜invoke name="read_file">'},
            {"type": "text_delta", "text": "OK"},
        ]
    )
    assert extract_visible_text_delta(chunk) == "OK"


def test_extract_visible_text_delta_ignores_input_text_blocks():
    chunk = DummyChunk(
        content=[
            {"type": "input_text", "text": "prompt text"},
            {"type": "input_text_delta", "text": " more prompt text"},
            {"type": "output_text_delta", "text": "final answer"},
        ]
    )
    assert extract_visible_text_delta(chunk) == "final answer"


def test_extract_reasoning_delta_from_content_blocks():
    chunk = DummyChunk(
        content=[
            {"type": "reasoning", "reasoning": "Think step 1. "},
            {"type": "reasoning_delta", "text": "Think step 2."},
            {"type": "text", "text": "final answer"},
        ]
    )
    assert extract_reasoning_delta(chunk) == "Think step 1. Think step 2."


def test_extract_reasoning_delta_ignores_textual_tool_call_artifacts():
    chunk = DummyChunk(
        content=[
            {"type": "reasoning", "text": 'invoke name">\nparameter name="" string="true">direct'},
            {"type": "reasoning_delta", "text": "safe reasoning"},
        ]
    )

    assert extract_reasoning_delta(chunk) == "safe reasoning"


def test_extract_reasoning_delta_from_reasoning_content_blocks():
    chunk = DummyChunk(
        content=[
            {"type": "reasoning_content", "reasoning_content": "Keep tool-call rationale."},
            {"type": "text", "text": "final answer"},
        ]
    )
    assert extract_reasoning_delta(chunk) == "Keep tool-call rationale."


def test_extract_reasoning_delta_from_reasoningcontent_blocks():
    chunk = DummyChunk(
        content=[
            {"type": "reasoningcontent", "reasoningcontent": "Keep normalized reasoning."},
            {"type": "text", "text": "final answer"},
        ]
    )
    assert extract_reasoning_delta(chunk) == "Keep normalized reasoning."


def test_extract_reasoning_delta_from_additional_kwargs():
    chunk = DummyChunk(content="", content_blocks=None)
    chunk.additional_kwargs = {"reasoning_content": "Keep provider-specific reasoning."}
    assert extract_reasoning_delta(chunk) == "Keep provider-specific reasoning."


def test_extract_tool_call_chunks():
    chunk = DummyChunk(
        content=[
            {
                "type": "tool_call_chunk",
                "id": "call-1",
                "name": "search_web",
                "args": '{"q":"agent"}',
            },
        ]
    )
    assert extract_tool_call_chunks(chunk) == [
        {
            "id": "call-1",
            "name": "search_web",
            "args_delta": '{"q":"agent"}',
            "raw": {
                "type": "tool_call_chunk",
                "id": "call-1",
                "name": "search_web",
                "args": '{"q":"agent"}',
            },
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


def test_extract_tool_call_chunks_omits_null_optional_fields():
    chunk = DummyChunk(
        content="",
        tool_call_chunks=[{"id": None, "name": None, "args": "{}"}],
    )

    assert extract_tool_call_chunks(chunk) == [
        {
            "args_delta": "{}",
            "raw": {"id": None, "name": None, "args": "{}"},
        }
    ]


def test_map_custom_payload_to_tool_event():
    event_name, payload = map_custom_payload_to_event(
        {
            "event": "tool",
            "tool_name": "write_text_artifact",
            "stage": "end",
            "output": "artifact_saved:/tmp/a.md",
        }
    )
    assert event_name == "tool.result"
    assert payload["tool_name"] == "write_text_artifact"


def test_map_custom_payload_to_tool_event_preserves_tool_identity_aliases():
    event_name, payload = map_custom_payload_to_event(
        {
            "event": "tool",
            "stage": "start",
            "tool_call_id": "call-1",
            "tool_name": "search_web",
        }
    )

    assert event_name == "tool.requested"
    assert payload["tool_call_id"] == "call-1"
    assert payload["id"] == "call-1"
    assert payload["tool_name"] == "search_web"
    assert payload["name"] == "search_web"


def test_extract_tool_requests_from_updates():
    updates = {
        "agent_loop": {
            "messages": [
                DummyMessage(
                    tool_calls=[
                        {"id": "call-1", "name": "search_web", "args": {"q": "branch tree"}},
                    ]
                )
            ]
        }
    }
    assert extract_tool_requests_from_updates(updates) == [
        {
            "node": "agent_loop",
            "tool_name": "search_web",
            "name": "search_web",
            "tool_call_id": "call-1",
            "id": "call-1",
            "args": {"q": "branch tree"},
        }
    ]


def test_sanitize_stream_metadata():
    cleaned = sanitize_stream_metadata(
        {
            "langgraph_node": "agent_loop",
            "tags": ["demo"],
            "secret": "ignore-me",
        }
    )
    assert cleaned == {"langgraph_node": "agent_loop", "tags": ["demo"]}


def test_stream_visibility_phase_from_metadata_accepts_internal_fields_and_tags():
    assert stream_visibility_phase_from_metadata({"stream_phase": "visible"}) == STREAM_VISIBILITY_VISIBLE
    assert (
        stream_visibility_phase_from_metadata({"focus_agent_stream_phase": "quarantine"})
        == STREAM_VISIBILITY_QUARANTINE
    )
    assert (
        stream_visibility_phase_from_metadata({"tags": ["demo", "stream_phase:visible"]})
        == STREAM_VISIBILITY_VISIBLE
    )
    assert stream_visibility_phase_from_metadata({}) == STREAM_VISIBILITY_QUARANTINE
    assert stream_visibility_phase_from_metadata(None) == STREAM_VISIBILITY_QUARANTINE
    assert stream_visibility_phase_from_metadata({"stream_phase": "unknown"}) == STREAM_VISIBILITY_QUARANTINE


def test_sanitize_stream_metadata_strips_internal_stream_phase():
    cleaned = sanitize_stream_metadata(
        {
            "langgraph_node": "agent_loop",
            "stream_phase": "visible",
            "tags": ["demo", "stream_phase:visible", "focus_agent_stream_phase:quarantine"],
        }
    )

    assert cleaned == {"langgraph_node": "agent_loop", "tags": ["demo"]}
