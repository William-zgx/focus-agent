from __future__ import annotations

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


def _v2_graph(monkeypatch, model, tmp_path, *, tools=(lookup,), **settings):
    monkeypatch.setattr(
        "focus_agent.engine.graph.builder.create_chat_model",
        lambda *args, **kwargs: model,
    )
    return build_graph(
        settings=Settings(agent_core="v2", **settings),
        checkpointer=PersistentInMemorySaver(tmp_path / "checkpoints.pkl"),
        memory_retriever=MemoryRetriever(store=None),
        memory_extractor=MemoryExtractor(mode="off"),
        tool_registry=ToolRegistry(tools=tuple(tools)),
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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, "v1"), ("", "v1"), ("legacy", "v1"), ("V2", "v2"), (" loop ", "v2")],
)
def test_agent_core_env_parsing(raw, expected):
    env = {} if raw is None else {"AGENT_CORE": raw}
    assert load_agent_config(env, Settings())["agent_core"] == expected


def test_agent_core_env_rejects_unknown_core():
    with pytest.raises(ValueError, match="AGENT_CORE"):
        load_agent_config({"AGENT_CORE": "v3"}, Settings())


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


def test_default_core_is_still_the_routed_graph(monkeypatch):
    monkeypatch.setattr(
        "focus_agent.engine.graph.builder.create_chat_model",
        lambda *args, **kwargs: _ScriptedModel([AIMessage(content="hi")]),
    )

    graph = build_graph(settings=Settings(), tool_registry=ToolRegistry(tools=(lookup,)))

    assert "plan" in set(graph.get_graph().nodes)


def test_v2_direct_answer_binds_all_tools_and_streams_visibly(monkeypatch, tmp_path):
    model = _ScriptedModel([AIMessage(content="Paris is the capital of France.")])
    graph = _v2_graph(monkeypatch, model, tmp_path)

    result = _invoke(graph, _ask("What is the capital of France?"), "thread-direct")

    final = result.value["messages"][-1]
    assert final.content == "Paris is the capital of France."
    assert model.bound_tool_names == [["lookup"]]
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

    assert model.bound_tool_names == [["lookup"], ["lookup"], []]
    last_prompt_system = [m.content for m in model.prompts[-1] if isinstance(m, SystemMessage)]
    assert any("tool budget for this turn is used up" in text for text in last_prompt_system)
    assert result.value["messages"][-1].content == "Answer from gathered facts."
    assert result.value["plan_meta"]["tool_budget_exhausted"] is True


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
