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
