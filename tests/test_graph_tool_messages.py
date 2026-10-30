import pytest
from langchain.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import ValidationError

from focus_agent.core.types import ContextBudget
from focus_agent.engine.graph_tool_messages import (
    iter_tool_results,
    tool_call_names_by_id,
    tool_message_json,
)


def _messages() -> list:
    return [
        HumanMessage(content="hi"),
        AIMessage(
            content="",
            tool_calls=[
                {"id": "a", "name": "web_search", "args": {"query": "x"}},
                {"id": "b", "name": "web_fetch", "args": {"url": "https://e.x"}},
            ],
        ),
        ToolMessage(content='{"ok": true}', tool_call_id="a"),
        ToolMessage(content="plain", tool_call_id="b"),
        ToolMessage(content="orphan", tool_call_id="missing"),
    ]


def test_tool_call_names_by_id_maps_named_calls() -> None:
    assert tool_call_names_by_id(_messages()) == {"a": "web_search", "b": "web_fetch"}


def test_iter_tool_results_pairs_results_with_preceding_calls() -> None:
    pairs = [(m.tool_call_id, name, dict(args)) for m, name, args in iter_tool_results(_messages())]

    assert pairs == [
        ("a", "web_search", {"query": "x"}),
        ("b", "web_fetch", {"url": "https://e.x"}),
        ("missing", "", {}),
    ]


def test_tool_message_json_parses_strings_and_passes_structured_content() -> None:
    assert tool_message_json(ToolMessage(content='{"a": 1}', tool_call_id="t")) == {"a": 1}
    assert tool_message_json(ToolMessage(content="not json", tool_call_id="t")) is None
    blocks = [{"type": "text", "text": "x"}]
    assert tool_message_json(ToolMessage(content=blocks, tool_call_id="t")) == blocks


def test_context_budget_coerce() -> None:
    budget = ContextBudget(prompt_token_limit=1000)

    assert ContextBudget.coerce(budget) is budget
    assert ContextBudget.coerce({"prompt_token_limit": 2000}).prompt_token_limit == 2000
    assert ContextBudget.coerce(None) == ContextBudget()
    with pytest.raises(ValidationError):
        ContextBudget.coerce({"prompt_token_limit": 0})
