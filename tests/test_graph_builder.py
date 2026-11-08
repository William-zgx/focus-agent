import json
import time
from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import tool
from langgraph.types import Command

from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import ConfiguredModel, ModelCatalogConfig, Settings
from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import ContextBudget
from focus_agent.engine.graph.textual_tool_call_repair import (
    _looks_like_textual_tool_call_artifact,
    _repair_tool_free_answer_response,
)
from focus_agent.engine.graph.tool_call_repair import (
    _canonicalize_tool_call_args,
    _repair_and_dedupe_tool_calls,
)
from focus_agent.engine.graph.tool_history_repair import (
    _count_tool_call_rounds_since_latest_human,
    _ensure_reasoning_content_for_tool_call_history,
    _messages_for_model,
    _should_force_tool_free_answer,
)
from focus_agent.engine.graph.tool_result_fallback import (
    _invoke_with_tool_result_fallback,
    _tool_result_fallback_message,
)
from focus_agent.engine.graph_builder import build_graph
from focus_agent.engine.local_persistence import PersistentInMemorySaver
from focus_agent.memory import MemoryExtractor, MemoryRetriever
from focus_agent.multi_agent.approval_queue import InMemoryApprovalQueue


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


def test_messages_for_model_keeps_every_tool_round_of_the_current_turn():
    messages = [
        HumanMessage(content="old question"),
        AIMessage(content="old answer"),
        HumanMessage(content="research question"),
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "web_search", "args": {}}]),
        ToolMessage(content="first result", tool_call_id="c1"),
        AIMessage(content="", tool_calls=[{"id": "c2", "name": "web_fetch", "args": {}}]),
        ToolMessage(content="second result", tool_call_id="c2"),
    ]

    selected = _messages_for_model({"messages": messages, "recent_messages": messages[:3]})

    assert [message.content for message in selected if isinstance(message, ToolMessage)] == [
        "first result",
        "second result",
    ]
    assert [message.content for message in selected[:3]] == [
        "old question",
        "old answer",
        "research question",
    ]


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


def test_messages_for_model_filters_copied_branch_control_context():
    handoff = "10月份去济州岛，那个时候的气温怎么样啊？"
    state = {
        "branch_meta": {
            "branch_id": "branch-new",
            "root_thread_id": "root-1",
            "parent_thread_id": "root-1",
            "branch_fork_message_count": 4,
        },
        "recent_messages": [
            HumanMessage(content="我想去济州岛旅游，你能给我一份攻略大纲吗？"),
            AIMessage(content="济州岛旅行可以按区域和主题规划。"),
            HumanMessage(content="新建子分支，详细的做一下去汉拿山的攻略。"),
            AIMessage(content="我已准备好分支切换确认项：创建子分支 一个新分支。请点击确认。"),
            HumanMessage(content=handoff),
            HumanMessage(content=handoff),
        ],
        "messages": [
            HumanMessage(content="我想去济州岛旅游，你能给我一份攻略大纲吗？"),
            AIMessage(content="济州岛旅行可以按区域和主题规划。"),
            HumanMessage(content="新建子分支，详细的做一下去汉拿山的攻略。"),
            AIMessage(content="我已准备好分支切换确认项：创建子分支 一个新分支。请点击确认。"),
            HumanMessage(content=handoff),
            HumanMessage(content=handoff),
        ],
    }

    messages = _messages_for_model(state)

    assert [message.content for message in messages] == [handoff]


def test_messages_for_model_drops_branch_recent_history_cut_before_tool_call_user():
    state = {
        "branch_meta": {
            "branch_id": "branch-new",
            "root_thread_id": "root-1",
            "parent_thread_id": "root-1",
            "branch_fork_message_count": 3,
        },
        "recent_messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "workspace-search-1",
                        "name": "search_code",
                        "args": {"query": "FINAL_CURRENT_OK_9B21"},
                    }
                ],
            ),
            ToolMessage(content='{"results":[]}', tool_call_id="workspace-search-1"),
            AIMessage(content="FINAL_CURRENT_OK_9B21"),
            HumanMessage(content="我想去韩国旅游，帮我做一个攻略。"),
            AIMessage(content="韩国攻略可以先按首尔和周边规划。"),
            HumanMessage(content="我想去韩国旅游，帮我做一个攻略"),
        ],
        "messages": [
            HumanMessage(content="RUNTIME FINAL CURRENT answer exactly FINAL_CURRENT_OK_9B21"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "workspace-search-1",
                        "name": "search_code",
                        "args": {"query": "FINAL_CURRENT_OK_9B21"},
                    }
                ],
            ),
            ToolMessage(content='{"results":[]}', tool_call_id="workspace-search-1"),
            AIMessage(content="FINAL_CURRENT_OK_9B21"),
            HumanMessage(content="我想去韩国旅游，帮我做一个攻略。"),
            AIMessage(content="韩国攻略可以先按首尔和周边规划。"),
            HumanMessage(content="我想去韩国旅游，帮我做一个攻略"),
        ],
    }

    messages = _messages_for_model(state)

    assert [message.content for message in messages] == [
        "我想去韩国旅游，帮我做一个攻略。",
        "韩国攻略可以先按首尔和周边规划。",
        "我想去韩国旅游，帮我做一个攻略",
    ]
    assert not isinstance(messages[0], AIMessage)
    assert not any(isinstance(message, ToolMessage) for message in messages)


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
        AIMessage(
            content="",
            tool_calls=[{"id": "call-old", "name": "web_search", "args": {"query": "old"}}],
        ),
        ToolMessage(content='{"query":"old"}', tool_call_id="call-old"),
        AIMessage(content="旧回答"),
        HumanMessage(content="新问题"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call-1", "name": "web_search", "args": {"query": "one"}}],
        ),
        ToolMessage(content='{"query":"one"}', tool_call_id="call-1"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call-2", "name": "web_search", "args": {"query": "two"}}],
        ),
        ToolMessage(content='{"query":"two"}', tool_call_id="call-2"),
    ]

    assert _count_tool_call_rounds_since_latest_human(messages) == 2
    assert _should_force_tool_free_answer(messages) is False


def test_should_force_tool_free_answer_after_repeated_same_tool_failure():
    messages = [
        HumanMessage(content="查行情"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call-1",
                    "name": "run_workspace_command",
                    "args": {"command": ["python3", "missing.py"]},
                }
            ],
        ),
        ToolMessage(
            content='{"status":"error","error":"missing script"}',
            tool_call_id="call-1",
            status="error",
        ),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call-2",
                    "name": "run_workspace_command",
                    "args": {"command": ["python3", "missing.py"]},
                }
            ],
        ),
        ToolMessage(
            content='{"status":"error","error":"missing script"}',
            tool_call_id="call-2",
            status="error",
        ),
    ]

    assert _count_tool_call_rounds_since_latest_human(messages) == 2
    assert _should_force_tool_free_answer(messages) is True


def test_should_force_tool_free_answer_after_repeated_string_exit_code_failure():
    messages = [
        HumanMessage(content="查行情"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call-1",
                    "name": "run_workspace_command",
                    "args": {"command": ["python3", "scripts/stocks_client.py"]},
                }
            ],
        ),
        ToolMessage(content='{"exit_code":"1"}', tool_call_id="call-1"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call-2",
                    "name": "run_workspace_command",
                    "args": {"command": ["python3", "scripts/stocks_client.py"]},
                }
            ],
        ),
        ToolMessage(content='{"exit_code":"1"}', tool_call_id="call-2"),
    ]

    assert _should_force_tool_free_answer(messages) is True


def test_messages_for_model_repairs_dangling_tool_calls_before_provider_prompt():
    state = {
        "recent_messages": [],
        "messages": [
            HumanMessage(content="查行情"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "run_workspace_command",
                        "args": {"command": ["python3", "scripts/stocks_client.py"]},
                    }
                ],
            ),
            HumanMessage(content="继续回答"),
        ],
    }

    messages = _messages_for_model(state)

    assert isinstance(messages[1], AIMessage)
    assert isinstance(messages[2], ToolMessage)
    assert messages[2].tool_call_id == "call-1"
    assert messages[2].status == "error"
    assert messages[2].artifact["runtime"]["dangling_tool_call_repaired"] is True
    assert isinstance(messages[3], HumanMessage)


def test_detects_textual_tool_call_artifacts():
    assert _looks_like_textual_tool_call_artifact(
        AIMessage(
            content='<｜DSML｜function_calls><｜DSML｜invoke name="web_search"></｜DSML｜invoke>'
        )
    )
    assert _looks_like_textual_tool_call_artifact(
        AIMessage(
            content=(
                "让我进一步获取几个关键来源的详细内容，以便给出更有深度的回答。\n\n"
                "< | | DSML | | tool_calls>\n"
                '< | | DSML | | invoke nameweb_search">\n'
                '< | | DSML | | parameter name="query" string="true">AI breakthroughs</ | | DSML | | parameter>'
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
        AIMessage(
            content=(
                '<tool_req name="run_shell_command">\n'
                '<arg name="command" string="true">cd /home/focus/.focus_agent/skills/stocks '
                "&& python3 scripts/stocks_client.py quote 601020.SS</arg>\n"
                '<arg name="timeout" string="false">30</arg>\n'
                "</tool_req>"
            )
        )
    )
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
    assert _looks_like_textual_tool_call_artifact(
        AIMessage(
            content='src/focus_agent/capabilities/tool_manifest.py="offset" string20025.claude'
        )
    )
    assert _looks_like_textual_tool_call_artifact(
        AIMessage(
            content='src/focus_agent/capabilities/default_tool_modules/workspace.pyfalse">1212alls>'
        )
    )
    assert not _looks_like_textual_tool_call_artifact(AIMessage(content="[背景] 北京今天晴。"))
    assert not _looks_like_textual_tool_call_artifact(
        AIMessage(content="北京今天晴，最高气温25℃。")
    )
    assert not _looks_like_textual_tool_call_artifact(
        AIMessage(content="我尝试过几种投资方法，最终更偏向长期持有。")
    )
    assert not _looks_like_textual_tool_call_artifact(
        AIMessage(content="我来帮你分析这份报告：结论是现金流改善。")
    )


def _first_tool_call(messages):
    tool_call_messages = [
        message
        for message in messages
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None)
    ]
    assert tool_call_messages
    return tool_call_messages[0].tool_calls[0]


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

    answer = _tool_result_fallback_message(prompt_messages).content

    assert "graph_builder.py:512" in answer
    assert "context_policy.py:43" in answer


def test_fallback_answer_from_tool_results_includes_search_code_context():
    prompt_messages = [
        HumanMessage(content="查证 skill_install 的 allowed_roles。"),
        ToolMessage(
            content=json.dumps(
                {
                    "query": "skill_install",
                    "results": [
                        {
                            "path": "src/focus_agent/capabilities/tool_manifest.py",
                            "line_number": 188,
                            "line": '    "skill_install": {',
                            "context": (
                                '188 |     "skill_install": {\n'
                                '199 |         "allowed_roles": ("skill_scout",),\n'
                                '200 |         "requires_workspace_write": True,'
                            ),
                        }
                    ],
                }
            ),
            tool_call_id="call-1",
        ),
    ]

    answer = _tool_result_fallback_message(prompt_messages).content

    assert "tool_manifest.py:188" in answer
    assert "allowed_roles" in answer
    assert "requires_workspace_write" in answer


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
            "context_budget": ContextBudget(
                prompt_token_limit=2000,
                output_token_reserve=0,
                chars_per_token=1,
            ),
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    prompt_messages = fake_model.invocations[0]
    rendered = "\n".join(str(message.content) for message in prompt_messages)

    assert result.value["messages"][-1].content.startswith("杨絮")
    assert len(fake_model.bound_tool_batches) == 1
    assert set(fake_model.bound_tool_batches[0]) == {"web_search", "run_subtask", "todo_write"}
    assert current_turn in rendered
    assert "Keep the current writing request authoritative." in rendered
    assert "obsolete summary" not in rendered


@pytest.mark.parametrize(
    "user_request", ["Answer this request.", "Search web for the latest DeepSeek news."]
)
def test_graph_blocks_model_when_required_context_overflows(monkeypatch, user_request):
    class FakeRunnable:
        def __init__(self, owner):
            self.owner = owner

        def with_config(self, _config):
            return self

        def invoke(self, prompt_messages):
            self.owner.invocations.append(list(prompt_messages))
            return AIMessage(content="should not be generated")

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
        return query

    graph = build_graph(settings=Settings(), tool_registry=ToolRegistry(tools=(web_search,)))
    result = graph.invoke(
        {
            "messages": [HumanMessage(content=user_request)],
            "selected_model": "openai:deepseek-reasoner",
            "user_constraints": [{"constraint": "required rule " * 200}],
            "context_budget": ContextBudget(
                prompt_token_limit=100,
                output_token_reserve=0,
                chars_per_token=1,
            ),
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-1"),
        version="v2",
    )

    assert fake_model.invocations == []
    assert "model was not invoked" in result.value["messages"][-1].content
    assert result.value["plan_meta"]["context_budget_exhausted"] is True
    assert result.value["task_outcome"]["status"] == "blocked"
    assert "__context_budget__" not in str(result.value["task_outcome"])
    assert "prompt budget" in result.value["task_outcome"]["degradation_reason"]
    assert result.value.get("pending_tool_action") is None


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
            return AIMessage(
                content="根据工具结果，assemble_context 位于 context_policy.py 第 42 行。"
            )

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


def test_tool_result_fallback_returns_evidence_without_retrying_model_after_timeout():
    class TimeoutModel:
        def __init__(self):
            self.calls = 0

        def invoke(self, _prompt_messages):
            self.calls += 1
            raise TimeoutError("upstream model timed out")

    model = TimeoutModel()
    response = _invoke_with_tool_result_fallback(
        model,
        [
            HumanMessage(content="请用中文总结 Python 3.13 官方文档。"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "python-docs",
                        "name": "web_fetch",
                        "args": {"url": "https://docs.python.org/3/whatsnew/3.13.html"},
                    }
                ],
            ),
            ToolMessage(
                content=(
                    '{"url":"https://docs.python.org/3/whatsnew/3.13.html",'
                    '"title":"What’s New In Python 3.13",'
                    '"content":"Python 3.13 includes experimental free-threaded mode."}'
                ),
                tool_call_id="python-docs",
            ),
        ],
    )

    assert model.calls == 1
    assert "超时" in response.content
    assert "What’s New In Python 3.13" in response.content


def test_fallback_answer_from_tool_results_summarizes_web_search_payload():
    answer = _tool_result_fallback_message(
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
            ),
        ]
    ).content

    assert "根据搜索结果" in answer
    assert "工具 web_search" not in answer
    assert "Evidence [" not in answer
    assert "比亚迪A股上周先涨后跌" in answer
    assert "BYD share price" in answer


def test_fallback_answer_from_tool_results_excludes_unrelated_same_turn_web_search():
    answer = _tool_result_fallback_message(
        [
            HumanMessage(content="今天北京天气怎么样？"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "weather-search",
                        "name": "web_search",
                        "args": {"query": "今天北京天气"},
                    },
                    {
                        "id": "sports-search",
                        "name": "web_search",
                        "args": {"query": "NBA finals schedule"},
                    },
                ],
            ),
            ToolMessage(
                content=(
                    '{"query":"今天北京天气","results":[{"title":"Beijing weather",'
                    '"url":"https://weather.example/beijing","content":"北京今天晴。"}]}'
                ),
                tool_call_id="weather-search",
            ),
            ToolMessage(
                content=(
                    '{"query":"NBA finals schedule","results":[{"title":"NBA finals",'
                    '"url":"https://sports.example/nba","content":"Basketball schedule."}]}'
                ),
                tool_call_id="sports-search",
            ),
        ]
    ).content

    assert "Beijing weather" in answer
    assert "NBA finals" not in answer
    assert "Basketball schedule" not in answer


def test_fallback_answer_from_tool_results_formats_weather_as_final_answer():
    answer = _tool_result_fallback_message(
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
                    '{"query":"2026-05-27 北京 天气","answer":"Beijing will be partly cloudy.",'
                    '"results":[{"title":"2026年5月27日天气预报 - 密云区人民政府",'
                    '"url":"https://www.bjmy.gov.cn/sy/tqyb/202605/t20260527_543010.html",'
                    '"content":"5月27日07时发布天气预报：今天白天：晴转多云，北转南风3级，'
                    "阵风5级，最高气温28℃；今天夜间：多云转晴，南转北风2-3级，"
                    '最低气温18℃。"}]}'
                ),
                tool_call_id="weather-search",
            ),
        ]
    ).content

    assert answer.startswith("根据搜索结果，今天白天：晴转多云")
    assert "最高气温28℃" in answer
    assert "最低气温18℃" in answer
    assert "来源：" in answer
    assert "Evidence [" not in answer
    assert "保守整理" not in answer


def test_fallback_answer_from_tool_results_uses_latest_turn_and_compacted_refs():
    answer = _tool_result_fallback_message(
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
    ).content

    assert "比亚迪 002594" in answer
    assert "https://xueqiu.com/S/SZ002594" in answer
    assert "https://quote.eastmoney.com/sz002594.html" in answer
    assert "旧一轮比特币结果" not in answer


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


class _TwoRoundToolModel:
    def __init__(self, *, first_tool_calls, second_tool_calls, final_answer: str = "done"):
        self.first_tool_calls = first_tool_calls
        self.second_tool_calls = second_tool_calls
        self.final_answer = final_answer
        self.invocations = 0

    def bind_tools(self, _tools):
        return self

    def with_config(self, _config):
        return self

    def invoke(self, _prompt_messages):
        self.invocations += 1
        if self.invocations == 1:
            return AIMessage(content="", tool_calls=self.first_tool_calls)
        if self.invocations == 2:
            return AIMessage(content="", tool_calls=self.second_tool_calls)
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

    tool_messages = [
        message for message in result.value["messages"] if isinstance(message, ToolMessage)
    ]
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

    tool_messages = [
        message for message in result.value["messages"] if isinstance(message, ToolMessage)
    ]
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

    tool_messages = [
        message for message in result.value["messages"] if isinstance(message, ToolMessage)
    ]
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

    tool_messages = [
        message for message in result.value["messages"] if isinstance(message, ToolMessage)
    ]
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

    tool_messages = [
        message for message in result.value["messages"] if isinstance(message, ToolMessage)
    ]

    assert tool_messages[-1].status == "success"
    assert store.search_calls == [("conversation", "root-1", "branch", "branch-1", "local_memory")]


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


def test_graph_tool_executor_retries_retryable_failure_once(monkeypatch):
    calls = 0

    @tool
    def flaky_lookup(query: str) -> str:
        """Flaky read-only lookup."""
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary network connection reset")
        return f"ok:{query}"

    flaky_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": False,
    }

    def _assert_retry_prompt(prompt_messages):
        tool_messages = [message for message in prompt_messages if isinstance(message, ToolMessage)]
        assert len(tool_messages) == 1
        assert tool_messages[-1].status == "success"
        assert tool_messages[-1].content == "ok:oops"

    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {
                "id": "flaky-1",
                "name": "flaky_lookup",
                "args": {"query": "oops"},
            }
        ],
        final_answer="handled retry",
        on_final_invoke=_assert_retry_prompt,
    )

    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    graph = build_graph(
        settings=Settings(),
        tool_registry=ToolRegistry(tools=(flaky_lookup,)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="please inspect the flaky thing")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-retry"),
        version="v2",
    )

    outcomes = result.value["tool_outcomes"]
    assert calls == 2
    assert [item["status"] for item in outcomes] == ["failed", "recovered"]
    assert [item["attempt_index"] for item in outcomes] == [1, 2]
    assert result.value["task_outcome"]["status"] == "answered"
    assert result.value["messages"][-1].content == "handled retry"


def test_graph_tool_executor_allows_retry_for_retry_safe_approved_workspace_command_only():
    from focus_agent.engine.graph.tool_execution import _retryable_failed_inputs

    workspace_input = SimpleNamespace(
        tool_call_id="cmd-1",
        tool_name="run_workspace_command",
        runtime=SimpleNamespace(
            side_effect=True,
            side_effect_kind="workspace_command",
            requires_approval=True,
            retry_safe=True,
        ),
    )
    skill_entrypoint_input = SimpleNamespace(
        tool_call_id="skill-1",
        tool_name="run_skill_entrypoint",
        runtime=SimpleNamespace(
            side_effect=True,
            side_effect_kind="workspace_command",
            requires_approval=True,
            retry_safe=True,
        ),
    )
    patch_input = SimpleNamespace(
        tool_call_id="patch-1",
        tool_name="apply_patch",
        runtime=SimpleNamespace(
            side_effect=True,
            side_effect_kind="workspace_write",
            requires_approval=True,
            retry_safe=True,
        ),
    )
    outcomes = [
        {
            "tool_call_id": "cmd-1",
            "status": "failed",
            "retryable": True,
            "attempt_index": 1,
            "max_attempts": 2,
        },
        {
            "tool_call_id": "skill-1",
            "status": "failed",
            "retryable": True,
            "attempt_index": 1,
            "max_attempts": 2,
        },
        {
            "tool_call_id": "patch-1",
            "status": "failed",
            "retryable": True,
            "attempt_index": 1,
            "max_attempts": 2,
        },
    ]

    retry_inputs = _retryable_failed_inputs(
        outcomes,
        execution_inputs_by_index={
            0: workspace_input,
            1: skill_entrypoint_input,
            2: patch_input,
        },
    )

    assert retry_inputs == [workspace_input, skill_entrypoint_input]


def test_graph_tool_executor_does_not_retry_side_effect_without_retry_safe_metadata():
    from focus_agent.engine.graph.tool_execution import _retryable_failed_inputs

    workspace_input = SimpleNamespace(
        tool_call_id="cmd-1",
        tool_name="run_workspace_command",
        runtime=SimpleNamespace(
            side_effect=True,
            side_effect_kind="workspace_command",
            requires_approval=True,
            retry_safe=False,
        ),
    )
    retry_safe_input = SimpleNamespace(
        tool_call_id="cmd-2",
        tool_name="run_workspace_command",
        runtime=SimpleNamespace(
            side_effect=True,
            side_effect_kind="workspace_command",
            requires_approval=True,
            retry_safe=True,
        ),
    )
    outcomes = [
        {
            "tool_call_id": "cmd-1",
            "status": "failed",
            "retryable": True,
            "attempt_index": 1,
            "max_attempts": 2,
        },
        {
            "tool_call_id": "cmd-2",
            "status": "failed",
            "retryable": True,
            "attempt_index": 1,
            "max_attempts": 2,
        },
    ]

    retry_inputs = _retryable_failed_inputs(
        outcomes,
        execution_inputs_by_index={0: workspace_input, 1: retry_safe_input},
    )

    assert retry_inputs == [retry_safe_input]


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

    tool_messages = [
        message for message in result.value["messages"] if isinstance(message, ToolMessage)
    ]
    denied_payload = json.loads(tool_messages[1].content)
    assert lookup_calls == 1
    assert tool_messages[0].status == "success"
    assert tool_messages[1].status == "error"
    assert denied_payload["runtime"]["max_calls_per_turn_exceeded"] is True


def test_graph_tool_executor_enforces_max_calls_across_tool_rounds(monkeypatch):
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

    fake_model = _TwoRoundToolModel(
        first_tool_calls=[
            {"id": "limited-1", "name": "limited_lookup", "args": {"query": "alpha"}},
        ],
        second_tool_calls=[
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
            "messages": [HumanMessage(content="run limited lookups repeatedly")],
            "selected_model": "openai:fake",
        },
        context=RequestContext(user_id="user-1", root_thread_id="limit-tool-rounds"),
        version="v2",
    )

    tool_messages = [
        message for message in result.value["messages"] if isinstance(message, ToolMessage)
    ]
    denied_payload = json.loads(tool_messages[-1].content)
    assert lookup_calls == 1
    assert tool_messages[0].status == "success"
    assert tool_messages[-1].status == "error"
    assert denied_payload["runtime"]["max_calls_per_turn_exceeded"] is True


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
        settings=Settings(),
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

    tool_messages = [
        message for message in resumed.value["messages"] if isinstance(message, ToolMessage)
    ]
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


def test_graph_tool_executor_requires_approval_before_apply_patch(monkeypatch, tmp_path):
    call_count = 0

    @tool
    def apply_patch(patch: str) -> str:
        """Apply a workspace patch."""
        nonlocal call_count
        call_count += 1
        return patch

    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {"id": "patch-approval", "name": "apply_patch", "args": {"patch": "diff --git a/a b/a"}}
        ],
        final_answer="patch handled",
    )
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    graph = build_graph(
        settings=Settings(),
        checkpointer=PersistentInMemorySaver(tmp_path / "checkpoints.pkl"),
        tool_registry=ToolRegistry(tools=(apply_patch,)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="修改当前项目里的 README 文件")],
            "selected_model": "openai:deepseek-reasoner",
        },
        config={"configurable": {"thread_id": "thread-apply-patch-approval"}},
        context=RequestContext(user_id="user-1", root_thread_id="thread-apply-patch-approval"),
        version="v2",
    )

    assert call_count == 0
    assert result.interrupts
    interrupt_payload = getattr(result.interrupts[0], "value", None)
    assert interrupt_payload["kind"] == "tool_approval"
    assert interrupt_payload["tool_name"] == "apply_patch"
    assert interrupt_payload["tool_call_id"] == "patch-approval"


def test_graph_tool_executor_default_allow_permission_does_not_skip_approval(monkeypatch, tmp_path):
    from focus_agent.engine.graph.tool_execution import HarnessToolServices
    from focus_agent.harness.agents.factory import _build_new_components
    from focus_agent.harness.schemas import HarnessConfig

    call_count = 0

    @tool
    def apply_patch(patch: str) -> str:
        """Apply a workspace patch."""
        nonlocal call_count
        call_count += 1
        return patch

    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {"id": "patch-allowed", "name": "apply_patch", "args": {"patch": "diff --git a/a b/a"}}
        ],
        final_answer="patch handled",
    )
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )
    permission_manager = _build_new_components(HarnessConfig())["permission_manager"]

    graph = build_graph(
        settings=Settings(),
        checkpointer=PersistentInMemorySaver(tmp_path / "checkpoints.pkl"),
        tool_registry=ToolRegistry(tools=(apply_patch,)),
        harness_services=HarnessToolServices(permission_manager=permission_manager),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="修改当前项目里的 README 文件")],
            "selected_model": "openai:deepseek-reasoner",
        },
        config={"configurable": {"thread_id": "thread-allow-still-approval"}},
        context=RequestContext(user_id="user-1", root_thread_id="thread-allow-still-approval"),
        version="v2",
    )

    assert call_count == 0
    assert result.interrupts
    interrupt_payload = getattr(result.interrupts[0], "value", None)
    assert interrupt_payload["kind"] == "tool_approval"
    assert interrupt_payload["tool_call_id"] == "patch-allowed"


def test_graph_tool_executor_validates_approval_tools_before_interrupt(monkeypatch, tmp_path):
    call_count = 0

    def reject_large_patch(args):
        if len(str(args.get("patch") or "")) > 8:
            raise ValueError("patch exceeds max_patch_bytes")

    @tool
    def apply_patch(patch: str) -> str:
        """Apply a workspace patch."""
        nonlocal call_count
        call_count += 1
        return patch

    apply_patch.metadata = {
        "requires_approval": True,
        "risk_level": "medium",
        "intent_policies": ("execution",),
        "allowed_roles": ("executor",),
        "validator": reject_large_patch,
    }
    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {
                "id": "patch-invalid",
                "name": "apply_patch",
                "args": {"patch": "diff --git a/demo.py b/demo.py\n" * 20},
            }
        ],
        final_answer="invalid patch handled",
    )
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    graph = build_graph(
        settings=Settings(),
        checkpointer=PersistentInMemorySaver(tmp_path / "checkpoints.pkl"),
        tool_registry=ToolRegistry(tools=(apply_patch,)),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="修改当前项目里的 README 文件")],
            "selected_model": "openai:deepseek-reasoner",
        },
        config={"configurable": {"thread_id": "thread-apply-patch-validation"}},
        context=RequestContext(user_id="user-1", root_thread_id="thread-apply-patch-validation"),
        version="v2",
    )

    assert call_count == 0
    assert result.interrupts == ()
    tool_messages = [
        message for message in result.value["messages"] if isinstance(message, ToolMessage)
    ]
    assert tool_messages
    assert tool_messages[-1].artifact["runtime"]["parameter_validation_error"] is True


def test_graph_tool_executor_async_approval_records_pending_without_interrupt(monkeypatch):
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
            {"id": "approval-async", "name": "approval_lookup", "args": {"name": "focus"}},
        ],
        final_answer="approval queued",
    )
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    approval_queue = InMemoryApprovalQueue()
    graph = build_graph(
        settings=Settings(
            multi_agent_v2_enabled=True,
            multi_agent_async_approval_enabled=True,
            agent_tool_router_enabled=True,
            agent_tool_router_enforce=True,
        ),
        tool_registry=ToolRegistry(tools=(approval_lookup,)),
        approval_queue=approval_queue,
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="run approval lookup")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-async-approval"),
        version="v2",
    )

    approval_records = [
        record
        for record in result.value["governance_records"]
        if record["name"] == "tool_approval_request"
    ]
    tool_messages = [
        message for message in result.value["messages"] if isinstance(message, ToolMessage)
    ]
    assert call_count == 0
    assert result.interrupts == ()
    assert approval_records[-1]["payload"]["approval_status"] == "pending"
    assert approval_records[-1]["payload"]["tool_name"] == "approval_lookup"
    assert "args" not in approval_records[-1]["payload"]
    queued = approval_queue.list_pending()
    assert queued[-1].request_id == approval_records[-1]["payload"]["interrupt_id"]
    assert queued[-1].tool_args == {"name": "focus"}
    assert tool_messages[-1].status == "error"
    assert tool_messages[-1].artifact["runtime"]["tool_approval_pending"] is True


def test_graph_tool_executor_async_approval_does_not_block_other_tools(monkeypatch):
    calls: list[str] = []

    @tool
    def approval_lookup(name: str) -> str:
        """Lookup that requires approval."""
        calls.append(f"approval:{name}")
        return f"approved:{name}"

    @tool
    def safe_lookup(name: str) -> str:
        """Lookup that does not require approval."""
        calls.append(f"safe:{name}")
        return f"safe:{name}"

    approval_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": False,
        "requires_approval": True,
        "risk_level": "high",
        "intent_policies": ("execution",),
        "allowed_roles": ("executor",),
    }
    safe_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": False,
        "requires_approval": False,
        "risk_level": "low",
        "intent_policies": ("execution",),
        "allowed_roles": ("executor",),
    }
    fake_model = _SingleRoundToolModel(
        tool_calls=[
            {"id": "approval-async", "name": "approval_lookup", "args": {"name": "focus"}},
            {"id": "safe-async", "name": "safe_lookup", "args": {"name": "focus"}},
        ],
        final_answer="approval queued and safe completed",
    )
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: fake_model,
    )

    graph = build_graph(
        settings=Settings(
            multi_agent_v2_enabled=True,
            multi_agent_async_approval_enabled=True,
            agent_tool_router_enabled=True,
            agent_tool_router_enforce=True,
        ),
        tool_registry=ToolRegistry(tools=(approval_lookup, safe_lookup)),
        approval_queue=InMemoryApprovalQueue(),
    )

    result = graph.invoke(
        {
            "messages": [HumanMessage(content="run both lookups")],
            "selected_model": "openai:deepseek-reasoner",
        },
        context=RequestContext(user_id="user-1", root_thread_id="thread-async-approval-mixed"),
        version="v2",
    )

    tool_messages = [
        message for message in result.value["messages"] if isinstance(message, ToolMessage)
    ]
    assert calls == ["safe:focus"]
    assert [message.tool_call_id for message in tool_messages] == [
        "approval-async",
        "safe-async",
    ]
    assert tool_messages[0].status == "error"
    assert tool_messages[0].artifact["runtime"]["tool_approval_pending"] is True
    assert tool_messages[1].status == "success"
    assert tool_messages[1].content == "safe:focus"


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

    tool_messages = [
        message for message in resumed.value["messages"] if isinstance(message, ToolMessage)
    ]
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


def test_tool_free_repair_rejects_synthesis_that_echoes_known_tool_markup():
    class EchoingModel:
        def invoke(self, _prompt_messages):
            return AIMessage(content="[lookup_widget] assemble_context")

    prompt_messages = [
        SystemMessage(content="system"),
        HumanMessage(content="找到 assemble_context"),
        AIMessage(
            content="",
            tool_calls=[
                {"id": "call-1", "name": "search_code", "args": {"query": "assemble_context"}}
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
        model_for=lambda *_args: EchoingModel(),
        known_tool_names={"lookup_widget"},
    )

    assert "[lookup_widget]" not in repaired.content
    assert "context_policy.py:42" in repaired.content
