import json

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain.tools import tool

from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.graph.policy_temporal import (
    _temporal_live_web_search_args,
    search_time_range,
)
from focus_agent.engine.graph_builder import build_graph


def _research_graph(
    monkeypatch, *, keep_searching=False, invalid_synthesis=False, repeat_query=False
):
    invocations = []
    calls = []

    class Runnable:
        def __init__(self, allow_tools=False):
            self.allow_tools = allow_tools

        def bind_tools(self, _tools):
            return Runnable(True)

        def with_config(self, _config):
            return self

        def invoke(self, messages):
            invocations.append((self.allow_tools, messages))
            count = sum(enabled for enabled, _ in invocations)
            if self.allow_tools and (keep_searching or count < 4):
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": f"search-{count}",
                            "name": "web_search",
                            "args": {
                                "query": "Agent project evidence"
                                if repeat_query
                                else f"Agent project evidence {count}"
                            },
                        }
                    ],
                )
            if self.allow_tools and count == 4:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "read-source",
                            "name": "web_fetch",
                            "args": {"url": "https://example.com/agent"},
                        }
                    ],
                )
            if invalid_synthesis:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "forbidden-more",
                            "name": "web_search",
                            "args": {"query": "again"},
                        }
                    ],
                )
            return AIMessage(
                content=(
                    "根据已取得的资料，该 Agent 将搜索和正文读取分开，并保留来源供核对。"
                    "[项目说明](https://example.com/agent)。无法确认性能差异，现有证据仅支持上述行为。"
                )
            )

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model", lambda *a, **kw: Runnable()
    )

    @tool
    def web_search(query: str) -> str:
        """Search for source documents."""
        calls.append(("web_search", query))
        return json.dumps(
            {
                "query": query,
                "summary": "web_search output was compressed for prompt budgeting.",
                "truncated_by_context_policy": True,
                "results": [
                    {
                        "title": "Agent project",
                        "url": "https://example.com/agent",
                        "content": "The agent separates search and page reading, retaining sources.",
                    }
                ],
            }
        )

    @tool
    def web_fetch(url: str) -> str:
        """Read a source document."""
        calls.append(("web_fetch", url))
        return json.dumps(
            {
                "url": url,
                "title": "Agent project",
                "content": "The agent separates search and page reading, retaining sources.",
            }
        )

    graph = build_graph(
        settings=Settings(), tool_registry=ToolRegistry(tools=(web_search, web_fetch))
    )
    result = graph.invoke(
        {
            "messages": [HumanMessage(content="请联网研究 Agent 的技术路线，比较两个项目。")],
            "selected_model": "openai:fake",
        },
        config={"recursion_limit": 100},
        context=RequestContext(user_id="researcher", root_thread_id="web-research-test"),
        version="v2",
    ).value
    return result, invocations, calls


def test_research_reads_source_after_four_rounds_before_synthesizing(monkeypatch):
    result, invocations, calls = _research_graph(monkeypatch)
    assert calls[0] == ("web_search", "Agent project evidence 1")
    assert any(name == "web_fetch" for name, _ in calls)
    assert "正文读取" in result["messages"][-1].content
    assert "无法确认性能差异" in result["messages"][-1].content
    assert "compressed" not in result["messages"][-1].content
    assert not any(not enabled for enabled, _ in invocations)


def test_research_budget_reserves_one_synthesis_and_records_degradation(monkeypatch):
    result, invocations, calls = _research_graph(monkeypatch, keep_searching=True)
    synthesis = [messages for enabled, messages in invocations if not enabled]
    assert len(synthesis) == 1
    assert len(calls) == 8
    assert any(isinstance(m, SystemMessage) and "No more tools" in m.content for m in synthesis[0])
    assert "正文读取" in result["messages"][-1].content
    assert result["task_outcome"]["status"] == "degraded_answer"
    assert result["task_outcome"]["warnings"]
    assert result["answer_verification"]["status"] != "verified"


def test_budget_synthesis_cannot_restart_tools_or_leak_internal_summary(monkeypatch):
    result, invocations, calls = _research_graph(
        monkeypatch, keep_searching=True, invalid_synthesis=True
    )
    assert len(calls) == 8
    assert sum(not enabled for enabled, _ in invocations) == 1
    final = result["messages"][-1]
    assert not final.tool_calls
    assert "compressed for prompt budgeting" not in final.content
    assert "https://example.com/agent" in final.content
    assert result["task_outcome"]["status"] == "degraded_answer"


def test_recent_weeks_query_is_anchored_without_losing_search_filters():
    args = _temporal_live_web_search_args(
        {
            "query": "最近几周Agent的发展有什么最新进展？",
            "time_range": "month",
            "include_domains": ["example.com"],
        },
        fallback_query="",
        current_utc_time="2026-10-03T12:53:01Z",
    )
    assert "2026-09-04" in args["query"] and "2026-10-03" in args["query"]
    assert args["time_range"] == "month"
    assert args["include_domains"] == ["example.com"]


def test_search_time_range_keeps_explicit_years_unfiltered():
    assert search_time_range("2024年最新政策") is None
    assert search_time_range("latest 2024 policy") is None
    assert search_time_range("最新政策") == "month"
    assert search_time_range("最新政策 编号 120241") == "month"


def test_repeated_identical_search_is_not_rerun_across_rounds(monkeypatch):
    result, invocations, calls = _research_graph(
        monkeypatch, keep_searching=True, repeat_query=True
    )

    assert calls == [("web_search", "Agent project evidence")]
    later_prompts = [messages for enabled, messages in invocations[1:] if enabled]
    assert any(
        isinstance(message, SystemMessage)
        and "Already retrieved in this turn" in message.content
        and 'web_search "Agent project evidence"' in message.content
        for message in later_prompts[0]
    )
    suppressed = [
        message
        for message in result["messages"]
        if getattr(message, "artifact", None)
        and message.artifact.get("runtime", {}).get("repeated_retrieval_suppressed")
    ]
    assert suppressed
    assert "正文读取" in result["messages"][-1].content


def test_explicit_year_is_not_rewritten_to_last_month():
    args = _temporal_live_web_search_args(
        {"query": "LangGraph 2026 年的最新进展"},
        fallback_query="",
        current_utc_time="2026-10-07T00:00:00Z",
    )
    assert "2026-09-08" not in args["query"]
    assert "2026" in args["query"]
