from __future__ import annotations

from types import SimpleNamespace

from langchain.messages import AIMessage, HumanMessage

from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.engine.graph import agent_loop
from focus_agent.engine.graph.agent_loop_skill_helpers import (
    explicit_skill_tools_satisfied,
    skill_install_args_from_search_result,
)
from focus_agent.engine.graph.agent_loop_support import _web_fetch_args


class _StaticRunnable:
    def with_config(self, _config):
        return self

    def invoke(self, _prompt_messages):
        return AIMessage(content="拆分后的节点仍可直接回答。")


def test_agent_loop_finalization_hooks_resolve_current_module_patch_seams(monkeypatch):
    def sentinel(*_args, **_kwargs):
        return "patched"

    monkeypatch.setattr(agent_loop, "_latest_tool_result_content", sentinel)

    hooks = agent_loop._agent_loop_update_hooks(lambda *_args: _StaticRunnable())

    assert hooks["_latest_tool_result_content"] is sentinel
    assert hooks["model_with_tools_for"]("model", "mode", []).invoke([]).content == (
        "拆分后的节点仍可直接回答。"
    )


def test_agent_loop_node_still_finalizes_a_direct_answer():
    node = agent_loop.make_agent_loop_node(
        settings=Settings(),
        tools=(),
        tool_registry=ToolRegistry(tools=()),
        model_for=lambda *_args: _StaticRunnable(),
        model_with_tools_for=lambda *_args: _StaticRunnable(),
    )

    updates = node(
        {
            "messages": [HumanMessage(content="请直接回答这个问题。")],
            "assembled_context": "",
            "llm_calls": 0,
        },
        SimpleNamespace(context=SimpleNamespace(root_thread_id="refactor-test")),
    )

    assert updates["messages"][0].content == "拆分后的节点仍可直接回答。"
    assert updates["llm_calls"] == 1
    assert updates["execution_contract"]
    assert updates["answer_verification"]


def test_extracted_skill_helpers_keep_injected_legacy_dependencies():
    assert explicit_skill_tools_satisfied(
        "skills_search",
        [],
        latest_turn_has_tool_result=lambda _messages, name: name == "skills_search",
    )
    assert skill_install_args_from_search_result(
        "安装 stock-analyzer",
        [],
        latest_tool_result_content=lambda _messages, _name: (
            '{"results":[{"skill_id":"stock-analyzer","source_id":"community"}]}'
        ),
        skill_install_name_from_text=lambda _text: "stock-analyzer",
    ) == {"skill_id": "stock-analyzer", "source_id": "community"}
    assert _web_fetch_args({}, "请抓取 https://example.com/path。") == {
        "url": "https://example.com/path"
    }
