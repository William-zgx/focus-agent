from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.engine import graph_tool_result_fallback, graph_web_result_fallback


def test_graph_tool_result_fallback_reexports_web_fallback_symbols() -> None:
    symbol_names = (
        "_fallback_web_answer_from_tool_results",
        "_latest_relevant_web_payloads",
        "_looks_like_live_web_fallback_payload",
        "_web_payload_main_answer",
        "_looks_like_internal_web_summary",
        "_looks_like_weather_query",
        "_contains_weather_marker",
        "_chinese_weather_summary_from_payloads",
        "_extract_concise_weather_text",
        "_first_result_text",
        "_web_payload_sources",
        "_reference_sources",
        "_payload_results",
        "_source_domain",
        "_looks_like_web_observation_payload",
        "_prompt_observation_payload",
    )

    for symbol_name in symbol_names:
        assert getattr(graph_tool_result_fallback, symbol_name) is getattr(
            graph_web_result_fallback,
            symbol_name,
        )


def test_graph_web_result_fallback_synthesizes_weather_with_source() -> None:
    answer = graph_web_result_fallback._fallback_web_answer_from_tool_results(
        [
            HumanMessage(content="今天北京天气怎么样？"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "weather-search",
                        "name": "web_search",
                        "args": {"query": "2026-05-27 北京 天气"},
                    }
                ],
            ),
            ToolMessage(
                content=(
                    '{"query":"2026-05-27 北京 天气","answer":"Partly cloudy.",'
                    '"results":[{"title":"北京天气预报",'
                    '"url":"https://weather.example/beijing",'
                    '"content":"今天白天：晴转多云，最高气温28℃；'
                    '今天夜间：多云转晴，最低气温18℃。"}]}'
                ),
                tool_call_id="weather-search",
            ),
        ]
    )

    assert answer.startswith("根据搜索结果，今天白天：晴转多云")
    assert "最低气温18℃" in answer
    assert "北京天气预报（weather.example）" in answer


def test_graph_web_result_fallback_prefers_fetched_official_pages() -> None:
    answer = graph_web_result_fallback._fallback_web_answer_from_tool_results(
        [
            HumanMessage(content="请核对 Python 3.13 和 HTTP 307 的官方文档。"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "search",
                        "name": "web_search",
                        "args": {"query": "Python 3.13 free-threaded mode"},
                    },
                    {
                        "id": "python-docs",
                        "name": "web_fetch",
                        "args": {"url": "https://docs.python.org/3/whatsnew/3.13.html"},
                    },
                    {
                        "id": "mdn-307",
                        "name": "web_fetch",
                        "args": {
                            "url": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Status/307"
                        },
                    },
                ],
            ),
            ToolMessage(
                content=(
                    '{"query":"Python 3.13 free-threaded mode","results":['
                    '{"title":"Python - Wikipedia","url":"https://en.wikipedia.org/wiki/Python"}]}'
                ),
                tool_call_id="search",
            ),
            ToolMessage(
                content=(
                    '{"url":"https://docs.python.org/3/whatsnew/3.13.html",'
                    '"title":"What’s New In Python 3.13",'
                    '"content":"Python 3.13 includes experimental support for running in a free-threaded mode."}'
                ),
                tool_call_id="python-docs",
            ),
            ToolMessage(
                content=(
                    '{"url":"https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Status/307",'
                    '"title":"307 Temporary Redirect - HTTP",'
                    '"content":"The HTTP 307 Temporary Redirect response status code indicates that the requested resource has temporarily moved."}'
                ),
                tool_call_id="mdn-307",
            ),
        ]
    )

    assert answer.startswith("根据已抓取页面")
    assert "experimental support" in answer
    assert "Temporary Redirect" in answer
    assert "https://docs.python.org/3/whatsnew/3.13.html" in answer
    assert "https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Status/307" in answer
    assert "Wikipedia" not in answer


def test_compacted_search_summary_is_not_presented_as_source_evidence():
    import json

    messages = [HumanMessage(content="最近几周 Agent 有哪些进展？")]
    for index in range(4):
        messages.extend(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": str(index), "name": "web_search", "args": {"query": "Agent release"}}
                    ],
                ),
                ToolMessage(
                    tool_call_id=str(index),
                    content=json.dumps(
                        {
                            "tool": "web_search",
                            "query": "Agent release",
                            "reference": "query=Agent release",
                            "summary": "web_search output was compressed for prompt budgeting.",
                            "truncated_by_context_policy": True,
                            "results": [
                                {
                                    "url": f"https://example.com/{index}",
                                    "title": f"Release {index}",
                                    "content": f"Source snippet {index}",
                                }
                            ],
                        }
                    ),
                ),
            ]
        )
    answer = graph_web_result_fallback._fallback_web_answer_from_tool_results(messages)
    assert "compressed" not in answer
    assert "query=" not in answer
    assert "https://example.com/3" in answer
    assert "Source snippet 3" in answer


def test_generic_page_body_survives_prompt_reference_and_duplicate_fetch():
    import json

    body = "城市公交在周末增加两条线路，每隔十五分钟发车。"
    payload = {"url": "https://example.com/transit", "content": body}
    messages = [
        HumanMessage(content="公交线路有什么变化？"),
        AIMessage(
            content="",
            tool_calls=[
                {"id": "fetch", "name": "web_fetch", "args": {"url": payload["url"]}},
                {"id": "again", "name": "web_fetch", "args": {"url": payload["url"]}},
            ],
        ),
        ToolMessage(
            tool_call_id="fetch",
            content=json.dumps(payload),
            artifact={
                "prompt_observation": json.dumps({"url": payload["url"], "content": ""}),
            },
        ),
        ToolMessage(
            tool_call_id="again",
            content=json.dumps(
                {
                    "final_url": payload["url"],
                    "content": "",
                    "truncated_by_context_policy": True,
                }
            ),
        ),
    ]
    answer = graph_web_result_fallback._fallback_web_answer_from_tool_results(messages)
    assert answer.count(body) == 1
    assert "未包含" not in answer
    synthesis = graph_tool_result_fallback._tool_result_synthesis_prompt(messages)[1].content
    assert body in synthesis
    assert payload["url"] in synthesis
    assert "fetched_page" in synthesis
    assert "compressed" not in synthesis


def test_synthesis_includes_web_continuation_with_original_source_only():
    import json

    source = "https://example.com/guide"
    reference = "tool-observation://web_fetch/full-guide"
    messages = [
        HumanMessage(content="请读取 https://example.com/guide 并说明限制"),
        AIMessage(
            content="", tool_calls=[{"id": "fetch", "name": "web_fetch", "args": {"url": source}}]
        ),
        ToolMessage(
            tool_call_id="fetch",
            content=json.dumps(
                {
                    "url": source,
                    "content": "Introduction",
                    "artifact_ref": reference,
                }
            ),
        ),
        AIMessage(
            content="",
            tool_calls=[
                {"id": "read", "name": "artifact_read", "args": {"artifact_id": reference}},
                {"id": "unrelated", "name": "artifact_read", "args": {"artifact_id": "local.txt"}},
            ],
        ),
        ToolMessage(
            tool_call_id="read",
            content=json.dumps(
                {
                    "artifact_id": reference,
                    "offset": 20000,
                    "content": "The recovered section lists the limitations.",
                }
            ),
        ),
        ToolMessage(
            tool_call_id="unrelated",
            content=json.dumps(
                {
                    "artifact_id": "local.txt",
                    "content": "Unrelated local fact",
                }
            ),
        ),
    ]
    prompt = graph_tool_result_fallback._tool_result_synthesis_prompt(messages)[1].content
    assert "recovered section lists the limitations" in prompt
    assert source in prompt
    assert "Unrelated local fact" not in prompt


def test_synthesis_digest_keeps_every_fetched_page_whole():
    import json as _json

    from langchain.messages import AIMessage, HumanMessage, ToolMessage

    from focus_agent.engine.graph_tool_result_fallback import _tool_result_synthesis_prompt

    vendors = ["openai", "anthropic", "google", "mistral", "meta"]
    messages = [HumanMessage(content="Compare the latest flagship model pricing of each vendor")]
    for index, vendor in enumerate(vendors):
        call_id = f"fetch-{index}"
        url = f"https://{vendor}.example/pricing"
        messages.append(
            AIMessage(
                content="",
                tool_calls=[{"id": call_id, "name": "web_fetch", "args": {"url": url}}],
            )
        )
        body = f"{vendor} flagship model pricing latest " * 300
        messages.append(
            ToolMessage(
                content=_json.dumps({"url": url, "title": f"{vendor} pricing", "content": body}),
                tool_call_id=call_id,
            )
        )

    digest = _tool_result_synthesis_prompt(messages)[1].content

    # The earliest page must survive even though later pages are long.
    for vendor in vendors:
        assert f"https://{vendor}.example/pricing" in digest
    assert digest.count('"source_type": "fetched_page"') == len(vendors)
