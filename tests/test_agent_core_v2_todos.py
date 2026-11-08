from __future__ import annotations

import pytest
from langchain.messages import AIMessage, SystemMessage, ToolMessage

from focus_agent.capabilities.tool_registry import ToolRegistry, ToolRuntimeMeta
from focus_agent.config import Settings
from focus_agent.engine.graph_builder import build_graph
from focus_agent.engine.local_persistence import PersistentInMemorySaver
from focus_agent.engine.loop.prompt import operating_note
from focus_agent.engine.loop.todos import MAX_TODOS, build_todo_write_tool, normalize_todos
from focus_agent.memory import MemoryExtractor, MemoryRetriever

from .test_agent_core_v2 import _ask, _invoke, _ScriptedModel, _v2_graph, lookup


def _todo_call(call_id: str, *items: tuple[str, str]) -> AIMessage:
    todos = [{"content": content, "status": status} for content, status in items]
    return AIMessage(
        content="",
        tool_calls=[{"id": call_id, "name": "todo_write", "args": {"todos": todos}}],
    )


def _system_text(prompt) -> str:
    return "\n".join(m.content for m in prompt if isinstance(m, SystemMessage))


def _tool_messages(result) -> list[ToolMessage]:
    return [m for m in result.value["messages"] if isinstance(m, ToolMessage)]


def test_v2_todo_write_round_then_answer_renders_current_todos(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            _todo_call(
                "todo-1",
                ("Read the config", "in_progress"),
                ("Patch the loader", "pending"),
                ("Run the tests", "pending"),
            ),
            _todo_call(
                "todo-2",
                ("Read the config", "completed"),
                ("Patch the loader", "in_progress"),
                ("Run the tests", "pending"),
            ),
            AIMessage(content="All three steps are planned and underway."),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path)

    result = _invoke(graph, _ask("Refactor the loader in three steps"), "thread-todos")

    assert [(m.status, m.content) for m in _tool_messages(result)] == [
        ("success", "Todos updated: 0 completed, 1 in progress, 2 pending."),
        ("success", "Todos updated: 1 completed, 1 in progress, 1 pending."),
    ]
    assert result.value["messages"][-1].content == "All three steps are planned and underway."
    assert result.value["llm_calls"] == 3
    first, second, third = (_system_text(prompt) for prompt in model.prompts)
    assert "todo_write" in first
    assert "## Current todos" not in first
    assert (
        "## Current todos\n"
        "1. [in_progress] Read the config\n"
        "2. [pending] Patch the loader\n"
        "3. [pending] Run the tests"
    ) in second
    assert (
        "1. [completed] Read the config\n"
        "2. [in_progress] Patch the loader\n"
        "3. [pending] Run the tests"
    ) in third
    assert "earlier turn" not in third


def test_v2_invalid_todo_write_returns_error_and_loop_continues(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            _todo_call("todo-bad", ("Step one", "in_progress"), ("Step two", "in_progress")),
            _todo_call("todo-good", ("Step one", "in_progress"), ("Step two", "pending")),
            AIMessage(content="Working through the steps."),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path)

    result = _invoke(graph, _ask("Do the two-step job"), "thread-todos-invalid")

    bad, good = _tool_messages(result)
    assert bad.status == "error"
    assert "keep at most one in progress" in bad.content
    assert good.status == "success"
    assert result.value["messages"][-1].content == "Working through the steps."
    assert "## Current todos" not in _system_text(model.prompts[1])
    assert "1. [in_progress] Step one" in _system_text(model.prompts[2])


def test_v2_repeated_identical_todo_write_is_not_suppressed(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            _todo_call("todo-1", ("Gather facts", "in_progress"), ("Write summary", "pending")),
            _todo_call("todo-2", ("Gather facts", "in_progress"), ("Write summary", "pending")),
            AIMessage(content="done"),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path)

    result = _invoke(graph, _ask("Summarize the project"), "thread-todos-repeat")

    assert [m.status for m in _tool_messages(result)] == ["success", "success"]


def test_v2_todos_carry_over_turns_until_every_item_is_completed(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            _todo_call("todo-1", ("Draft outline", "completed"), ("Write body", "in_progress")),
            AIMessage(content="Outline done; body is next."),
            _todo_call("todo-2", ("Draft outline", "completed"), ("Write body", "completed")),
            AIMessage(content="Body written."),
            AIMessage(content="Anything else?"),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path)
    thread_id = "thread-todos-turns"

    _invoke(graph, _ask("Write the report"), thread_id)
    _invoke(graph, _ask("continue"), thread_id)
    _invoke(graph, _ask("thanks"), thread_id)

    resumed = _system_text(model.prompts[2])
    assert "## Current todos" in resumed
    assert "earlier turn" in resumed
    assert "2. [in_progress] Write body" in resumed
    assert "## Current todos" not in _system_text(model.prompts[4])


def test_v2_todos_block_survives_an_exhausted_tool_budget(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            _todo_call("todo-1", ("Gather facts", "in_progress"), ("Write summary", "pending")),
            AIMessage(
                content="",
                tool_calls=[{"id": "lookup-1", "name": "lookup", "args": {"name": "focus"}}],
            ),
            AIMessage(content="Answer from the gathered fact."),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path, agent_max_tool_rounds=2)

    result = _invoke(graph, _ask("Summarize the project"), "thread-todos-budget")

    assert model.bound_tool_names[-1] == []
    last_prompt = _system_text(model.prompts[-1])
    assert "tool budget for this turn is used up" in last_prompt
    assert "todo_write:" not in last_prompt
    assert (
        "## Current todos\n1. [in_progress] Gather facts\n2. [pending] Write summary"
    ) in last_prompt
    assert result.value["messages"][-1].content == "Answer from the gathered fact."
    assert result.value["plan_meta"]["tool_budget_exhausted"] is True


def test_v2_todo_write_does_not_change_the_shared_registry(monkeypatch, tmp_path):
    registry = ToolRegistry(tools=(lookup,))
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: _ScriptedModel([AIMessage(content="hi")]),
    )

    build_graph(
        settings=Settings(),
        checkpointer=PersistentInMemorySaver(tmp_path / "checkpoints.pkl"),
        memory_retriever=MemoryRetriever(store=None),
        memory_extractor=MemoryExtractor(mode="off"),
        tool_registry=registry,
    )

    assert set(registry.by_name) == {"lookup"}


def test_todo_rule_only_when_tool_is_available():
    assert "todo_write" in operating_note(["lookup", "todo_write"], tool_budget_exhausted=False)
    assert "todo_write" not in operating_note(["lookup"], tool_budget_exhausted=False)


def test_todo_write_runtime_metadata_is_cheap_and_unguarded():
    runtime = ToolRuntimeMeta.from_tool(build_todo_write_tool())

    assert not runtime.side_effect
    assert not runtime.cacheable
    assert not runtime.requires_approval
    assert runtime.validator is normalize_todos


def test_normalize_todos_collapses_whitespace_and_allows_clearing():
    assert normalize_todos({"todos": [{"content": "  Run   tests ", "status": "pending"}]}) == [
        {"content": "Run tests", "status": "pending"}
    ]
    assert normalize_todos({"todos": []}) == []


@pytest.mark.parametrize(
    ("todos", "message"),
    [
        (None, "must be a list"),
        ([{"content": "   ", "status": "pending"}], "non-empty content"),
        ([{"content": "Ship", "status": "done"}], "status must be"),
        ([{"content": "x" * 201, "status": "pending"}], "longer than"),
        ([{"content": f"step {i}", "status": "pending"} for i in range(MAX_TODOS + 1)], "at most"),
        (
            [{"content": "a", "status": "in_progress"}, {"content": "b", "status": "in_progress"}],
            "at most one in progress",
        ),
    ],
)
def test_normalize_todos_rejects_invalid_lists(todos, message):
    with pytest.raises(ValueError, match=message):
        normalize_todos({"todos": todos})
