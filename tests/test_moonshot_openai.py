from langchain_core.messages import AIMessage, HumanMessage

from focus_agent.providers.moonshot_openai import MoonshotChatOpenAI


def test_moonshot_request_payload_preserves_reasoning_content_for_tool_call_history():
    model = MoonshotChatOpenAI(
        model="kimi-k2.6",
        api_key="test-key",
        base_url="https://api.moonshot.cn/v1",
    )

    payload = model._get_request_payload(
        [
            HumanMessage(content="先查天气"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "web_search",
                        "args": {"query": "北京天气"},
                    }
                ],
                additional_kwargs={"reasoning_content": "先搜索北京天气，再比较结果。"},
            ),
        ]
    )

    assistant = payload["messages"][-1]
    assert assistant["role"] == "assistant"
    assert assistant["reasoning_content"] == "先搜索北京天气，再比较结果。"
    assert assistant["tool_calls"][0]["function"]["name"] == "web_search"
    assert assistant["content"] is None


def test_moonshot_chat_result_keeps_reasoning_content_from_response():
    model = MoonshotChatOpenAI(
        model="kimi-k2.6",
        api_key="test-key",
        base_url="https://api.moonshot.cn/v1",
    )

    result = model._create_chat_result(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "先用工具收集天气，再输出比较结论。",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "web_search",
                                    "arguments": '{"query":"北京天气"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "model": "kimi-k2.6",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
    )

    message = result.generations[0].message
    assert message.additional_kwargs["reasoning_content"] == "先用工具收集天气，再输出比较结论。"
    assert message.tool_calls[0]["name"] == "web_search"


def test_moonshot_stream_chunk_keeps_reasoning_content():
    model = MoonshotChatOpenAI(
        model="kimi-k2.6",
        api_key="test-key",
        base_url="https://api.moonshot.cn/v1",
    )

    generation_chunk = model._convert_chunk_to_generation_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "继续沿用前一条工具推理。",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "function": {
                                    "name": "web_search",
                                    "arguments": '{"query":"北京天气"}',
                                },
                            }
                        ],
                    }
                }
            ]
        },
        default_chunk_class=AIMessage,
        base_generation_info=None,
    )

    assert generation_chunk is not None
    message = generation_chunk.message
    assert message.additional_kwargs["reasoning_content"] == "继续沿用前一条工具推理。"
    assert message.content == ""


def test_moonshot_request_payload_normalizes_langchain_reasoningcontent_blocks():
    model = MoonshotChatOpenAI(
        model="kimi-k2.6",
        api_key="test-key",
        base_url="https://api.moonshot.cn/v1",
    )

    payload = model._get_request_payload(
        [
            HumanMessage(content="继续"),
            AIMessage(
                content=[
                    {"type": "reasoningcontent", "reasoningcontent": "先比较天气。"},
                    {"type": "text", "text": "北京更暖和。"},
                ],
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "web_search",
                        "args": {"query": "北京天气"},
                    }
                ],
            ),
        ]
    )

    assistant = payload["messages"][-1]
    assert assistant["reasoning_content"] == "先比较天气。"
    assert assistant["content"] == [{"type": "text", "text": "北京更暖和。"}]


def test_moonshot_request_payload_converts_string_content_items_to_text_blocks():
    model = MoonshotChatOpenAI(
        model="kimi-k2.6",
        api_key="test-key",
        base_url="https://api.moonshot.cn/v1",
    )

    payload = model._get_request_payload(
        [
            HumanMessage(content="继续"),
            AIMessage(
                content=[
                    "",
                    {"type": "reasoningcontent", "reasoningcontent": "先比较天气。"},
                    "北京更暖和。",
                ],
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "web_search",
                        "args": {"query": "北京天气"},
                    }
                ],
            ),
        ]
    )

    assistant = payload["messages"][-1]
    assert assistant["reasoning_content"] == "先比较天气。"
    assert assistant["content"] == [{"type": "text", "text": "北京更暖和。"}]
