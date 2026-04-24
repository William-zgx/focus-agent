import time

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import tool

from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import ConfiguredModel, ModelCatalogConfig, Settings
from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import ContextBudget
from focus_agent.engine.graph_builder import (
    _classify_turn_tool_policy,
    _count_tool_call_rounds_since_latest_human,
    _ensure_reasoning_content_for_tool_call_history,
    _fallback_answer_from_tool_results,
    _looks_like_textual_tool_call_artifact,
    _messages_for_model,
    _repair_tool_free_answer_response,
    _should_force_tool_free_answer,
    _tools_for_policy,
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


def test_messages_for_model_sanitizes_assistant_tool_call_content_blocks():
    state = {
        "recent_messages": [],
        "messages": [
            HumanMessage(content="查一下北京和汉河的天气"),
            AIMessage(
                content=[
                    "",
                    {"type": "reasoningcontent", "reasoningcontent": "先比较两个城市天气。"},
                    "北京更暖和。",
                ],
                tool_calls=[
                    {
                        "id": "tool-call-1",
                        "name": "web_search",
                        "args": {"query": "北京 汉河 天气"},
                    }
                ],
            ),
            ToolMessage(content='{"forecast":"sunny"}', tool_call_id="tool-call-1"),
        ],
    }

    messages = _messages_for_model(state)

    assert len(messages) == 2
    assistant = messages[0]
    assert isinstance(assistant, AIMessage)
    assert assistant.content == "北京更暖和。"
    assert assistant.additional_kwargs["reasoning_content"] == "先比较两个城市天气。"


def test_ensure_reasoning_content_for_thinking_tool_call_history():
    settings = Settings(
        model="openai:custom-reasoning-pro",
        model_catalog=ModelCatalogConfig(
            models=(
                ConfiguredModel(
                    id="openai:custom-reasoning-pro",
                    supports_thinking=True,
                    default_thinking_enabled=True,
                ),
            ),
        ),
    )
    messages = [
        HumanMessage(content="查实时价格"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "tool-call-1",
                    "name": "web_search",
                    "args": {"query": "bitcoin price"},
                }
            ],
        ),
        ToolMessage(content='{"price":"78194.37"}', tool_call_id="tool-call-1"),
    ]

    fixed = _ensure_reasoning_content_for_tool_call_history(
        messages,
        model_id="openai:custom-reasoning-pro",
        thinking_mode="",
        settings=settings,
    )

    assistant = fixed[1]
    assert isinstance(assistant, AIMessage)
    assert assistant is not messages[1]
    assert assistant.additional_kwargs["reasoning_content"]
    assert assistant.tool_calls == messages[1].tool_calls


def test_ensure_reasoning_content_skips_disabled_thinking_mode():
    settings = Settings(
        model="openai:custom-reasoning-pro",
        model_catalog=ModelCatalogConfig(
            models=(
                ConfiguredModel(
                    id="openai:custom-reasoning-pro",
                    supports_thinking=True,
                    default_thinking_enabled=True,
                ),
            ),
        ),
    )
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "tool-call-1",
                    "name": "web_search",
                    "args": {"query": "bitcoin price"},
                }
            ],
        )
    ]

    fixed = _ensure_reasoning_content_for_tool_call_history(
        messages,
        model_id="openai:custom-reasoning-pro",
        thinking_mode="disabled",
        settings=settings,
    )

    assert fixed == messages
    assert "reasoning_content" not in fixed[0].additional_kwargs


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


def test_messages_for_model_keeps_only_latest_unanswered_human_turn():
    state = {
        "recent_messages": [
            HumanMessage(content="北京和上海哪个今天天气好？哪个气温高？"),
            HumanMessage(content="帮我写一篇300字左右描述小猫可爱的作文。直接发给我。"),
        ],
        "messages": [
            HumanMessage(content="北京和上海哪个今天天气好？哪个气温高？"),
            HumanMessage(content="帮我写一篇300字左右描述小猫可爱的作文。直接发给我。"),
        ],
    }

    messages = _messages_for_model(state)

    assert [message.content for message in messages] == [
        "帮我写一篇300字左右描述小猫可爱的作文。直接发给我。"
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


def test_graph_retries_tool_free_answer_until_markup_is_gone(monkeypatch):
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
            if tool_free_count < 3:
                return AIMessage(content="<｜DSML｜function_calls><｜DSML｜invoke name=\"web_search\"></｜DSML｜invoke>")
            return AIMessage(content="根据已有搜索结果，上海更暖和，北京更晴朗。")

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
            "messages": [HumanMessage(content="今天北京和上海天气如何？")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    final_messages = result.value["messages"]
    assert isinstance(final_messages[-1], AIMessage)
    assert final_messages[-1].content == "根据已有搜索结果，上海更暖和，北京更晴朗。"

    tool_free_calls = [item for item in fake_model.invocations if not item["allow_tools"]]
    assert len(tool_free_calls) == 3
    assert any(
        isinstance(message, SystemMessage) and "still contained internal tool-call markup" in message.content
        for message in tool_free_calls[2]["messages"]
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


def test_turn_tool_policy_classifies_direct_workspace_and_web_requests():
    assert _classify_turn_tool_policy("帮我写一篇300字左右描述小猫可爱的作文。直接发给我。") == "direct_answer"
    assert _classify_turn_tool_policy("不要联网。简单解释 LangGraph 的 checkpointer 是什么。") == "direct_answer"
    assert _classify_turn_tool_policy("找到仓库里使用 assemble_context 的位置。") == "workspace_lookup"
    assert _classify_turn_tool_policy("北京和上海哪个今天天气好？") == "live_web_research"
    assert _classify_turn_tool_policy("复现场景，做一下测试。") == "execution"


def test_fallback_answer_from_tool_results_preserves_workspace_findings():
    prompt_messages = [
        HumanMessage(content="找到仓库里使用 assemble_context 的位置。"),
        ToolMessage(
            content=(
                '{"query":"assemble_context","results":['
                '{"path":"src/focus_agent/engine/graph_builder.py","line_number":512,'
                '"line":"context_slice = build_context_slice(...)"},'
                '{"path":"src/focus_agent/core/context_policy.py","line_number":43,'
                '"line":"def assemble_context(state, mode):"}'
                "]}"
            ),
            tool_call_id="call-1",
        ),
    ]

    answer = _fallback_answer_from_tool_results(prompt_messages)

    assert "graph_builder.py:512" in answer
    assert "context_policy.py:43" in answer


def test_tools_for_policy_filters_web_and_write_tools():
    @tool
    def list_files(path: str = ".") -> str:
        """List files."""
        return path

    @tool
    def search_code(query: str) -> str:
        """Search code."""
        return query

    @tool
    def read_file(path: str) -> str:
        """Read file."""
        return path

    @tool
    def web_search(query: str) -> str:
        """Search web."""
        return query

    @tool
    def write_text_artifact(title: str, body: str) -> str:
        """Write artifact."""
        return title + body

    tools = [list_files, search_code, read_file, web_search, write_text_artifact]

    assert [item.name for item in _tools_for_policy("direct_answer", tools)] == []
    assert [item.name for item in _tools_for_policy("workspace_lookup", tools)] == [
        "list_files",
        "search_code",
        "read_file",
    ]
    assert [
        item.name
        for item in _tools_for_policy("workspace_lookup", tools, "找到仓库里 web_search 工具的定义位置")
    ] == ["search_code", "read_file"]
    assert [item.name for item in _tools_for_policy("live_web_research", tools)] == ["web_search"]
    assert [item.name for item in _tools_for_policy("execution", tools)] == [
        "list_files",
        "search_code",
        "read_file",
        "web_search",
        "write_text_artifact",
    ]


def test_graph_does_not_bind_tools_for_direct_answer_turn(monkeypatch):
    class FakeRunnable:
        def __init__(self, owner, *, allow_tools: bool, tool_names: list[str] | None = None):
            self.owner = owner
            self.allow_tools = allow_tools
            self.tool_names = tool_names or []

        def with_config(self, _config):
            return self

        def invoke(self, prompt_messages):
            self.owner.invocations.append(
                {
                    "allow_tools": self.allow_tools,
                    "tool_names": self.tool_names,
                    "messages": list(prompt_messages),
                }
            )
            return AIMessage(content="ReAct 是把推理和行动交替结合来完成任务的方法。")

    class FakeModel:
        def __init__(self):
            self.invocations = []
            self.bound_tool_batches = []

        def bind_tools(self, bound_tools):
            names = [item.name for item in bound_tools]
            self.bound_tool_batches.append(names)
            return FakeRunnable(self, allow_tools=True, tool_names=names)

        def with_config(self, _config):
            return FakeRunnable(self, allow_tools=False)

    fake_model = FakeModel()
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    @tool
    def web_search(query: str) -> str:
        """Search web."""
        return query

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(web_search,)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="用一句话说明什么是 ReAct。")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    final_messages = result.value["messages"]
    assert final_messages[-1].content == "ReAct 是把推理和行动交替结合来完成任务的方法。"
    assert fake_model.bound_tool_batches == []
    assert fake_model.invocations[0]["allow_tools"] is False
    assert any(
        isinstance(message, SystemMessage) and "answered directly" in message.content
        for message in fake_model.invocations[0]["messages"]
    )


def test_graph_binds_only_workspace_tools_for_workspace_turn(monkeypatch):
    class FakeRunnable:
        def __init__(self, owner, *, allow_tools: bool, tool_names: list[str] | None = None):
            self.owner = owner
            self.allow_tools = allow_tools
            self.tool_names = tool_names or []

        def with_config(self, _config):
            return self

        def invoke(self, prompt_messages):
            self.owner.invocations.append(
                {
                    "allow_tools": self.allow_tools,
                    "tool_names": self.tool_names,
                    "messages": list(prompt_messages),
                }
            )
            return AIMessage(content="assemble_context 在 graph_builder 和 context_policy 中使用。")

    class FakeModel:
        def __init__(self):
            self.invocations = []
            self.bound_tool_batches = []

        def bind_tools(self, bound_tools):
            names = [item.name for item in bound_tools]
            self.bound_tool_batches.append(names)
            return FakeRunnable(self, allow_tools=True, tool_names=names)

        def with_config(self, _config):
            return FakeRunnable(self, allow_tools=False)

    fake_model = FakeModel()
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    @tool
    def search_code(query: str) -> str:
        """Search code."""
        return query

    @tool
    def read_file(path: str) -> str:
        """Read file."""
        return path

    @tool
    def web_search(query: str) -> str:
        """Search web."""
        return query

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(search_code, read_file, web_search)),
    )

    graph.invoke(
        {
            "messages": [HumanMessage(content="找到仓库里使用 assemble_context 的位置。")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    assert fake_model.bound_tool_batches == [["search_code", "read_file"]]
    assert fake_model.invocations[0]["allow_tools"] is True
    assert fake_model.invocations[0]["tool_names"] == ["search_code", "read_file"]
    assert any(
        isinstance(message, SystemMessage) and "local workspace inspection tools" in message.content
        for message in fake_model.invocations[0]["messages"]
    )


def test_graph_applies_prompt_budget_guard_before_direct_model_invoke(monkeypatch):
    class FakeRunnable:
        def __init__(self, owner):
            self.owner = owner

        def with_config(self, _config):
            return self

        def invoke(self, prompt_messages):
            self.owner.invocations.append(list(prompt_messages))
            return AIMessage(content="杨絮能传播种子，也能为城市春天提供一种自然观察材料。")

    class FakeModel:
        def __init__(self):
            self.invocations = []
            self.bound_tool_batches = []

        def bind_tools(self, bound_tools):
            self.bound_tool_batches.append([item.name for item in bound_tools])
            return FakeRunnable(self)

        def with_config(self, _config):
            return FakeRunnable(self)

    fake_model = FakeModel()
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    @tool
    def web_search(query: str) -> str:
        """Search web."""
        return query

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(web_search,)),
    )

    current_turn = "帮我写一段关于杨絮好处的短文，直接发给我。"
    result = graph.invoke(
        {
            "messages": [HumanMessage(content=current_turn)],
            "selected_model": "openai:deepseek-reasoner",
            "rolling_summary": "obsolete summary " * 500,
            "user_constraints": [{"constraint": "Keep the current writing request authoritative."}],
            "context_budget": ContextBudget(prompt_token_limit=320, chars_per_token=1),
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    prompt_messages = fake_model.invocations[0]
    rendered = "\n".join(str(message.content) for message in prompt_messages)

    assert result.value["messages"][-1].content.startswith("杨絮")
    assert fake_model.bound_tool_batches == []
    assert sum(len(str(message.content)) for message in prompt_messages) <= 320
    assert current_turn in rendered
    assert "Keep the current writing request authoritative." in rendered
    assert "obsolete summary" not in rendered


def test_empty_tool_free_repair_falls_back_to_tool_results():
    prompt_messages = [
        SystemMessage(content="system"),
        HumanMessage(content="找到 assemble_context"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call-1",
                    "name": "search_code",
                    "args": {"query": "assemble_context"},
                }
            ],
        ),
        ToolMessage(
            content=(
                '{"results":[{"path":"src/focus_agent/core/context_policy.py",'
                '"line_number":42,"line":"def assemble_context(state, mode):"}]}'
            ),
            tool_call_id="call-1",
        ),
    ]

    repaired = _repair_tool_free_answer_response(
        response=AIMessage(content=""),
        prompt_messages=prompt_messages,
        context_budget=ContextBudget(),
        selected_model="openai:fake",
        selected_thinking_mode="",
        model_for=lambda *_args: None,
    )

    assert "context_policy.py:42" in repaired.content


class _SingleRoundToolModel:
    def __init__(self, *, tool_calls, final_answer: str = "done", on_final_invoke=None):
        self.tool_calls = tool_calls
        self.final_answer = final_answer
        self.on_final_invoke = on_final_invoke

    def bind_tools(self, _tools):
        return self

    def with_config(self, _config):
        return self

    def invoke(self, prompt_messages):
        if not any(isinstance(message, ToolMessage) for message in prompt_messages):
            return AIMessage(content="", tool_calls=self.tool_calls)
        if self.on_final_invoke is not None:
            self.on_final_invoke(prompt_messages)
        return AIMessage(content=self.final_answer)


def test_graph_tool_executor_converts_tool_exception_into_error_message(monkeypatch):
    @tool
    def broken_lookup(query: str) -> str:
        """Broken read-only lookup."""
        raise RuntimeError(f"boom:{query}")

    broken_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": False,
    }

    def _assert_error_prompt(prompt_messages):
        tool_messages = [message for message in prompt_messages if isinstance(message, ToolMessage)]
        assert tool_messages
        assert tool_messages[-1].status == "error"
        assert "boom:oops" in tool_messages[-1].content

    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {
                "id": "broken-1",
                "name": "broken_lookup",
                "args": {"query": "oops"},
            }
        ],
        final_answer="handled",
        on_final_invoke=_assert_error_prompt,
    )

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(broken_lookup,)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="please inspect the broken thing")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    messages = result.value["messages"]
    tool_messages = [message for message in messages if isinstance(message, ToolMessage)]

    assert tool_messages[-1].status == "error"
    assert isinstance(messages[-1], AIMessage)
    assert messages[-1].content == "handled"


def test_graph_adds_reasoning_content_before_followup_thinking_invoke(monkeypatch):
    @tool
    def web_search(query: str) -> str:
        """Search the live web."""
        return f"result:{query}"

    web_search.metadata = {
        "parallel_safe": True,
        "cacheable": False,
    }

    def _assert_reasoning_prompt(prompt_messages):
        tool_call_messages = [
            message
            for message in prompt_messages
            if isinstance(message, AIMessage) and getattr(message, "tool_calls", None)
        ]
        assert tool_call_messages
        assert tool_call_messages[-1].additional_kwargs["reasoning_content"]

    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {
                "id": "search-1",
                "name": "web_search",
                "args": {"query": "bitcoin price"},
            }
        ],
        final_answer="price found",
        on_final_invoke=_assert_reasoning_prompt,
    )
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    settings = Settings(
        model="openai:custom-reasoning-pro",
        model_catalog=ModelCatalogConfig(
            models=(
                ConfiguredModel(
                    id="openai:custom-reasoning-pro",
                    supports_thinking=True,
                    default_thinking_enabled=True,
                ),
            ),
        ),
    )
    graph = build_graph(
        settings=settings,
        tool_registry=ToolRegistry(tools=(web_search,)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="帮我查一下比特币实时价格")],
            "selected_model": "openai:custom-reasoning-pro",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    assert result.value["messages"][-1].content == "price found"


def test_graph_forces_search_code_for_workspace_definition_lookup(monkeypatch):
    @tool
    def search_code(query: str) -> str:
        """Search repository code."""
        return (
            '{"results":[{"path":"src/focus_agent/core/state.py",'
            '"line_number":106,"line":"selected_model: str"}]}'
        )

    search_code.metadata = {
        "parallel_safe": True,
        "cacheable": False,
    }

    class _WorkspaceLookupModel:
        def bind_tools(self, _tools):
            return self

        def with_config(self, _config):
            return self

        def invoke(self, prompt_messages):
            assert any(isinstance(message, ToolMessage) for message in prompt_messages)
            return AIMessage(
                content="AgentState.selected_model is defined in src/focus_agent/core/state.py."
            )

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: _WorkspaceLookupModel(),
    )

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(search_code,)),
    )

    result = graph.invoke(
        {
            "messages": [
                HumanMessage(
                    content="只用本地仓库工具，找到仓库里 AgentState 的 selected_model 字段定义位置。"
                )
            ],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    messages = result.value["messages"]
    search_messages = [
        message
        for message in messages
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None)
    ]
    tool_messages = [message for message in messages if isinstance(message, ToolMessage)]

    assert search_messages
    assert search_messages[0].tool_calls[0]["name"] == "search_code"
    assert search_messages[0].tool_calls[0]["args"]["query"] == "AgentState selected_model"
    assert tool_messages
    assert messages[-1].content == "AgentState.selected_model is defined in src/focus_agent/core/state.py."


def test_graph_tool_executor_parallelizes_read_only_tools(monkeypatch):
    @tool
    def slow_lookup(name: str) -> str:
        """Slow read-only lookup."""
        time.sleep(0.2)
        return name

    slow_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": False,
    }

    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {"id": "call-a", "name": "slow_lookup", "args": {"name": "alpha"}},
            {"id": "call-b", "name": "slow_lookup", "args": {"name": "beta"}},
        ],
        final_answer="parallel done",
    )

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(slow_lookup,)),
    )

    started = time.perf_counter()
    result = graph.invoke(
        {
            "messages": [HumanMessage(content="run two lookups")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )
    elapsed = time.perf_counter() - started

    messages = result.value["messages"]
    tool_messages = [message for message in messages if isinstance(message, ToolMessage)]

    assert elapsed < 0.33
    assert [message.tool_call_id for message in tool_messages] == ["call-a", "call-b"]
    assert tool_messages[0].content == "alpha"
    assert tool_messages[1].content == "beta"


def test_graph_tool_executor_reuses_thread_cache_for_cacheable_tools(monkeypatch):
    call_count = 0

    @tool
    def cached_lookup(name: str) -> str:
        """Cacheable read-only lookup."""
        nonlocal call_count
        call_count += 1
        return f"seen:{name}"

    cached_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
    }

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: _SingleRoundToolModel(
            tool_calls=[
                {"id": "cache-1", "name": "cached_lookup", "args": {"name": "focus"}},
            ],
            final_answer="cache done",
        ),
    )

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(cached_lookup,)),
    )

    payload = {
        "messages": [HumanMessage(content="lookup focus")],
        "selected_model": "openai:deepseek-reasoner",
    }
    context = RequestContext(user_id="user-1", root_thread_id="thread-cache")

    graph.invoke(payload, context=context, version="v2")
    graph.invoke(payload, context=context, version="v2")

    assert call_count == 1


def test_graph_tool_executor_does_not_reuse_turn_cache_across_turns(monkeypatch):
    call_count = 0

    @tool
    def turn_scoped_lookup(name: str) -> str:
        """Turn-scoped cacheable lookup."""
        nonlocal call_count
        call_count += 1
        return f"turn:{name}"

    turn_scoped_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "turn",
    }

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: _SingleRoundToolModel(
            tool_calls=[
                {"id": "turn-1", "name": "turn_scoped_lookup", "args": {"name": "focus"}},
            ],
            final_answer="turn done",
        ),
    )

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(turn_scoped_lookup,)),
    )

    context = RequestContext(user_id="user-1", root_thread_id="thread-turn-cache")
    graph.invoke(
        {
            "messages": [HumanMessage(content="lookup focus once")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=context,
        version="v2",
    )
    graph.invoke(
        {
            "messages": [
                HumanMessage(content="lookup focus once"),
                AIMessage(content="turn done"),
                HumanMessage(content="lookup focus again"),
            ],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=context,
        version="v2",
    )

    assert call_count == 2


def test_graph_turn_cache_isolated_between_threads(monkeypatch):
    call_count = 0

    @tool
    def turn_scoped_lookup(name: str) -> str:
        """Turn-scoped cacheable lookup."""
        nonlocal call_count
        call_count += 1
        return f"turn:{name}"

    turn_scoped_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "turn",
    }

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: _SingleRoundToolModel(
            tool_calls=[
                {"id": "turn-1", "name": "turn_scoped_lookup", "args": {"name": "focus"}},
            ],
            final_answer="turn done",
        ),
    )

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(turn_scoped_lookup,)),
    )
    payload = {
        "messages": [HumanMessage(content="lookup focus")],
        "selected_model": "openai:deepseek-reasoner",
    }

    graph.invoke(
        payload,
        context=RequestContext(user_id="user-1", root_thread_id="thread-a"),
        version="v2",
    )
    graph.invoke(
        payload,
        context=RequestContext(user_id="user-1", root_thread_id="thread-b"),
        version="v2",
    )
    graph.invoke(
        payload,
        context=RequestContext(user_id="user-1", root_thread_id="thread-a"),
        version="v2",
    )

    assert call_count == 2


def test_graph_tool_executor_reports_validator_failures_without_crashing(monkeypatch):
    @tool
    def validated_lookup(query: str) -> str:
        """Lookup with runtime validation."""
        return f"validated:{query}"

    def _validator(args):
        if not str(args.get("query") or "").strip():
            raise ValueError("query must not be empty.")

    validated_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": False,
        "validator": _validator,
    }

    def _assert_validator_error(prompt_messages):
        tool_messages = [message for message in prompt_messages if isinstance(message, ToolMessage)]
        assert tool_messages[-1].status == "error"
        assert "query must not be empty" in tool_messages[-1].content

    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {"id": "validator-1", "name": "validated_lookup", "args": {"query": "  "}},
        ],
        final_answer="validator handled",
        on_final_invoke=_assert_validator_error,
    )

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(validated_lookup,)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="lookup with bad args")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    messages = result.value["messages"]
    tool_messages = [message for message in messages if isinstance(message, ToolMessage)]

    assert tool_messages[-1].status == "error"
    assert isinstance(messages[-1], AIMessage)
    assert messages[-1].content == "validator handled"
