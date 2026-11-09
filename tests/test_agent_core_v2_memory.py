from __future__ import annotations

import json

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.store.memory import InMemoryStore

from focus_agent.capabilities.tool_registry import build_tool_registry
from focus_agent.config import Settings
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.graph_builder import build_graph
from focus_agent.engine.loop.prompt import operating_note
from focus_agent.memory import MemoryExtractor, MemoryRetriever, MemoryWriter
from focus_agent.skills import SkillRegistry
from focus_agent.storage.namespaces import (
    branch_local_memory_namespace,
    root_thread_episodic_namespace,
    user_profile_namespace,
)

PREFERENCE = "我更偏好简洁的回答"


class _BoundModel:
    def __init__(self, model, tool_names):
        self._model = model
        self._tool_names = tool_names

    def with_config(self, config):
        return self

    def invoke(self, prompt_messages):
        return self._model.respond(prompt_messages, self._tool_names)


class _ScriptedModel:
    """Returns scripted responses in order and records what the loop sent."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.bound_tool_names: list[list[str]] = []
        self.prompts: list[list] = []

    def bind_tools(self, tools, **_kwargs):
        return _BoundModel(self, sorted(str(getattr(item, "name", "")) for item in tools))

    def with_config(self, config):
        return self

    def invoke(self, prompt_messages):
        return self.respond(prompt_messages, [])

    def respond(self, prompt_messages, tool_names):
        self.prompts.append(list(prompt_messages))
        self.bound_tool_names.append(tool_names)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def _memory_graph(monkeypatch, model, *, store: InMemoryStore):
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: model,
    )
    return build_graph(
        settings=Settings(),
        store=store,
        memory_retriever=MemoryRetriever(store=store),
        memory_writer=MemoryWriter(store=store),
        memory_extractor=MemoryExtractor(),
    )


def _invoke(graph, text: str, *, branch_id: str | None = None, thread_id: str = "thread-1"):
    return graph.invoke(
        {"messages": [HumanMessage(content=text)], "selected_model": "openai:gpt-4.1-mini"},
        config={"configurable": {"thread_id": thread_id}},
        context=RequestContext(user_id="user-1", root_thread_id=thread_id, branch_id=branch_id),
        version="v2",
    )


def _profile_records(store: InMemoryStore) -> list[dict]:
    return [hit.value for hit in store.search(user_profile_namespace("user-1"), limit=10)]


def _memory_save_call(args: dict, *, call_id: str = "memory-save-1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"id": call_id, "name": "memory_save", "args": args}],
    )


def test_v2_without_memory_save_writes_no_user_preference(monkeypatch):
    store = InMemoryStore()
    model = _ScriptedModel([AIMessage(content="好的，我会保持回答简洁。")])
    graph = _memory_graph(monkeypatch, model, store=store)

    result = _invoke(graph, PREFERENCE)

    assert "memory_save" in model.bound_tool_names[0]
    assert _profile_records(store) == []
    kinds = [hit.value["kind"] for hit in store.search(root_thread_episodic_namespace("thread-1"))]
    assert kinds == ["turn_summary"]
    assert result.value["memory_write_result"]["prepared"] == 1


def test_v2_memory_save_writes_to_trusted_user_profile(monkeypatch):
    store = InMemoryStore()
    model = _ScriptedModel(
        [
            _memory_save_call({"content": PREFERENCE, "kind": "user_preference"}),
            AIMessage(content="记住了。"),
        ]
    )
    graph = _memory_graph(monkeypatch, model, store=store)

    result = _invoke(graph, PREFERENCE)

    tool_messages = [m for m in result.value["messages"] if isinstance(m, ToolMessage)]
    assert [m.status for m in tool_messages] == ["success"]
    payload = json.loads(tool_messages[0].content)
    assert payload["saved"] is True
    assert payload["namespace"] == list(user_profile_namespace("user-1"))
    records = _profile_records(store)
    assert [(item["kind"], item["content"], item["user_id"]) for item in records] == [
        ("user_preference", PREFERENCE, "user-1")
    ]


def test_v2_memory_save_with_foreign_user_id_is_rejected(monkeypatch):
    store = InMemoryStore()
    model = _ScriptedModel(
        [
            _memory_save_call({"content": PREFERENCE, "user_id": "other-user"}),
            AIMessage(content="无法保存。"),
        ]
    )
    graph = _memory_graph(monkeypatch, model, store=store)

    result = _invoke(graph, PREFERENCE)

    tool_messages = [m for m in result.value["messages"] if isinstance(m, ToolMessage)]
    assert [m.status for m in tool_messages] == ["error"]
    assert "user_id" in json.loads(tool_messages[0].content)["error"]
    assert _profile_records(store) == []


def test_v2_branch_memory_save_still_becomes_branch_finding(monkeypatch):
    store = InMemoryStore()
    model = _ScriptedModel(
        [
            _memory_save_call(
                {
                    "content": "Yugabyte needs 3 nodes",
                    "kind": "branch_finding",
                    "scope": "branch",
                }
            ),
            AIMessage(content="已记录分支发现。"),
        ]
    )
    graph = _memory_graph(monkeypatch, model, store=store)

    result = _invoke(graph, "记住这个分支结论。", branch_id="branch-1")

    findings = result.value["branch_local_findings"]
    assert [item["finding"] for item in findings] == ["Yugabyte needs 3 nodes"]
    branch_hits = store.search(branch_local_memory_namespace("thread-1", "branch-1"))
    assert [hit.value["kind"] for hit in branch_hits] == ["branch_finding"]


def test_operating_rules_mention_memory_save_only_when_offered():
    with_memory = operating_note(
        ["memory_save", "memory_search", "memory_forget"], tool_budget_exhausted=False
    )
    without_memory = operating_note(["lookup"], tool_budget_exhausted=False)
    memory_without_save = operating_note(["memory_search"], tool_budget_exhausted=False)

    assert "memory_save" in with_memory
    assert "memory_search" in with_memory
    assert "memory_forget" in with_memory
    assert "secrets" in with_memory
    assert "memory_save" not in without_memory
    assert "memory_save" not in memory_without_save


def test_v2_offers_memory_tools_with_a_repository_backend(monkeypatch):
    class _Repository:
        pass

    registry = build_tool_registry(
        settings=Settings(),
        skill_registry=SkillRegistry.from_settings(Settings()),
        store=None,
        memory_repository=_Repository(),
    )
    model = _ScriptedModel([AIMessage(content="ok")])
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: model,
    )
    graph = build_graph(
        settings=Settings(),
        memory_retriever=MemoryRetriever(store=None),
        memory_extractor=MemoryExtractor(),
        tool_registry=registry,
    )

    _invoke(graph, "hello")

    bound_names = set(model.bound_tool_names[0])
    assert {"memory_save", "memory_search", "tool_search"} <= bound_names
    assert "memory_forget" not in bound_names
    system_texts = [
        message.content for message in model.prompts[0] if isinstance(message, SystemMessage)
    ]
    assert any("- memory_forget:" in text for text in system_texts)


def test_operating_rules_drop_memory_when_tools_are_withheld():
    note = operating_note(["memory_save"], tool_budget_exhausted=True)

    assert "memory_save" not in note
