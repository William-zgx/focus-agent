import json
import time

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import tool
from langgraph.types import Command

from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.capabilities.tool_router import build_tool_route_plan
from focus_agent.config import ConfiguredModel, ModelCatalogConfig, Settings
from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import ContextBudget
from focus_agent.engine.graph_builder import (
    _classify_turn_tool_policy,
    _canonicalize_tool_call_args,
    _count_tool_call_rounds_since_latest_human,
    _ensure_reasoning_content_for_tool_call_history,
    _fallback_answer_from_tool_results,
    build_tool_intent_plan,
    _live_web_research_should_start_with_search,
    _looks_like_textual_tool_call_artifact,
    _messages_for_model,
    _repair_and_dedupe_tool_calls,
    _repair_tool_free_answer_response,
    _should_force_tool_free_answer,
    _tool_policy_note,
    _tools_for_policy,
    build_graph,
)
from focus_agent.engine.local_persistence import PersistentInMemorySaver
from focus_agent.memory import MemoryExtractor, MemoryRetriever


class _StaticAIResponseRunnable:
    def __init__(self, content: str):
        self.content = content

    def with_config(self, _config):
        return self

    def invoke(self, _prompt_messages):
        return AIMessage(content=self.content)


class _StaticAIResponseModel:
    def __init__(self, content: str = "done"):
        self.content = content

    def bind_tools(self, _tools):
        return _StaticAIResponseRunnable(self.content)

    def with_config(self, _config):
        return _StaticAIResponseRunnable(self.content)


def _patch_static_chat_model(monkeypatch, *, content: str = "done"):
    fake_model = _StaticAIResponseModel(content=content)
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )
    return fake_model


def _invoke_delegation_graph(monkeypatch, settings: Settings, *, model_content: str = "done"):
    _patch_static_chat_model(monkeypatch, content=model_content)
    graph = build_graph(
        settings=settings,
        tool_registry=ToolRegistry(tools=()),
    )

    return graph.invoke(
        {
            "messages": [HumanMessage(content="Implement and verify delegation runtime.")],
            "selected_model": "openai:fake",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )


def test_graph_delegation_observe_mode_leaves_runs_planned(monkeypatch):
    result = _invoke_delegation_graph(
        monkeypatch,
        Settings(
            plan_act_reflect_enabled=False,
            agent_role_routing_enabled=True,
            agent_delegation_enabled=True,
            agent_delegation_enforce=True,
        ),
    )

    delegation = result.value["agent_delegation_plan"]
    records = result.value["governance_records"]
    assert delegation["execution_mode"] == "observe"
    assert all(run["status"] == "planned" for run in delegation["runs"])
    assert delegation["run_results"] == []
    assert any(record["name"] == "agent_delegation_plan" for record in records)


def test_graph_delegation_fake_mode_updates_runs_and_artifacts(monkeypatch):
    result = _invoke_delegation_graph(
        monkeypatch,
        Settings(
            plan_act_reflect_enabled=False,
            agent_role_routing_enabled=True,
            agent_delegation_enabled=True,
            agent_delegation_execution_mode="fake",
            agent_task_ledger_enabled=True,
            agent_artifact_synthesis_enabled=True,
        ),
    )

    delegation = result.value["agent_delegation_plan"]
    artifacts = result.value["delegated_artifacts"]
    synthesis = result.value["artifact_synthesis_result"]
    record_names = [record["name"] for record in result.value["governance_records"]]

    assert delegation["execution_mode"] == "fake"
    assert any(run["status"] == "completed" for run in delegation["runs"])
    assert any("fake delegated result" in artifact["title"] for artifact in artifacts)
    assert synthesis["accepted_artifact_ids"]
    assert "agent_task_ledger" in record_names
    assert "delegated_artifacts" in record_names


def test_graph_delegation_inline_mode_merges_completed_runs_and_artifacts(monkeypatch):
    result = _invoke_delegation_graph(
        monkeypatch,
        Settings(
            plan_act_reflect_enabled=False,
            agent_role_routing_enabled=True,
            agent_delegation_enabled=True,
            agent_delegation_execution_mode="inline",
            agent_task_ledger_enabled=True,
            agent_artifact_synthesis_enabled=True,
        ),
        model_content="inline graph delegated result",
    )

    delegation = result.value["agent_delegation_plan"]
    artifacts = result.value["delegated_artifacts"]

    assert delegation["execution_mode"] == "inline"
    assert delegation["run_results"]
    assert any(run["status"] == "completed" for run in delegation["runs"])
    assert not any(run["status"] == "skipped" for run in delegation["runs"])
    assert not any("not implemented" in str(run.get("error", "")).lower() for run in delegation["runs"])
    assert any("inline graph delegated result" in artifact["summary"] for artifact in artifacts)


def test_graph_delegation_background_mode_merges_completed_runs_and_artifacts(monkeypatch):
    result = _invoke_delegation_graph(
        monkeypatch,
        Settings(
            plan_act_reflect_enabled=False,
            agent_role_routing_enabled=True,
            agent_delegation_enabled=True,
            agent_delegation_execution_mode="background",
            agent_role_max_parallel_runs=2,
            agent_task_ledger_enabled=True,
            agent_artifact_synthesis_enabled=True,
        ),
        model_content="background graph delegated result",
    )

    delegation = result.value["agent_delegation_plan"]
    artifacts = result.value["delegated_artifacts"]

    assert delegation["execution_mode"] == "background"
    assert delegation["run_results"]
    assert any(run["status"] == "completed" for run in delegation["runs"])
    assert not any(run["status"] == "skipped" for run in delegation["runs"])
    assert not any("not implemented" in str(run.get("error", "")).lower() for run in delegation["runs"])
    assert any("background graph delegated result" in artifact["summary"] for artifact in artifacts)


def test_tool_call_repair_canonicalizes_args_and_dedupes_identical_calls():
    assert _canonicalize_tool_call_args('{"query":"focus"}') == {"query": "focus"}
    assert _canonicalize_tool_call_args("not-json") == {"_raw_args": "not-json"}

    message = AIMessage(
        content="",
        tool_calls=[
            {"id": "call-a", "name": "search_code", "args": {"query": "focus"}},
            {"id": "call-b", "name": "search_code", "args": {"query": "focus"}},
            {"id": "call-c", "name": "read_file", "args": {"path": "src/app.py"}},
        ],
    )

    repaired = _repair_and_dedupe_tool_calls(message)

    assert isinstance(repaired, AIMessage)
    assert [call["id"] for call in repaired.tool_calls] == ["call-a", "call-c"]
    assert [call["name"] for call in repaired.tool_calls] == ["search_code", "read_file"]


def test_execution_policy_note_guards_branch_action_claims():
    note = _tool_policy_note("execution")

    assert "Branch Action" in note
    assert "do not claim" in note


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


def test_live_web_search_first_guard_uses_full_tool_history():
    @tool
    def web_search(query: str) -> str:
        """Search the live web."""
        return query

    latest_user = "我想仔细了解一下电力板块，选几只龙头股分析"
    stripped_recent_messages = [HumanMessage(content=latest_user)]
    full_turn_messages = [
        HumanMessage(content=latest_user),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "search-1",
                    "name": "web_search",
                    "args": {"query": latest_user},
                }
            ],
        ),
        ToolMessage(content='{"answer":"已有搜索结果"}', tool_call_id="search-1"),
    ]

    assert _live_web_research_should_start_with_search(
        latest_user,
        stripped_recent_messages,
        [web_search],
    )
    assert not _live_web_research_should_start_with_search(
        latest_user,
        full_turn_messages,
        [web_search],
    )


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
            self.configs = []

        def with_config(self, config):
            self.configs.append(config)
            return self

        def invoke(self, prompt_messages):
            self.owner.invocations.append(
                {
                    "allow_tools": self.allow_tools,
                    "messages": list(prompt_messages),
                    "configs": list(self.configs),
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
    assert all(
        any(
            config.get("metadata", {}).get("stream_phase") == "quarantine"
            for config in item["configs"]
        )
        for item in tool_enabled_calls
    )
    assert any(
        isinstance(message, SystemMessage) and "emit a real tool call" in message.content
        for message in tool_enabled_calls[1]["messages"]
    )


def test_detects_textual_tool_call_artifacts():
    assert _looks_like_textual_tool_call_artifact(
        AIMessage(content="<｜DSML｜function_calls><｜DSML｜invoke name=\"web_search\"></｜DSML｜invoke>")
    )
    assert _looks_like_textual_tool_call_artifact(
        AIMessage(
            content=(
                "让我进一步获取几个关键来源的详细内容，以便给出更有深度的回答。\n\n"
                "< | | DSML | | tool_calls>\n"
                "< | | DSML | | invoke nameweb_search\">\n"
                "< | | DSML | | parameter name=\"query\" string=\"true\">AI breakthroughs</ | | DSML | | parameter>"
            )
        )
    )
    assert _looks_like_textual_tool_call_artifact(
        AIMessage(
            content=(
                'toolcalls/invoke namewebfetch">\n'
                'parameter namemax_chars" string="false">8000</ | | DSML | | parameter>\n'
                'parameter nameurl" string="true">https://example.com</ | | DSML | | parameter>'
            )
        )
    )
    assert _looks_like_textual_tool_call_artifact(
        AIMessage(
            content=(
                'invoke name">\n'
                'parameter name="" string="true">direct</ | | DSML | | parameter>\n'
                'parameter name="" string="true">https://mem0.ai/blog/state-of-ai-agent-memory-2026'
                "</ | | DSML | | parameter>"
            )
        )
    )
    assert _looks_like_textual_tool_call_artifact(AIMessage(content="</tool_call>"))
    assert _looks_like_textual_tool_call_artifact(
        AIMessage(content="[web_fetch] 尝试获取沪指本周逐日行情数据，请稍等。")
    )
    assert _looks_like_textual_tool_call_artifact(
        AIMessage(content="[custom_lookup] lookup next"),
        known_tool_names={"custom_lookup"},
    )
    assert _looks_like_textual_tool_call_artifact(
        AIMessage(content="让我尝试获取更详细的日线数据：\n\n我已经从搜索结果中获取到了关键信息。")
    )
    assert _looks_like_textual_tool_call_artifact(
        AIMessage(
            content=(
                "我来帮你查询华钰矿业（601020）近一周的行情数据。"
                "先获取详细的历史交易数据。让我查询东方财富网的具体行情页面。"
                "如果没有新指示，我将默认继续执行。请确认是否继续。"
            )
        )
    )
    assert not _looks_like_textual_tool_call_artifact(AIMessage(content="[背景] 北京今天晴。"))
    assert not _looks_like_textual_tool_call_artifact(AIMessage(content="北京今天晴，最高气温25℃。"))
    assert not _looks_like_textual_tool_call_artifact(AIMessage(content="我尝试过几种投资方法，最终更偏向长期持有。"))
    assert not _looks_like_textual_tool_call_artifact(AIMessage(content="我来帮你分析这份报告：结论是现金流改善。"))


def test_turn_tool_policy_classifies_direct_workspace_and_web_requests():
    assert _classify_turn_tool_policy("帮我写一篇300字左右描述小猫可爱的作文。直接发给我。") == "direct_answer"
    assert _classify_turn_tool_policy("帮我写一段说明通用 Agent 工具调用优化的价值，直接回复。") == "direct_answer"
    assert _classify_turn_tool_policy("不要联网。简单解释 LangGraph 的 checkpointer 是什么。") == "direct_answer"
    assert _classify_turn_tool_policy("找到仓库里使用 assemble_context 的位置。") == "workspace_lookup"
    assert _classify_turn_tool_policy("北京和上海哪个今天天气好？") == "live_web_research"
    assert (
        _classify_turn_tool_policy(
            "我想仔细了解一下电力板块。你能选几只电力板块的龙头股给我分析一下吗？"
        )
        == "live_web_research"
    )
    assert (
        _classify_turn_tool_policy("比亚迪近一年最大涨跌幅是多少？请给出数据来源和计算口径。")
        == "live_web_research"
    )
    assert (
        _classify_turn_tool_policy("请重新实际检索：比亚迪近一年最大单日涨幅和最大单日跌幅分别是多少？请引用来源并说明口径。")
        == "live_web_research"
    )
    assert (
        _classify_turn_tool_policy(
            '帮我找到 "Memory in the Age of AI Agents" 这篇论文的下载链接（arXiv 最好），并告诉我如何获取 PDF'
        )
        == "live_web_research"
    )
    assert _classify_turn_tool_policy("帮我下载 Memory in the Age of AI Agents 这篇论文") == "live_web_research"
    assert _classify_turn_tool_policy("Find the PDF for Memory in the Age of AI Agents") == "live_web_research"
    assert _classify_turn_tool_policy("帮我看一下最近哪些AI项目比较火？都是做什么的?") == "live_web_research"
    assert _classify_turn_tool_policy("当前项目里 web_search 工具在哪里？") == "workspace_lookup"
    assert _classify_turn_tool_policy("当前项目里下载 README 文件") == "workspace_lookup"
    assert _classify_turn_tool_policy("download the README file from the current repo") == "workspace_lookup"
    assert _classify_turn_tool_policy("当前项目里 DOI parser 在哪里？") == "workspace_lookup"
    assert _classify_turn_tool_policy("复现场景，做一下测试。") == "execution"


def test_tool_intent_plan_applies_skill_defaults_and_no_tool_precedence():
    research = build_tool_intent_plan(
        '帮我找到 "Memory in the Age of AI Agents" 这篇论文的下载链接',
        active_skill_ids=["research"],
    )
    plan = build_tool_intent_plan("查一下最近 AI 工具，但不要联网", active_skill_ids=["research"])
    review = build_tool_intent_plan("看看这个实现是否安全", active_skill_ids=["review"])

    assert research.policy == "live_web_research"
    assert research.preferred_first_tool == "web_search"
    assert research.preferred_first_args["query"].startswith("帮我找到")
    assert research.source == "skill:research"
    assert plan.policy == "direct_answer"
    assert "explicit_no_tool" in plan.reason_codes
    assert review.policy == "workspace_lookup"
    assert review.source == "skill:review"


def test_tool_intent_plan_recovers_pending_web_search_from_confirmation():
    plan = build_tool_intent_plan(
        "允许",
        pending_tool_action={
            "policy": "live_web_research",
            "preferred_first_tool": "web_search",
            "preferred_first_args": {"query": "帮我查一下今天北京天气"},
        },
    )
    no_pending = build_tool_intent_plan("允许")

    assert plan.policy == "live_web_research"
    assert plan.preferred_first_tool == "web_search"
    assert plan.preferred_first_args == {"query": "帮我查一下今天北京天气"}
    assert plan.source == "pending_tool_action"
    assert "pending_tool_action_carryover" in plan.reason_codes
    assert "temporal_anchor_required" in plan.reason_codes
    assert no_pending.policy == "direct_answer"


def test_tool_intent_plan_recovers_pending_web_search_from_phrase_confirmation():
    plan = build_tool_intent_plan(
        "好的，帮我查吧。",
        pending_tool_action={
            "policy": "live_web_research",
            "tool": "web_search",
            "query": "今天有哪个国家总统访问中国？",
            "created_turn_index": 1,
            "expires_after_turns": 2,
        },
    )

    assert plan.policy == "live_web_research"
    assert plan.preferred_first_tool == "web_search"
    assert plan.preferred_first_args == {"query": "今天有哪个国家总统访问中国？"}
    assert plan.temporal_anchor_required is True


def test_tool_intent_plan_marks_temporal_anchor_requirement_for_live_web():
    plan = build_tool_intent_plan("帮我查一下 today AI news")

    assert plan.policy == "live_web_research"
    assert plan.preferred_first_tool == "web_search"
    assert "temporal_anchor_required" in plan.reason_codes
    assert plan.temporal_anchor_required is True


def test_live_web_research_starts_stock_queries_with_web_search():
    @tool
    def web_search(query: str) -> str:
        """Search web."""
        return query

    @tool
    def current_utc_time() -> str:
        """Current time."""
        return "now"

    assert _live_web_research_should_start_with_search(
        "帮我查一下这个周沪指的波动情况。",
        [HumanMessage(content="帮我查一下这个周沪指的波动情况。")],
        [web_search, current_utc_time],
    )
    assert _live_web_research_should_start_with_search(
        "我想仔细了解一下电力板块。你能选几只电力板块的龙头股给我分析一下吗？",
        [HumanMessage(content="我想仔细了解一下电力板块。你能选几只电力板块的龙头股给我分析一下吗？")],
        [web_search, current_utc_time],
    )
    assert _live_web_research_should_start_with_search(
        "比亚迪近一年最大涨跌幅是多少？请给出数据来源和计算口径。",
        [HumanMessage(content="比亚迪近一年最大涨跌幅是多少？请给出数据来源和计算口径。")],
        [web_search, current_utc_time],
    )
    assert _live_web_research_should_start_with_search(
        "请重新实际检索：比亚迪近一年最大单日涨幅和最大单日跌幅分别是多少？请引用来源并说明口径。",
        [HumanMessage(content="请重新实际检索：比亚迪近一年最大单日涨幅和最大单日跌幅分别是多少？请引用来源并说明口径。")],
        [web_search, current_utc_time],
    )
    assert _live_web_research_should_start_with_search(
        "帮我看一下最近哪些AI项目比较火？都是做什么的?",
        [HumanMessage(content="帮我看一下最近哪些AI项目比较火？都是做什么的?")],
        [web_search, current_utc_time],
    )
    assert not _live_web_research_should_start_with_search(
        "现在几点？",
        [HumanMessage(content="现在几点？")],
        [web_search, current_utc_time],
    )
    assert not _live_web_research_should_start_with_search(
        "帮我查一下这个周沪指的波动情况。",
        [
            HumanMessage(content="帮我查一下这个周沪指的波动情况。"),
            ToolMessage(content='{"answer":"done"}', tool_call_id="call-1"),
        ],
        [web_search, current_utc_time],
    )
    assert _live_web_research_should_start_with_search(
        "帮我查一下今天北京天气",
        [
            HumanMessage(content="帮我查一下今天北京天气"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "time-1",
                        "name": "current_utc_time",
                        "args": {},
                    }
                ],
            ),
            ToolMessage(content="2026-05-14T00:00:00Z", tool_call_id="time-1"),
        ],
        [web_search, current_utc_time],
    )


def _first_tool_call(messages):
    tool_call_messages = [
        message
        for message in messages
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None)
    ]
    assert tool_call_messages
    return tool_call_messages[0].tool_calls[0]


def test_graph_routes_external_ai_trend_queries_to_web_search_first(monkeypatch):
    prompts = [
        "帮我看一下最近哪些AI项目比较火？都是做什么的?",
        "What are the latest popular AI tools for coding?",
    ]

    def make_web_search(calls):
        @tool
        def web_search(query: str) -> str:
            """Search the live web."""
            calls.append(query)
            return '{"answer":"local web-search fixture"}'

        return web_search

    for prompt in prompts:
        web_calls = []

        class FakeRunnable:
            def with_config(self, _config):
                return self

            def invoke(self, _prompt_messages):
                return AIMessage(content="trend summary")

        class FakeModel:
            def bind_tools(self, _tools):
                return FakeRunnable()

            def with_config(self, _config):
                return FakeRunnable()

        monkeypatch.setattr(
            "focus_agent.engine.graph_builder.create_chat_model",
            lambda *args, **kwargs: FakeModel(),
        )

        web_search = make_web_search(web_calls)

        graph = build_graph(
            settings=Settings(
                agent_tool_router_enabled=True,
                agent_tool_router_enforce=True,
            ),
            tool_registry=ToolRegistry(tools=(web_search,)),
        )

        result = graph.invoke(
            {
                "messages": [HumanMessage(content=prompt)],
                "selected_model": "openai:fake",
            },
            context=RequestContext(
                user_id="user-1",
                root_thread_id=f"route-web-{len(web_calls)}",
            ),
            version="v2",
        )

        first_call = _first_tool_call(result.value["messages"])
        assert first_call["name"] == "web_search"
        assert first_call["args"] == {"query": prompt}
        assert web_calls == [prompt]


def test_graph_forces_current_time_before_temporal_web_search(monkeypatch):
    calls = []

    @tool
    def current_utc_time() -> str:
        """Return current UTC time."""
        calls.append("current_utc_time")
        return "2026-05-14T00:00:00Z"

    @tool
    def web_search(query: str) -> str:
        """Search the live web."""
        calls.append(f"web_search:{query}")
        return '{"answer":"sunny"}'

    class FakeRunnable:
        def with_config(self, _config):
            return self

        def invoke(self, _prompt_messages):
            return AIMessage(content="今天北京天气晴朗。")

    class FakeModel:
        def bind_tools(self, _tools):
            return FakeRunnable()

        def with_config(self, _config):
            return FakeRunnable()

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: FakeModel(),
    )

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(current_utc_time, web_search)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="帮我查一下今天北京天气")],
            "selected_model": "openai:fake",
        },
        context=RequestContext(user_id="user-1", root_thread_id="route-temporal-anchor"),
        version="v2",
    )

    tool_calls = [
        call
        for message in result.value["messages"]
        if isinstance(message, AIMessage)
        for call in (getattr(message, "tool_calls", None) or [])
    ]
    assert [call["name"] for call in tool_calls[:2]] == ["current_utc_time", "web_search"]
    assert tool_calls[1]["args"] == {"query": "帮我查一下今天北京天气"}
    assert calls == [
        "current_utc_time",
        "web_search:帮我查一下今天北京天气",
    ]
    assert result.value["tool_intent_plan"]["temporal_anchor_required"] is True
    assert result.value["plan_meta"]["tool_intent_plan"]["temporal_anchor_required"] is True


def test_graph_recovers_pending_web_search_from_confirmation(monkeypatch):
    web_calls = []

    @tool
    def web_search(query: str) -> str:
        """Search the live web."""
        web_calls.append(query)
        return '{"answer":"allowed"}'

    class FakeRunnable:
        def with_config(self, _config):
            return self

        def invoke(self, _prompt_messages):
            return AIMessage(content="查询完成。")

    class FakeModel:
        def bind_tools(self, _tools):
            return FakeRunnable()

        def with_config(self, _config):
            return FakeRunnable()

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: FakeModel(),
    )

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(web_search,)),
    )

    result = graph.invoke(
        {
            "messages": [
                HumanMessage(content="帮我查一下最近 AI 项目"),
                AIMessage(content="需要联网查询，是否允许？"),
                HumanMessage(content="可以"),
            ],
            "selected_model": "openai:fake",
        },
        context=RequestContext(user_id="user-1", root_thread_id="route-carryover"),
        version="v2",
    )

    first_call = _first_tool_call(result.value["messages"])
    assert first_call["name"] == "web_search"
    assert first_call["args"] == {"query": "帮我查一下最近 AI 项目"}
    assert web_calls == ["帮我查一下最近 AI 项目"]
    assert result.value["tool_intent_plan"]["source"] == "pending_tool_action"
    assert "pending_tool_action_carryover" in result.value["tool_intent_plan"]["reason_codes"]


def test_graph_writes_evidence_bundle_and_citations_after_web_result(monkeypatch):
    @tool
    def web_search(query: str) -> str:
        """Search the live web."""
        return json.dumps(
            {
                "query": query,
                "provider": "test",
                "results": [
                    {
                        "title": "Foreign Ministry Spokesperson",
                        "url": "https://www.mfa.gov.cn/eng/example",
                        "content": "Official visit details from the Ministry of Foreign Affairs.",
                    }
                ],
            }
        )

    class FakeRunnable:
        def with_config(self, _config):
            return self

        def invoke(self, _prompt_messages):
            return AIMessage(content="根据外交部消息，访问安排已公布。")

    class FakeModel:
        def bind_tools(self, _tools):
            return FakeRunnable()

        def with_config(self, _config):
            return FakeRunnable()

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: FakeModel(),
    )

    graph = build_graph(settings=Settings(), tool_registry=ToolRegistry(tools=(web_search,)))

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="最近有哪个国家总统访问中国？")],
            "selected_model": "openai:fake",
        },
        context=RequestContext(user_id="user-1", root_thread_id="route-evidence"),
        version="v2",
    )

    assert result.value["evidence_bundle"][0]["trust_tier"] == "high"
    assert result.value["citations"][0]["label"] == "Foreign Ministry Spokesperson"
    assert result.value["citations"][0]["uri"] == "https://www.mfa.gov.cn/eng/example"
    assert not result.value["tool_intent_plan"].get("external_answer_missing_citation")


def test_graph_routes_research_prefixed_academic_download_to_web_search_first(monkeypatch):
    raw_prompt = (
        'research: 帮我找到 "Memory in the Age of AI Agents" 这篇论文的下载链接'
        "（arXiv 最好），并告诉我如何获取 PDF"
    )
    stripped_prompt = raw_prompt.removeprefix("research:").strip()
    web_calls = []

    @tool
    def web_search(query: str) -> str:
        """Search the live web."""
        web_calls.append(query)
        return '{"answer":"local arxiv fixture"}'

    class FakeRunnable:
        def with_config(self, _config):
            return self

        def invoke(self, _prompt_messages):
            return AIMessage(content="arXiv download summary")

    class FakeModel:
        def bind_tools(self, _tools):
            return FakeRunnable()

        def with_config(self, _config):
            return FakeRunnable()

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: FakeModel(),
    )

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(web_search,)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content=raw_prompt)],
            "task_brief": stripped_prompt,
            "active_skill_ids": ["research"],
            "selected_model": "openai:fake",
        },
        context=RequestContext(
            user_id="user-1",
            root_thread_id="route-research-academic-download",
        ),
        version="v2",
    )

    first_call = _first_tool_call(result.value["messages"])
    assert first_call["name"] == "web_search"
    assert first_call["args"] == {"query": stripped_prompt}
    assert web_calls == [stripped_prompt]
    assert result.value["tool_intent_plan"]["policy"] == "live_web_research"
    assert result.value["tool_intent_plan"]["source"] == "skill:research"
    assert result.value["plan_meta"]["tool_intent_plan"]["preferred_first_tool"] == "web_search"


def test_graph_routes_project_web_search_location_to_search_code_without_web_exposure(monkeypatch):
    captured = {"bound_tools": []}
    web_calls = 0

    class FakeRunnable:
        def with_config(self, _config):
            return self

        def invoke(self, _prompt_messages):
            return AIMessage(content="web_search is defined in the workspace tools.")

    class FakeModel:
        def bind_tools(self, bound_tools):
            captured["bound_tools"].append([tool.name for tool in bound_tools])
            return FakeRunnable()

        def with_config(self, _config):
            return FakeRunnable()

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: FakeModel(),
    )

    @tool
    def search_code(query: str) -> str:
        """Search repository code."""
        return (
            '{"results":[{"path":"src/focus_agent/capabilities/default_tool_modules/web.py",'
            '"line_number":12,"line":"def web_search(query: str) -> str:"}]}'
        )

    @tool
    def read_file(path: str) -> str:
        """Read a workspace file."""
        return path

    @tool
    def web_search(query: str) -> str:
        """Search the live web."""
        nonlocal web_calls
        web_calls += 1
        return query

    graph = build_graph(
        settings=Settings(
            agent_tool_router_enabled=True,
            agent_tool_router_enforce=True,
        ),
        tool_registry=ToolRegistry(tools=(search_code, read_file, web_search)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="当前项目里 web_search 工具在哪里？")],
            "selected_model": "openai:fake",
        },
        context=RequestContext(user_id="user-1", root_thread_id="route-workspace"),
        version="v2",
    )

    first_call = _first_tool_call(result.value["messages"])
    assert first_call["name"] == "search_code"
    assert first_call["args"] == {"query": "web_search"}
    assert captured["bound_tools"] == [["search_code", "read_file"]]
    assert web_calls == 0


def test_graph_respects_no_network_recent_ai_tools_request_without_tool_call(monkeypatch):
    captured = {"bound_tools": []}
    web_calls = 0

    class FakeRunnable:
        def with_config(self, _config):
            return self

        def invoke(self, _prompt_messages):
            return AIMessage(content="不联网也可以概括常见 AI 工具类别。")

    class FakeModel:
        def bind_tools(self, bound_tools):
            captured["bound_tools"].append([tool.name for tool in bound_tools])
            return FakeRunnable()

        def with_config(self, _config):
            return FakeRunnable()

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: FakeModel(),
    )

    @tool
    def web_search(query: str) -> str:
        """Search the live web."""
        nonlocal web_calls
        web_calls += 1
        return query

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(web_search,)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="不要联网。最近哪些 AI 工具比较火？")],
            "selected_model": "openai:fake",
        },
        context=RequestContext(user_id="user-1", root_thread_id="route-no-web"),
        version="v2",
    )

    tool_call_messages = [
        message
        for message in result.value["messages"]
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None)
    ]
    assert tool_call_messages == []
    assert captured["bound_tools"] == []
    assert web_calls == 0


def test_graph_exposes_mixed_readonly_web_and_workspace_tools_without_write_tools(monkeypatch):
    captured = {"bound_tools": []}

    class FakeRunnable:
        def with_config(self, _config):
            return self

        def invoke(self, _prompt_messages):
            return AIMessage(content="comparison ready")

    class FakeModel:
        def bind_tools(self, bound_tools):
            captured["bound_tools"].append([tool.name for tool in bound_tools])
            return FakeRunnable()

        def with_config(self, _config):
            return FakeRunnable()

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: FakeModel(),
    )

    @tool
    def search_code(query: str) -> str:
        """Search repository code."""
        return query

    @tool
    def read_file(path: str) -> str:
        """Read a workspace file."""
        return path

    @tool
    def web_search(query: str) -> str:
        """Search the live web."""
        return query

    @tool
    def web_fetch(url: str) -> str:
        """Fetch a web page."""
        return url

    @tool
    def current_utc_time() -> str:
        """Return current UTC time."""
        return "2026-01-01T00:00:00Z"

    @tool
    def write_text_artifact(title: str, content: str) -> str:
        """Write an artifact."""
        return f"{title}:{content}"

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(
            tools=(
                search_code,
                read_file,
                web_search,
                web_fetch,
                current_utc_time,
                write_text_artifact,
            )
        ),
    )

    graph.invoke(
        {
            "messages": [HumanMessage(content="对比仓库里的 web_search 实现和最新 Tavily API 文档")],
            "selected_model": "openai:fake",
        },
        context=RequestContext(user_id="user-1", root_thread_id="route-mixed-readonly"),
        version="v2",
    )

    assert captured["bound_tools"]
    exposed = set(captured["bound_tools"][0])
    assert {
        "search_code",
        "read_file",
        "web_search",
        "web_fetch",
        "current_utc_time",
    } <= exposed
    assert "write_text_artifact" not in exposed


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

    @tool
    def approval_lookup(name: str) -> str:
        """Lookup that requires approval."""
        return name

    approval_lookup.metadata = {
        "requires_approval": True,
        "risk_level": "high",
        "intent_policies": ("execution",),
        "allowed_roles": ("executor",),
    }

    tools = [list_files, search_code, read_file, web_search, write_text_artifact, approval_lookup]

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
        "write_text_artifact",
        "approval_lookup",
    ]
    route_plan = build_tool_route_plan(
        tool_registry=ToolRegistry(tools=tuple(tools)),
        role="executor",
        tool_policy="execution",
        available_tool_names=[tool.name for tool in tools],
    )
    assert route_plan.allowed_tools == [
        item.name for item in _tools_for_policy("execution", tools, role="executor")
    ]
    approval_decision = next(item for item in route_plan.decisions if item.name == "approval_lookup")
    assert approval_decision.allowed is True
    assert approval_decision.reason == "approval_required"


def test_graph_does_not_bind_tools_for_direct_answer_turn(monkeypatch):
    class FakeRunnable:
        def __init__(self, owner, *, allow_tools: bool, tool_names: list[str] | None = None):
            self.owner = owner
            self.allow_tools = allow_tools
            self.tool_names = tool_names or []
            self.configs = []

        def with_config(self, config):
            self.configs.append(config)
            return self

        def invoke(self, prompt_messages):
            self.owner.invocations.append(
                {
                    "allow_tools": self.allow_tools,
                    "tool_names": self.tool_names,
                    "messages": list(prompt_messages),
                    "configs": list(self.configs),
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
        config.get("metadata", {}).get("stream_phase") == "visible"
        for config in fake_model.invocations[0]["configs"]
    )
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
            self.configs = []

        def with_config(self, config):
            self.configs.append(config)
            return self

        def invoke(self, prompt_messages):
            self.owner.invocations.append(
                {
                    "allow_tools": self.allow_tools,
                    "tool_names": self.tool_names,
                    "messages": list(prompt_messages),
                    "configs": list(self.configs),
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
        config.get("metadata", {}).get("stream_phase") == "quarantine"
        for config in fake_model.invocations[0]["configs"]
    )
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


def test_empty_tool_free_repair_synthesizes_plain_answer_before_raw_fallback():
    class SynthesizingModel:
        def invoke(self, prompt_messages):
            assert not any(isinstance(message, ToolMessage) for message in prompt_messages)
            assert "工具结果" in prompt_messages[-1].content
            return AIMessage(content="根据工具结果，assemble_context 位于 context_policy.py 第 42 行。")

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
        model_for=lambda *_args: SynthesizingModel(),
    )

    assert repaired.content == "根据工具结果，assemble_context 位于 context_policy.py 第 42 行。"


def test_fallback_answer_from_tool_results_summarizes_web_search_payload():
    answer = _fallback_answer_from_tool_results(
        [
            HumanMessage(content="帮我查一下上个周比亚迪在A股股价的波动情况。"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "web_search",
                        "args": {"query": "比亚迪 A股 上周 股价 波动"},
                    }
                ],
            ),
            ToolMessage(
                content=(
                    '{"answer":"比亚迪A股上周先涨后跌，波动扩大。",'
                    '"results":[{"title":"BYD share price","url":"https://example.com/byd",'
                    '"content":"上周区间振幅约 6%。"}]}'
                ),
                tool_call_id="call-1",
            )
        ]
    )

    assert "工具 web_search(query=比亚迪 A股 上周 股价 波动)" in answer
    assert "比亚迪A股上周先涨后跌" in answer
    assert "BYD share price" in answer


def test_fallback_answer_from_tool_results_uses_latest_turn_and_compacted_refs():
    answer = _fallback_answer_from_tool_results(
        [
            ToolMessage(
                content='{"answer":"旧一轮比特币结果","results":[{"title":"BTC"}]}',
                tool_call_id="old-call",
            ),
            HumanMessage(content="帮我查一下上个周比亚迪在A股股价的波动情况。"),
            ToolMessage(
                content=(
                    '{"query":"比亚迪 002594 股价 2026年4月20日 4月24日 周行情",'
                    '"summary":"web_search output was compressed into an artifact-like prompt reference.",'
                    '"reference":"refs=https://xueqiu.com/S/SZ002594",'
                    '"results":[{"ref":"https://xueqiu.com/S/SZ002594"}],'
                    '"refs":["https://quote.eastmoney.com/sz002594.html"]}'
                ),
                tool_call_id="new-call",
            ),
        ]
    )

    assert "比亚迪 002594" in answer
    assert "https://xueqiu.com/S/SZ002594" in answer
    assert "https://quote.eastmoney.com/sz002594.html" in answer
    assert "旧一轮比特币结果" not in answer


def test_graph_falls_back_to_web_tool_results_when_final_answer_model_fails(monkeypatch):
    class FakeRunnable:
        def __init__(self, owner):
            self.owner = owner

        def with_config(self, _config):
            return self

        def invoke(self, prompt_messages):
            self.owner.invocations.append(list(prompt_messages))
            if not any(isinstance(message, ToolMessage) for message in prompt_messages):
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "web_search",
                            "args": {"query": "比亚迪 A股 上周 股价 波动"},
                        }
                    ],
                )
            raise RuntimeError("final answer model failed")

    class FakeModel:
        def __init__(self):
            self.invocations = []

        def bind_tools(self, _tools):
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
        return (
            '{"answer":"比亚迪A股上周先涨后跌，波动扩大。",'
            '"results":[{"title":"BYD share price","url":"https://example.com/byd",'
            '"content":"上周区间振幅约 6%。"}]}'
        )

    graph = build_graph(settings=Settings(), tool_registry=ToolRegistry(tools=(web_search,)))

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="帮我查一下上个周比亚迪在A股股价的波动情况。")],
            "selected_model": "openai:fake",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    final_answer = result.value["messages"][-1].content
    assert "格式化失败" not in final_answer
    assert "保守整理" in final_answer
    assert "比亚迪A股上周先涨后跌" in final_answer
    assert "BYD share price" in final_answer


def test_graph_repairs_kimi_bracket_tool_marker_after_tool_results(monkeypatch):
    class FakeRunnable:
        def __init__(self, owner, *, allow_tools: bool):
            self.owner = owner
            self.allow_tools = allow_tools

        def with_config(self, _config):
            return self

        def invoke(self, prompt_messages):
            self.owner.invocations.append({"allow_tools": self.allow_tools, "messages": list(prompt_messages)})
            if not any(isinstance(message, ToolMessage) for message in prompt_messages):
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "web_search",
                            "args": {"query": "沪指 本周 波动"},
                        }
                    ],
                )
            tool_enabled_calls = [
                item
                for item in self.owner.invocations
                if item["allow_tools"] and any(isinstance(message, ToolMessage) for message in item["messages"])
            ]
            if self.allow_tools and len(tool_enabled_calls) == 1:
                return AIMessage(content="[web_fetch] 尝试获取沪指（000001）本周逐日行情数据，请稍等。")
            return AIMessage(content="沪指本周先震荡后回稳，已根据搜索结果整理。")

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
        """Search web."""
        return '{"answer":"沪指本周区间震荡，成交活跃。"}'

    graph = build_graph(settings=Settings(), tool_registry=ToolRegistry(tools=(web_search,)))

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="帮我查一下这个周沪指的波动情况。")],
            "selected_model": "moonshot:kimi-k2.6",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    final_answer = result.value["messages"][-1].content
    assert "[web_fetch]" not in final_answer
    assert "沪指本周先震荡后回稳" in final_answer
    assert result.value["plan_meta"]["tool_protocol_repair_count"] == 1
    assert result.value["plan_meta"]["tool_protocol_repair_reason"] == "textual_tool_marker"


def test_graph_repairs_internal_search_narration_after_tool_results(monkeypatch):
    class FakeRunnable:
        def __init__(self, owner, *, allow_tools: bool):
            self.owner = owner
            self.allow_tools = allow_tools

        def with_config(self, _config):
            return self

        def invoke(self, prompt_messages):
            self.owner.invocations.append({"allow_tools": self.allow_tools, "messages": list(prompt_messages)})
            has_tool_result = any(isinstance(message, ToolMessage) for message in prompt_messages)
            has_repair_note = any(
                isinstance(message, SystemMessage) and "internal process narration" in message.content
                for message in prompt_messages
            )
            if has_tool_result and not has_repair_note:
                return AIMessage(
                    content=(
                        "我来帮你查询华钰矿业（601020）近一周的行情数据。"
                        "先获取详细的历史交易数据。让我查询东方财富网的具体行情页面。"
                        "如果没有新指示，我将默认继续执行。请确认是否继续。"
                    )
                )
            return AIMessage(content="华钰矿业近一周上涨明显；逐日收盘价仍需以交易所或行情源校验。")

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
        """Search web."""
        return '{"answer":"4月22日华钰矿业报33.89元，近5日上涨17.48%。"}'

    graph = build_graph(settings=Settings(), tool_registry=ToolRegistry(tools=(web_search,)))

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="帮我查一下A股华钰矿业近一周的股价波动，并且对其进行分析。")],
            "selected_model": "moonshot:kimi-k2.6",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    final_answer = result.value["messages"][-1].content
    assert "我来帮你查询" not in final_answer
    assert "请确认是否继续" not in final_answer
    assert "华钰矿业近一周上涨明显" in final_answer
    assert result.value["plan_meta"]["tool_protocol_repair_count"] == 1
    assert result.value["plan_meta"]["tool_protocol_repair_reason"] == "textual_tool_marker"


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


class _RecordingMemoryStore:
    def __init__(self):
        self.put_calls = []
        self.search_calls = []
        self.delete_calls = []
        self.data = {}

    def put(self, namespace, key, value):
        self.put_calls.append((tuple(namespace), key, dict(value)))
        self.data.setdefault(tuple(namespace), {})[key] = dict(value)

    def get(self, namespace, key):
        return self.data.get(tuple(namespace), {}).get(key)

    def delete(self, namespace, key):
        self.delete_calls.append((tuple(namespace), key))
        self.data.get(tuple(namespace), {}).pop(key, None)

    def search(self, namespace, query, limit):  # noqa: ARG002
        self.search_calls.append(tuple(namespace))
        return []


def _graph_with_memory_store(store):
    return build_graph(
        settings=Settings(),
        store=store,
        memory_retriever=MemoryRetriever(store=None),
        memory_extractor=MemoryExtractor(mode="off"),
    )


def test_graph_memory_search_binds_missing_context_args_and_avoids_default_project(monkeypatch):
    store = _RecordingMemoryStore()
    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {
                "id": "memory-search-1",
                "name": "memory_search",
                "args": {"query": "concise"},
            }
        ],
    )
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    result = _graph_with_memory_store(store).invoke(
        {
            "messages": [HumanMessage(content="use the memory tool")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="root-1"),
        version="v2",
    )

    tool_messages = [message for message in result.value["messages"] if isinstance(message, ToolMessage)]
    payload = json.loads(tool_messages[-1].content)

    assert tool_messages[-1].status == "success"
    assert ["user", "user-1", "profile"] in payload["namespaces"]
    assert ["conversation", "root-1", "main"] in payload["namespaces"]
    assert ["project", "default", "memory"] not in payload["namespaces"]
    assert ("project", "default", "memory") not in store.search_calls


def test_graph_memory_tool_rejects_mismatched_user_and_root_without_executing(monkeypatch):
    store = _RecordingMemoryStore()
    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {
                "id": "memory-save-1",
                "name": "memory_save",
                "args": {
                    "content": "User prefers concise answers.",
                    "user_id": "other-user",
                },
            },
            {
                "id": "memory-forget-1",
                "name": "memory_forget",
                "args": {"memory_id": "memory-1", "root_thread_id": "other-root"},
            },
        ],
    )
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    result = _graph_with_memory_store(store).invoke(
        {
            "messages": [HumanMessage(content="use the memory tool")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="root-1"),
        version="v2",
    )

    tool_messages = [message for message in result.value["messages"] if isinstance(message, ToolMessage)]
    errors = [json.loads(message.content) for message in tool_messages]

    assert [message.status for message in tool_messages] == ["error", "error"]
    assert "user_id" in errors[0]["error"]
    assert "root_thread_id" in errors[1]["error"]
    assert store.put_calls == []
    assert store.delete_calls == []


def test_graph_memory_tool_rejects_explicit_other_user_namespace(monkeypatch):
    store = _RecordingMemoryStore()
    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {
                "id": "memory-search-1",
                "name": "memory_search",
                "args": {"query": "concise", "namespace": "user/other-user/profile"},
            }
        ],
    )
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    result = _graph_with_memory_store(store).invoke(
        {
            "messages": [HumanMessage(content="use the memory tool")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="root-1"),
        version="v2",
    )

    tool_messages = [message for message in result.value["messages"] if isinstance(message, ToolMessage)]
    payload = json.loads(tool_messages[-1].content)

    assert tool_messages[-1].status == "error"
    assert "outside the active request context" in payload["error"]
    assert store.search_calls == []


def test_graph_memory_tool_rejects_skill_scope_without_executing(monkeypatch):
    store = _RecordingMemoryStore()
    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {
                "id": "memory-search-1",
                "name": "memory_search",
                "args": {"query": "research", "namespace": "skill/research/memory"},
            }
        ],
    )
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    result = _graph_with_memory_store(store).invoke(
        {
            "messages": [HumanMessage(content="use the memory tool")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="root-1"),
        version="v2",
    )

    tool_messages = [message for message in result.value["messages"] if isinstance(message, ToolMessage)]
    payload = json.loads(tool_messages[-1].content)

    assert tool_messages[-1].status == "error"
    assert "skill-scoped memory is not allowed" in payload["error"]
    assert store.search_calls == []


def test_graph_memory_tool_allows_current_branch_namespace(monkeypatch):
    store = _RecordingMemoryStore()
    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {
                "id": "memory-search-1",
                "name": "memory_search",
                "args": {
                    "query": "finding",
                    "namespace": "conversation/root-1/branch/branch-1/local_memory",
                },
            }
        ],
    )
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    result = _graph_with_memory_store(store).invoke(
        {
            "messages": [HumanMessage(content="use the memory tool")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(
            user_id="user-1",
            root_thread_id="root-1",
            branch_id="branch-1",
        ),
        version="v2",
    )

    tool_messages = [message for message in result.value["messages"] if isinstance(message, ToolMessage)]

    assert tool_messages[-1].status == "success"
    assert store.search_calls == [
        ("conversation", "root-1", "branch", "branch-1", "local_memory")
    ]


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


def test_graph_tool_executor_enforces_max_calls_per_turn(monkeypatch):
    lookup_calls = 0

    @tool
    def limited_lookup(query: str) -> str:
        """Lookup with a per-turn call budget."""
        nonlocal lookup_calls
        lookup_calls += 1
        return query

    limited_lookup.metadata = {
        "allowed_roles": ("executor",),
        "intent_policies": ("execution",),
        "max_calls_per_turn": 1,
    }

    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {"id": "limited-1", "name": "limited_lookup", "args": {"query": "alpha"}},
            {"id": "limited-2", "name": "limited_lookup", "args": {"query": "beta"}},
        ],
        final_answer="handled limit",
    )
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(limited_lookup,)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="run two limited lookups")],
            "selected_model": "openai:fake",
        },
        context=RequestContext(user_id="user-1", root_thread_id="limit-tool-calls"),
        version="v2",
    )

    tool_messages = [message for message in result.value["messages"] if isinstance(message, ToolMessage)]
    denied_payload = json.loads(tool_messages[1].content)
    assert lookup_calls == 1
    assert tool_messages[0].status == "success"
    assert tool_messages[1].status == "error"
    assert denied_payload["runtime"]["max_calls_per_turn_exceeded"] is True


def test_graph_tool_executor_backstop_denies_unexposed_web_search_for_direct_and_workspace_turns(monkeypatch):
    prompts = [
        "不要联网。最近哪些 AI 工具比较火？",
        "列出当前项目的文件结构概况。",
    ]

    for prompt in prompts:
        web_calls = 0

        class FakeModel:
            def bind_tools(self, _tools):
                return self

            def with_config(self, _config):
                return self

            def invoke(self, prompt_messages):
                if any(isinstance(message, ToolMessage) for message in prompt_messages):
                    return AIMessage(content="handled denied tool")
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "hallucinated-web",
                            "name": "web_search",
                            "args": {"query": "should not execute"},
                        }
                    ],
                )

        monkeypatch.setattr(
            "focus_agent.engine.graph_builder.create_chat_model",
            lambda *args, **kwargs: FakeModel(),
        )

        @tool
        def list_files(path: str = ".") -> str:
            """List workspace files."""
            return path

        @tool
        def search_code(query: str) -> str:
            """Search repository code."""
            return query

        @tool
        def read_file(path: str) -> str:
            """Read a workspace file."""
            return path

        @tool
        def web_search(query: str) -> str:
            """Search the live web."""
            nonlocal web_calls
            web_calls += 1
            raise AssertionError(f"web_search should not execute for {query}")

        graph = build_graph(
            settings=Settings(
                agent_tool_router_enabled=True,
                agent_tool_router_enforce=True,
            ),
            tool_registry=ToolRegistry(
                tools=(list_files, search_code, read_file, web_search),
            ),
        )

        result = graph.invoke(
            {
                "messages": [HumanMessage(content=prompt)],
                "selected_model": "openai:fake",
            },
            context=RequestContext(
                user_id="user-1",
                root_thread_id=f"backstop-web-{len(prompt)}",
            ),
            version="v2",
        )

        tool_messages = [
            message
            for message in result.value["messages"]
            if isinstance(message, ToolMessage) and message.tool_call_id == "hallucinated-web"
        ]
        assert web_calls == 0
        assert tool_messages
        assert tool_messages[-1].status == "error"


def test_graph_tool_executor_backstop_denies_live_web_write_hallucination(monkeypatch):
    write_calls = 0

    class FakeModel:
        def bind_tools(self, _tools):
            return self

        def with_config(self, _config):
            return self

        def invoke(self, prompt_messages):
            tool_messages = [
                message for message in prompt_messages if isinstance(message, ToolMessage)
            ]
            if any(message.tool_call_id == "hallucinated-write" for message in tool_messages):
                return AIMessage(content="handled denied write")
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "hallucinated-write",
                        "name": "write_text_artifact",
                        "args": {"title": "web", "content": "should not write"},
                    }
                ],
            )

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: FakeModel(),
    )

    @tool
    def web_search(query: str) -> str:
        """Search the live web."""
        return '{"answer":"local web-search fixture"}'

    @tool
    def write_text_artifact(title: str, content: str) -> str:
        """Write an artifact."""
        nonlocal write_calls
        write_calls += 1
        raise AssertionError(
            f"write_text_artifact should not execute for {title}:{content}"
        )

    graph = build_graph(
        settings=Settings(
            agent_tool_router_enabled=True,
            agent_tool_router_enforce=True,
        ),
        tool_registry=ToolRegistry(tools=(web_search, write_text_artifact)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="帮我查一下最近 AI 编程工具有哪些更新。")],
            "selected_model": "openai:fake",
        },
        context=RequestContext(user_id="user-1", root_thread_id="backstop-live-web-write"),
        version="v2",
    )

    tool_messages = [
        message
        for message in result.value["messages"]
        if isinstance(message, ToolMessage) and message.tool_call_id == "hallucinated-write"
    ]
    assert write_calls == 0
    assert tool_messages
    assert tool_messages[-1].status == "error"


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


def test_graph_tool_executor_interrupts_before_required_approval_and_resumes_approve(
    monkeypatch, tmp_path
):
    call_count = 0

    @tool
    def approval_lookup(name: str) -> str:
        """Lookup that requires approval."""
        nonlocal call_count
        call_count += 1
        return f"approved:{name}"

    approval_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": False,
        "requires_approval": True,
        "risk_level": "high",
        "intent_policies": ("execution",),
        "allowed_roles": ("executor",),
    }

    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {"id": "approval-1", "name": "approval_lookup", "args": {"name": "focus"}},
        ],
        final_answer="approval handled",
    )
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    graph = build_graph(
        settings=Settings(
            agent_tool_router_enabled=True,
            agent_tool_router_enforce=True,
        ),
        checkpointer=PersistentInMemorySaver(tmp_path / "checkpoints.pkl"),
        tool_registry=ToolRegistry(tools=(approval_lookup,)),
    )
    config = {"configurable": {"thread_id": "thread-approval-approve"}}
    context = RequestContext(user_id="user-1", root_thread_id="thread-approval-approve")

    interrupted = graph.invoke(
        {
            "messages": [HumanMessage(content="run approval lookup")],
            "selected_model": "openai:deepseek-reasoner",
        },
        config=config,
        context=context,
        version="v2",
    )

    assert call_count == 0
    assert interrupted.interrupts
    interrupt_payload = getattr(interrupted.interrupts[0], "value", None)
    assert interrupt_payload["kind"] == "tool_approval"
    assert interrupt_payload["interrupt_id"].startswith("tool-approval:approval-1:")
    assert interrupt_payload["tool_name"] == "approval_lookup"
    assert interrupt_payload["tool_call_id"] == "approval-1"
    assert "args" not in interrupt_payload
    assert interrupt_payload["redacted_args"] == {"name": "focus"}
    assert interrupt_payload["risk_level"] == "high"
    assert interrupt_payload["policy_version"] == "tool_approval.v2"
    assert "approval_lookup" in interrupted.value["tool_route_plan"]["allowed_tools"]

    resumed = graph.invoke(
        Command(
            resume={
                "kind": "tool_approval",
                "interrupt_id": interrupt_payload["interrupt_id"],
                "tool_call_id": "approval-1",
                "approved": True,
            }
        ),
        config=config,
        context=context,
        version="v2",
    )

    tool_messages = [message for message in resumed.value["messages"] if isinstance(message, ToolMessage)]
    approval_records = [
        record
        for record in resumed.value["governance_records"]
        if record["name"] == "tool_approval_decision"
    ]
    assert call_count == 1
    assert approval_records[-1]["payload"]["approved"] is True
    assert approval_records[-1]["payload"]["tool_name"] == "approval_lookup"
    assert approval_records[-1]["payload"]["tool_call_id"] == "approval-1"
    assert "args" not in approval_records[-1]["payload"]
    assert approval_records[-1]["payload"]["redacted_args"] == {"name": "focus"}
    assert approval_records[-1]["payload"]["risk_level"] == "high"
    assert tool_messages[-1].content == "approved:focus"
    assert resumed.value["messages"][-1].content == "approval handled"


def test_graph_tool_executor_resume_deny_writes_structured_tool_error(monkeypatch, tmp_path):
    call_count = 0

    @tool
    def approval_lookup(name: str) -> str:
        """Lookup that requires approval."""
        nonlocal call_count
        call_count += 1
        return f"approved:{name}"

    approval_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": False,
        "requires_approval": True,
        "risk_level": "high",
    }

    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {"id": "approval-deny-1", "name": "approval_lookup", "args": {"name": "focus"}},
        ],
        final_answer="approval denied handled",
    )
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    graph = build_graph(
        settings=Settings(),
        checkpointer=PersistentInMemorySaver(tmp_path / "checkpoints.pkl"),
        tool_registry=ToolRegistry(tools=(approval_lookup,)),
    )
    config = {"configurable": {"thread_id": "thread-approval-deny"}}
    context = RequestContext(user_id="user-1", root_thread_id="thread-approval-deny")
    interrupted = graph.invoke(
        {
            "messages": [HumanMessage(content="run approval lookup")],
            "selected_model": "openai:deepseek-reasoner",
        },
        config=config,
        context=context,
        version="v2",
    )
    interrupt_payload = getattr(interrupted.interrupts[0], "value", None)

    resumed = graph.invoke(
        Command(
            resume={
                "kind": "tool_approval",
                "interrupt_id": interrupt_payload["interrupt_id"],
                "tool_call_id": "approval-deny-1",
                "approved": False,
            }
        ),
        config=config,
        context=context,
        version="v2",
    )

    tool_messages = [message for message in resumed.value["messages"] if isinstance(message, ToolMessage)]
    approval_records = [
        record
        for record in resumed.value["governance_records"]
        if record["name"] == "tool_approval_decision"
    ]
    payload = json.loads(tool_messages[-1].content)
    assert call_count == 0
    assert approval_records[-1]["payload"]["approved"] is False
    assert approval_records[-1]["payload"]["decision"] == "denied"
    assert approval_records[-1]["payload"]["tool_call_id"] == "approval-deny-1"
    assert "args" not in approval_records[-1]["payload"]
    assert approval_records[-1]["payload"]["redacted_args"] == {"name": "focus"}
    assert tool_messages[-1].status == "error"
    assert payload["status"] == "error"
    assert payload["tool"] == "approval_lookup"
    assert "denied by approval response" in payload["error"]
    assert tool_messages[-1].artifact["runtime"]["tool_approval_denied"] is True
    assert resumed.value["messages"][-1].content == "approval denied handled"


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
