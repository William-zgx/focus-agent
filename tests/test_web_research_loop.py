import json

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain.tools import tool

from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.core.request_context import RequestContext
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
        settings=Settings(agent_max_tool_rounds=8),
        tool_registry=ToolRegistry(tools=(web_search, web_fetch)),
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


def test_research_budget_reserves_one_synthesis_without_degrading_a_good_answer(monkeypatch):
    result, invocations, calls = _research_graph(monkeypatch, keep_searching=True)
    synthesis = [messages for enabled, messages in invocations if not enabled]
    assert len(synthesis) == 1
    assert len(calls) == 8
    assert any(
        isinstance(m, SystemMessage) and "tool budget for this turn is used up" in m.content
        for m in synthesis[0]
    )
    assert "正文读取" in result["messages"][-1].content
    # v2 records budget exhaustion in plan_meta instead of v1 answer_verification.
    assert result["plan_meta"]["tool_budget_exhausted"] is True
    assert result["task_outcome"]["status"] == "answered"


def test_budget_synthesis_cannot_restart_tools_or_leak_internal_summary(monkeypatch):
    result, invocations, calls = _research_graph(
        monkeypatch, keep_searching=True, invalid_synthesis=True
    )
    assert len(calls) == 8
    assert sum(not enabled for enabled, _ in invocations) == 2
    final = result["messages"][-1]
    assert not final.tool_calls
    assert "compressed for prompt budgeting" not in final.content
    assert "https://example.com/agent" in final.content
    assert final.additional_kwargs["tool_result_fallback_reason"] == "model_synthesis_failed"


def test_repeated_identical_search_is_not_rerun_across_rounds(monkeypatch):
    result, invocations, calls = _research_graph(
        monkeypatch, keep_searching=True, repeat_query=True
    )

    assert calls == [("web_search", "Agent project evidence")]
    suppressed = [
        message
        for message in result["messages"]
        if getattr(message, "artifact", None)
        and message.artifact.get("runtime", {}).get("repeated_retrieval_suppressed")
    ]
    assert suppressed
    assert "Already retrieved earlier in this turn" in suppressed[0].content
    assert "正文读取" in result["messages"][-1].content
