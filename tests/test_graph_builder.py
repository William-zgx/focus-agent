from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import tool

from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.graph_builder import (
    _count_tool_call_rounds_since_latest_human,
    _looks_like_textual_tool_call_artifact,
    _messages_for_model,
    _should_force_tool_free_answer,
    build_graph,
)


def test_messages_for_model_keeps_current_tool_exchange():
    state = {
        "recent_messages": [
            HumanMessage(content="北京天气"),
        ],
        "messages": [
            HumanMessage(content="北京天气"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tool-call-1",
                        "name": "web_search",
                        "args": {"query": "beijing weather"},
                    }
                ],
            ),
            ToolMessage(content='{"forecast":"sunny"}', tool_call_id="tool-call-1"),
        ],
    }

    messages = _messages_for_model(state)

    assert len(messages) == 3
    assert isinstance(messages[0], HumanMessage)
    assert isinstance(messages[1], AIMessage)
    assert isinstance(messages[2], ToolMessage)


def test_messages_for_model_uses_recent_messages_when_no_tool_exchange_is_active():
    state = {
        "recent_messages": [
            HumanMessage(content="今天北京天气怎么样"),
            AIMessage(content="今天北京晴。"),
        ],
        "messages": [
            HumanMessage(content="今天北京天气怎么样"),
            AIMessage(content="今天北京晴。"),
            HumanMessage(content="顺便说下上海"),
        ],
    }

    messages = _messages_for_model(state)

    assert [message.content for message in messages] == [
      "今天北京天气怎么样",
      "今天北京晴。",
    ]


def test_count_tool_call_rounds_since_latest_human_ignores_older_turns():
    messages = [
        HumanMessage(content="旧问题"),
        AIMessage(content="", tool_calls=[{"id": "call-old", "name": "web_search", "args": {"query": "old"}}]),
        ToolMessage(content='{"query":"old"}', tool_call_id="call-old"),
        AIMessage(content="旧回答"),
        HumanMessage(content="新问题"),
        AIMessage(content="", tool_calls=[{"id": "call-1", "name": "web_search", "args": {"query": "one"}}]),
        ToolMessage(content='{"query":"one"}', tool_call_id="call-1"),
        AIMessage(content="", tool_calls=[{"id": "call-2", "name": "web_search", "args": {"query": "two"}}]),
        ToolMessage(content='{"query":"two"}', tool_call_id="call-2"),
    ]

    assert _count_tool_call_rounds_since_latest_human(messages) == 2
    assert _should_force_tool_free_answer(messages) is True


def test_graph_forces_tool_free_answer_after_two_tool_rounds(monkeypatch):
    class FakeRunnable:
        def __init__(self, owner, *, allow_tools: bool):
            self.owner = owner
            self.allow_tools = allow_tools

        def with_config(self, _config):
            return self

        def invoke(self, prompt_messages):
            self.owner.invocations.append(
                {
                    "allow_tools": self.allow_tools,
                    "messages": list(prompt_messages),
                }
            )
            if self.allow_tools:
                tool_call_count = sum(1 for item in self.owner.invocations if item["allow_tools"])
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": f"call-{tool_call_count}",
                            "name": "web_search",
                            "args": {"query": f"search-{tool_call_count}"},
                        }
                    ],
                )
            tool_free_count = sum(1 for item in self.owner.invocations if not item["allow_tools"])
            if tool_free_count == 1:
                return AIMessage(content="<｜DSML｜function_calls><｜DSML｜invoke name=\"web_search\"></｜DSML｜invoke>")
            return AIMessage(content="根据已有搜索结果，北京今天晴，白天大约25℃。")

    class FakeModel:
        def __init__(self):
            self.invocations = []

        def bind_tools(self, _tools):
            return FakeRunnable(self, allow_tools=True)

        def with_config(self, _config):
            return FakeRunnable(self, allow_tools=False)

    fake_model = FakeModel()

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    @tool
    def web_search(query: str) -> str:
        """Search the web."""
        return f'{{"query":"{query}","summary":"sunny"}}'

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(web_search,)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="今天北京天气咋样呀?")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    final_messages = result.value["messages"]
    assert isinstance(final_messages[-1], AIMessage)
    assert final_messages[-1].content == "根据已有搜索结果，北京今天晴，白天大约25℃。"

    tool_enabled_calls = [item for item in fake_model.invocations if item["allow_tools"]]
    tool_free_calls = [item for item in fake_model.invocations if not item["allow_tools"]]

    assert len(tool_enabled_calls) == 2
    assert len(tool_free_calls) == 2
    assert any(
        isinstance(message, SystemMessage) and "Do not call more tools" in message.content
        for message in tool_free_calls[0]["messages"]
    )
    assert any(
        isinstance(message, SystemMessage) and "Do not emit tool-call markup" in message.content
        for message in tool_free_calls[1]["messages"]
    )


def test_graph_repairs_textual_tool_call_artifact_before_tool_execution(monkeypatch):
    class FakeRunnable:
        def __init__(self, owner, *, allow_tools: bool):
            self.owner = owner
            self.allow_tools = allow_tools

        def with_config(self, _config):
            return self

        def invoke(self, prompt_messages):
            self.owner.invocations.append(
                {
                    "allow_tools": self.allow_tools,
                    "messages": list(prompt_messages),
                }
            )
            if self.allow_tools:
                tool_enabled_calls = sum(1 for item in self.owner.invocations if item["allow_tools"])
                if tool_enabled_calls == 1:
                    return AIMessage(content="<｜DSML｜function_calls><｜DSML｜invoke name=\"list_files\"></｜DSML｜invoke>")
                return AIMessage(content="不需要调用工具，OK。")
            return AIMessage(content="降级修复回答。")

    class FakeModel:
        def __init__(self):
            self.invocations = []

        def bind_tools(self, _tools):
            return FakeRunnable(self, allow_tools=True)

        def with_config(self, _config):
            return FakeRunnable(self, allow_tools=False)

    fake_model = FakeModel()

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    @tool
    def list_files(path: str = ".") -> str:
        """List files."""
        return '{"results":[]}'

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(list_files,)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="你好，做一个 UI 冒烟测试，简短回复 OK 即可")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    final_messages = result.value["messages"]
    assert isinstance(final_messages[-1], AIMessage)
    assert final_messages[-1].content == "不需要调用工具，OK。"

    tool_enabled_calls = [item for item in fake_model.invocations if item["allow_tools"]]
    tool_free_calls = [item for item in fake_model.invocations if not item["allow_tools"]]

    assert len(tool_enabled_calls) == 2
    assert len(tool_free_calls) == 0
    assert any(
        isinstance(message, SystemMessage) and "emit a real tool call" in message.content
        for message in tool_enabled_calls[1]["messages"]
    )


def test_detects_textual_tool_call_artifacts():
    assert _looks_like_textual_tool_call_artifact(
        AIMessage(content="<｜DSML｜function_calls><｜DSML｜invoke name=\"web_search\"></｜DSML｜invoke>")
    )
    assert not _looks_like_textual_tool_call_artifact(AIMessage(content="北京今天晴，最高气温25℃。"))
