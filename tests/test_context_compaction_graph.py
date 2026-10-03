from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.core.request_context import RequestContext
from focus_agent.core.state import AgentState
from focus_agent.engine.graph.policy import build_tool_intent_plan
from focus_agent.engine.graph_builder import build_graph
from focus_agent.repositories.sqlite_branch_repository import SQLiteBranchRepository
from focus_agent.services.chat import ChatService, ConcurrentTurnError


class StaticModel:
    def bind_tools(self, _tools):
        return self

    def with_config(self, _config):
        return self

    def invoke(self, _messages, **_kwargs):
        return AIMessage(content="Confirmed E-930")


@pytest.mark.parametrize("instruction", ["不调用工具", "不调用任何工具"])
def test_context_recall_with_explicit_no_tools_does_not_route_to_workspace(instruction):
    plan = build_tool_intent_plan(
        f"现在仅复述主支预算、敏感数据限制和证据编号，{instruction}，60字以内。"
    )
    assert plan.policy == "direct_answer"
    assert "explicit_no_tool" in plan.reason_codes
    assert plan.preferred_first_tool is None


def chat_for_graph(graph, tmp_path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    return ChatService(SimpleNamespace(settings=Settings(), graph=graph, repo=repo))


def test_manual_compaction_writes_to_completed_production_graph(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model", lambda *a, **k: StaticModel()
    )
    graph = build_graph(
        settings=Settings(plan_act_reflect_enabled=False),
        tool_registry=ToolRegistry(tools=()),
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "root-1"}}
    graph.invoke(
        {
            "messages": [HumanMessage(content="Keep evidence E-930", id="human-1")],
            "selected_model": "openai:fake",
        },
        config=config,
        context=RequestContext(user_id="owner-1", root_thread_id="root-1"),
    )
    before = graph.get_state(config)
    response = chat_for_graph(graph, tmp_path).compact_thread_context(
        thread_id="root-1", user_id="owner-1"
    )
    after = graph.get_state(config)
    assert after.values["messages"] == before.values["messages"]
    assert after.next == before.next == ()
    assert after.values["context_compaction"]["trigger"] == "manual"
    assert response["context_usage"]["last_compacted_at"]


def test_manual_compaction_preserves_pending_interrupt_and_resume(tmp_path):
    def await_confirmation(_state):
        answer = interrupt({"question": "Confirm evidence E-930?"})
        return {"messages": [AIMessage(content=f"Confirmation: {answer}", id="confirmation")]}

    builder = StateGraph(AgentState)
    builder.add_node("bootstrap_turn", lambda _state: {"active_goal": "Keep E-930"})
    builder.add_node("await_confirmation", await_confirmation)
    builder.add_edge(START, "bootstrap_turn")
    builder.add_edge("bootstrap_turn", "await_confirmation")
    builder.add_edge("await_confirmation", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "root-1"}}
    graph.invoke({"messages": [HumanMessage(content="Keep E-930", id="human")]}, config=config)
    before = graph.get_state(config)
    with pytest.raises(ConcurrentTurnError, match="response or tool approval is pending"):
        chat_for_graph(graph, tmp_path).compact_thread_context(
            thread_id="root-1", user_id="owner-1"
        )
    after = graph.get_state(config)
    assert after.next == before.next == ("await_confirmation",)
    assert after.values["messages"] == before.values["messages"]
    assert after.tasks[0].interrupts[0].value == before.tasks[0].interrupts[0].value
    result = graph.invoke(Command(resume="yes"), config=config)
    assert result["messages"][-1].content == "Confirmation: yes"
    assert graph.get_state(config).next == ()
