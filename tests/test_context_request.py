from __future__ import annotations

import pytest
from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import tool

from focus_agent.core.context_request import build_context_request
from focus_agent.core.types import ContextBudget


@tool
def request_lookup(query: str) -> str:
    """Look up a value for the supplied query."""

    return query


def test_request_budget_accounts_for_schema_and_output_reserve() -> None:
    request = build_context_request(
        [SystemMessage(content="Rules"), HumanMessage(content="Current request")],
        budget=ContextBudget(
            prompt_token_limit=2000,
            chars_per_token=1,
            token_budget_mode="chars_fallback",
        ),
        available_tools=[request_lookup],
        output_reserve_tokens=100,
    )

    assert request.tool_schema_tokens > 0
    assert request.input_token_limit == 2000 - request.tool_schema_tokens - 100
    assert request.output_reserve_tokens == 100
    assert request.required_overflow is False
    assert request.remaining_tokens == request.input_token_limit - request.posttrim_tokens


def test_request_schema_estimate_includes_tool_description() -> None:
    budget = ContextBudget(
        prompt_token_limit=10000,
        chars_per_token=1,
        token_budget_mode="chars_fallback",
    )
    short = build_context_request(
        [HumanMessage(content="Current request")],
        budget=budget,
        available_tools=[
            {
                "name": "lookup",
                "description": "short",
                "input_schema": {"type": "object"},
            }
        ],
        output_reserve_tokens=0,
    )
    verbose = build_context_request(
        [HumanMessage(content="Current request")],
        budget=budget,
        available_tools=[
            {
                "name": "lookup",
                "description": "long description " * 30,
                "input_schema": {"type": "object"},
            }
        ],
        output_reserve_tokens=0,
    )

    assert verbose.tool_schema_tokens > short.tool_schema_tokens


def test_request_preserves_required_rules_user_and_tool_pair_when_over_budget() -> None:
    request = build_context_request(
        [
            SystemMessage(content="Required rules " * 100),
            HumanMessage(content="old context"),
            HumanMessage(content="keep this current user request"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call-1", "name": "request_lookup", "args": {}}],
            ),
            ToolMessage(content="tool result " * 100, tool_call_id="call-1"),
        ],
        budget=ContextBudget(
            prompt_token_limit=50,
            chars_per_token=1,
            token_budget_mode="chars_fallback",
        ),
        preserve_required_messages=True,
    )

    assert request.messages[0].content.startswith("Required rules")
    assert any(
        getattr(message, "content", "") == "keep this current user request"
        for message in request.messages
    )
    assert any(getattr(message, "tool_call_id", None) == "call-1" for message in request.messages)
    assert request.required_overflow is True


@pytest.mark.parametrize("mode", ["explore", "execute", "synthesize", "branch_review"])
def test_request_drops_optional_summary_before_required_overflow(mode: str) -> None:
    request = build_context_request(
        [
            SystemMessage(
                content=(
                    f"## Prompt mode\n- {mode}\n\n"
                    "## Constraints and goals\n"
                    "- Keep the current writing request authoritative.\n\n"
                    "## Rolling summary\n"
                    + ("obsolete summary " * 20)
                    + "\n\n## Retrieved long-term memories\n"
                    + ("obsolete memory " * 20)
                )
            ),
            HumanMessage(content="Current request"),
        ],
        budget=ContextBudget(
            prompt_token_limit=160,
            chars_per_token=1,
            token_budget_mode="chars_fallback",
        ),
        output_reserve_tokens=0,
    )

    rendered = "\n".join(str(message.content) for message in request.messages)

    assert "Keep the current writing request authoritative." in rendered
    assert "obsolete summary" not in rendered
    assert "obsolete memory" not in rendered
    assert request.required_overflow is False
    assert request.trimmed is True


def test_request_marks_overhead_overflow_instead_of_hiding_it_with_one_token() -> None:
    request = build_context_request(
        [HumanMessage(content="keep this")],
        budget=ContextBudget(
            prompt_token_limit=1,
            chars_per_token=1,
            token_budget_mode="chars_fallback",
        ),
        available_tools=[request_lookup],
        output_reserve_tokens=100,
    )

    assert request.input_token_limit == 0
    assert request.required_overflow is True
    assert request.remaining_tokens == 0


def test_request_without_tools_still_marks_provider_framing_as_estimated() -> None:
    request = build_context_request(
        [HumanMessage(content="Current request")],
        budget=ContextBudget(tokenizer_id="gpt-4o"),
    )
    assert request.counting_backend == "tiktoken"
    assert request.estimated is True


def test_protocol_repair_does_not_invoke_model_when_required_rules_overflow() -> None:
    from focus_agent.engine.graph_textual_tool_call_repair import (
        _repair_textual_tool_call_response,
    )

    def unexpected_model(*_args):
        raise AssertionError("an overflowing repair must not invoke a model")

    markup = '<tool_call name="request_lookup">{}</tool_call>'
    result = _repair_textual_tool_call_response(
        response=AIMessage(content=markup),
        prompt_messages=[
            SystemMessage(content="Required rules " * 100),
            HumanMessage(content="Current request"),
        ],
        context_budget=ContextBudget(prompt_token_limit=100, output_token_reserve=0),
        selected_model="gpt-4o",
        selected_thinking_mode="off",
        available_tools=[request_lookup],
        model_for=unexpected_model,
        model_with_tools_for=unexpected_model,
    )
    assert not result.tool_calls
    assert result.content != markup
