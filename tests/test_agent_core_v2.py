from __future__ import annotations

import json

import pytest
from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import tool
from langgraph.types import Command

from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.config_parts.agent import load_agent_config
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.graph_builder import build_graph
from focus_agent.engine.local_persistence import PersistentInMemorySaver
from focus_agent.engine.tools.execution import HarnessToolServices
from focus_agent.harness.governance.permissions import (
    PermissionAction,
    PermissionManager,
    PermissionRule,
)
from focus_agent.memory import MemoryExtractor, MemoryRetriever


@tool
def lookup(name: str) -> str:
    """Look up a project fact by name."""
    return f"fact:{name}"


lookup.metadata = {"parallel_safe": True, "cacheable": False}


class _BoundModel:
    def __init__(self, model, tool_names):
        self._model = model
        self._tool_names = tool_names

    def with_config(self, config):
        self._model.configs.append(dict(config))
        return self

    def invoke(self, prompt_messages):
        return self._model.respond(prompt_messages, self._tool_names)


class _ScriptedModel:
    """Returns scripted responses in order and records what the loop sent."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.bound_tool_names: list[list[str]] = []
        self.configs: list[dict] = []
        self.prompts: list[list] = []

    def bind_tools(self, tools, **_kwargs):
        return _BoundModel(self, sorted(str(getattr(item, "name", "")) for item in tools))

    def with_config(self, config):
        self.configs.append(dict(config))
        return self

    def invoke(self, prompt_messages):
        return self.respond(prompt_messages, [])

    def respond(self, prompt_messages, tool_names):
        self.prompts.append(list(prompt_messages))
        self.bound_tool_names.append(tool_names)
        return self.next_response(tool_names)

    def next_response(self, _tool_names):
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def _v2_graph(
    monkeypatch,
    model,
    tmp_path,
    *,
    tools=(lookup,),
    harness_services=None,
    **settings,
):
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: model,
    )
    return build_graph(
        settings=Settings(**settings),
        checkpointer=PersistentInMemorySaver(tmp_path / "checkpoints.pkl"),
        memory_retriever=MemoryRetriever(store=None),
        memory_extractor=MemoryExtractor(mode="off"),
        tool_registry=ToolRegistry(tools=tuple(tools)),
        harness_services=harness_services,
    )


def _invoke(graph, payload, thread_id: str):
    return graph.invoke(
        payload,
        config={"configurable": {"thread_id": thread_id}},
        context=RequestContext(user_id="user-1", root_thread_id=thread_id),
        version="v2",
    )


def _ask(text: str) -> dict:
    return {"messages": [HumanMessage(content=text)], "selected_model": "openai:gpt-4.1-mini"}


@pytest.mark.parametrize("raw", [None, "", "V2", " v2 "])
def test_agent_core_env_parsing(raw):
    env = {} if raw is None else {"AGENT_CORE": raw}
    assert load_agent_config(env, Settings())["agent_core"] == "v2"


@pytest.mark.parametrize("raw", ["v1", "legacy", "loop", "v3"])
def test_agent_core_env_rejects_other_cores(raw):
    with pytest.raises(ValueError, match="AGENT_CORE must be v2"):
        load_agent_config({"AGENT_CORE": raw}, Settings())


def test_agent_max_tool_rounds_is_at_least_one():
    assert (
        load_agent_config({"AGENT_MAX_TOOL_ROUNDS": "0"}, Settings())["agent_max_tool_rounds"] == 1
    )


def test_v2_graph_keeps_service_addressed_nodes_and_drops_routing(monkeypatch, tmp_path):
    graph = _v2_graph(monkeypatch, _ScriptedModel([AIMessage(content="hi")]), tmp_path)

    nodes = set(graph.get_graph().nodes)

    assert {
        "bootstrap_turn",
        "retrieve_memory",
        "assemble_context",
        "agent_loop",
        "tool_executor",
        "summarize_turn",
        "maybe_interrupt_for_merge",
    } <= nodes
    assert not {"plan", "reflect", "role_route_dry_run", "delegation_governance"} & nodes


def test_default_core_is_the_model_driven_graph(monkeypatch):
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: _ScriptedModel([AIMessage(content="hi")]),
    )

    graph = build_graph(settings=Settings(), tool_registry=ToolRegistry(tools=(lookup,)))

    nodes = set(graph.get_graph().nodes)
    assert "agent_loop" in nodes
    assert "plan" not in nodes


def test_v2_direct_answer_binds_all_tools_and_streams_visibly(monkeypatch, tmp_path):
    model = _ScriptedModel([AIMessage(content="Paris is the capital of France.")])
    graph = _v2_graph(monkeypatch, model, tmp_path)

    result = _invoke(graph, _ask("What is the capital of France?"), "thread-direct")

    final = result.value["messages"][-1]
    assert final.content == "Paris is the capital of France."
    assert model.bound_tool_names == [["lookup", "run_subtask", "todo_write"]]
    assert {"metadata": {"stream_phase": "visible"}, "tags": ["stream_phase:visible"]} in (
        model.configs
    )
    assert result.value["llm_calls"] == 1
    outcome = result.value["task_outcome"]
    assert outcome["status"] == "answered"
    assert outcome["policy"] == "model_driven"
    assert final.response_metadata["focus_agent"]["task_outcome"] == outcome
    assert result.value["plan_meta"]["agent_core"] == "v2"


def test_v2_prompt_carries_operating_rules_once(monkeypatch, tmp_path):
    model = _ScriptedModel([AIMessage(content="ok")])
    graph = _v2_graph(monkeypatch, model, tmp_path)

    _invoke(graph, _ask("hello"), "thread-prompt")

    system_texts = [m.content for m in model.prompts[0] if isinstance(m, SystemMessage)]
    assert sum("## How to work" in text for text in system_texts) == 1
    working_rules = next(text for text in system_texts if "## How to work" in text)
    assert "usually 1-3" in working_rules
    assert "not verification or changes" in working_rules
    assert "narrow the query" in working_rules
    assert isinstance(model.prompts[0][-1], HumanMessage)


def test_v2_model_driven_tool_round_then_answer(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            AIMessage(
                content="Let me look that up.",
                tool_calls=[{"id": "call-1", "name": "lookup", "args": {"name": "focus"}}],
            ),
            AIMessage(content="The fact is fact:focus."),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path)

    result = _invoke(graph, _ask("What do we know about focus?"), "thread-tool")

    messages = result.value["messages"]
    tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
    assert [m.content for m in tool_messages] == ["fact:focus"]
    assert messages[-1].content == "The fact is fact:focus."
    assert result.value["llm_calls"] == 2
    assert any(isinstance(m, ToolMessage) for m in model.prompts[1])
    outcomes = result.value["tool_outcomes"]
    assert [item["tool_name"] for item in outcomes] == ["lookup"]
    assert result.value["task_outcome"]["status"] == "answered"
    assert result.value["task_outcome"]["tool_outcome_ids"]


class _ToolHungryModel(_ScriptedModel):
    """Calls a fresh tool whenever tools are bound; answers once they are withheld."""

    def __init__(self):
        super().__init__([])

    def next_response(self, tool_names):
        if not tool_names:
            return AIMessage(content="Answer from gathered facts.")
        index = len(self.prompts)
        return AIMessage(
            content="",
            tool_calls=[{"id": f"call-{index}", "name": "lookup", "args": {"name": f"n{index}"}}],
        )


def test_v2_tool_budget_forces_an_answer_without_tools(monkeypatch, tmp_path):
    model = _ToolHungryModel()
    graph = _v2_graph(monkeypatch, model, tmp_path, agent_max_tool_rounds=2)

    result = _invoke(graph, _ask("Collect facts"), "thread-budget")

    assert model.bound_tool_names == [
        ["lookup", "run_subtask", "todo_write"],
        ["lookup", "run_subtask", "todo_write"],
        [],
    ]
    last_prompt_system = [m.content for m in model.prompts[-1] if isinstance(m, SystemMessage)]
    assert any("tool budget for this turn is used up" in text for text in last_prompt_system)
    assert result.value["messages"][-1].content == "Answer from gathered facts."
    assert result.value["plan_meta"]["tool_budget_exhausted"] is True


def test_v2_withholds_tools_when_their_schemas_alone_overflow_the_budget(monkeypatch, tmp_path):
    @tool
    def bulky(name: str) -> str:
        """Placeholder."""
        return name

    bulky.description = "Bulky tool description. " * 200
    model = _ScriptedModel([AIMessage(content="A short essay.")])
    graph = _v2_graph(monkeypatch, model, tmp_path, tools=(bulky,))
    payload = _ask("Write a short essay.")
    payload["context_budget"] = {
        "prompt_token_limit": 360,
        "output_token_reserve": 0,
        "chars_per_token": 1,
    }

    result = _invoke(graph, payload, "thread-schema-budget")

    assert model.bound_tool_names == [[]]
    assert result.value["messages"][-1].content == "A short essay."
    assert result.value["plan_meta"]["tools_withheld_for_context"] is True
    assert "context_budget_exhausted" not in result.value["plan_meta"]


def test_v2_synthesizes_an_answer_when_the_model_goes_silent_after_tools(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"id": "call-1", "name": "lookup", "args": {"name": "focus"}}],
            ),
            AIMessage(content=""),
            AIMessage(content="Synthesized from fact:focus."),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path)

    result = _invoke(graph, _ask("What do we know about focus?"), "thread-silent")

    assert result.value["messages"][-1].content == "Synthesized from fact:focus."
    assert model.bound_tool_names == [
        ["lookup", "run_subtask", "todo_write"],
        ["lookup", "run_subtask", "todo_write"],
        [],
    ]
    assert model.configs[-1] == {
        "metadata": {"stream_phase": "visible"},
        "tags": ["stream_phase:visible"],
    }
    assert result.value["plan_meta"]["tool_protocol_repair_reason"] == "empty_final_answer"


def test_v2_falls_back_when_synthesis_has_no_visible_text(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"id": "call-1", "name": "lookup", "args": {"name": "focus"}}],
            ),
            AIMessage(content=[]),
            AIMessage(content=[]),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path)

    result = _invoke(graph, _ask("What do we know about focus?"), "thread-empty-blocks")

    final = result.value["messages"][-1]
    assert final.content
    assert final.additional_kwargs["tool_result_fallback_reason"] == "model_synthesis_failed"
    assert result.value["plan_meta"]["tool_protocol_repair_reason"] == "empty_final_answer"


def test_v2_approval_interrupt_keeps_payload_and_resumes(monkeypatch, tmp_path):
    executed: list[str] = []

    @tool
    def risky_lookup(name: str) -> str:
        """Lookup that requires approval."""
        executed.append(name)
        return f"approved:{name}"

    risky_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": False,
        "requires_approval": True,
        "risk_level": "high",
    }
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"id": "approval-1", "name": "risky_lookup", "args": {"name": "x"}}],
            ),
            AIMessage(content="approval handled"),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path, tools=(risky_lookup,))
    thread_id = "thread-approval"

    interrupted = _invoke(graph, _ask("run the risky lookup"), thread_id)

    assert executed == []
    payload = interrupted.interrupts[0].value
    assert payload["kind"] == "tool_approval"
    assert payload["tool_call_id"] == "approval-1"
    assert payload["redacted_args"] == {"name": "x"}

    resumed = _invoke(
        graph,
        Command(
            resume={
                "kind": "tool_approval",
                "interrupt_id": payload["interrupt_id"],
                "tool_call_id": "approval-1",
                "approved": True,
            }
        ),
        thread_id,
    )

    assert executed == ["x"]
    assert resumed.value["messages"][-1].content == "approval handled"


@pytest.mark.parametrize("approved", [True, False])
def test_v2_permission_ask_uses_approval_resume(monkeypatch, tmp_path, approved):
    executed: list[str] = []

    @tool
    def guarded_lookup(name: str) -> str:
        """Lookup guarded only by a permission rule."""
        executed.append(name)
        return f"approved:{name}"

    guarded_lookup.metadata = {"parallel_safe": True, "cacheable": False}
    manager = PermissionManager(
        rules=[
            PermissionRule(
                action=PermissionAction.ASK,
                tool_pattern="guarded_lookup",
                reason="administrator requires confirmation",
            )
        ]
    )
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "permission-1", "name": "guarded_lookup", "args": {"name": "x"}}
                ],
            ),
            AIMessage(content="permission handled"),
        ]
    )
    graph = _v2_graph(
        monkeypatch,
        model,
        tmp_path,
        tools=(guarded_lookup,),
        harness_services=HarnessToolServices(permission_manager=manager),
    )
    thread_id = f"thread-permission-ask-{approved}"

    interrupted = _invoke(graph, _ask("run the guarded lookup"), thread_id)

    assert executed == []
    payload = interrupted.interrupts[0].value
    assert payload["kind"] == "tool_approval"
    assert payload["tool_name"] == "guarded_lookup"
    assert payload["tool_call_id"] == "permission-1"

    resumed = _invoke(
        graph,
        Command(
            resume={
                "kind": "tool_approval",
                "interrupt_id": payload["interrupt_id"],
                "tool_call_id": "permission-1",
                "approved": approved,
            }
        ),
        thread_id,
    )

    tool_message = next(
        message
        for message in resumed.value["messages"]
        if isinstance(message, ToolMessage) and message.tool_call_id == "permission-1"
    )
    assert resumed.value["messages"][-1].content == "permission handled"
    if approved:
        assert executed == ["x"]
        assert tool_message.content == "approved:x"
    else:
        assert executed == []
        error = json.loads(str(tool_message.content))
        assert error["runtime"]["tool_approval_denied"] is True
        assert "denied" in error["error"]


def test_v2_permission_deny_returns_denied_tool_result(monkeypatch, tmp_path):
    executed: list[str] = []

    @tool
    def denied_lookup(name: str) -> str:
        """Lookup denied by a permission rule."""
        executed.append(name)
        return name

    denied_lookup.metadata = {"parallel_safe": True, "cacheable": False}
    manager = PermissionManager(
        rules=[
            PermissionRule(
                action=PermissionAction.DENY,
                tool_pattern="denied_lookup",
                reason="blocked by administrator",
            )
        ]
    )
    model = _ScriptedModel(
        [
            AIMessage(
                content="",
                tool_calls=[{"id": "denied-1", "name": "denied_lookup", "args": {"name": "x"}}],
            ),
            AIMessage(content="denial handled"),
        ]
    )
    graph = _v2_graph(
        monkeypatch,
        model,
        tmp_path,
        tools=(denied_lookup,),
        harness_services=HarnessToolServices(permission_manager=manager),
    )

    result = _invoke(graph, _ask("run the denied lookup"), "thread-permission-deny")

    assert executed == []
    assert not result.interrupts
    tool_message = next(
        message
        for message in result.value["messages"]
        if isinstance(message, ToolMessage) and message.tool_call_id == "denied-1"
    )
    error = json.loads(str(tool_message.content))
    assert error["error"] == "blocked by administrator"
    assert error["runtime"]["permission_denied"] is True
    assert result.value["messages"][-1].content == "denial handled"


def test_v2_second_turn_sees_prior_history(monkeypatch, tmp_path):
    model = _ScriptedModel([AIMessage(content="first"), AIMessage(content="second")])
    graph = _v2_graph(monkeypatch, model, tmp_path)

    _invoke(graph, _ask("one"), "thread-history")
    result = _invoke(graph, _ask("two"), "thread-history")

    assert [m.content for m in result.value["messages"] if isinstance(m, AIMessage)] == [
        "first",
        "second",
    ]
    human_texts = [m.content for m in model.prompts[1] if isinstance(m, HumanMessage)]
    assert human_texts == ["one", "two"]
    assert result.value["llm_calls"] == 2
