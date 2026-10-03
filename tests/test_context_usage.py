from __future__ import annotations

import pytest
from langchain.messages import HumanMessage
from langchain.tools import tool

from focus_agent.context_usage import build_context_usage
from focus_agent.core import context_token_counting
from focus_agent.core.types import ContextBudget


@tool
def context_usage_lookup(query: str) -> str:
    """Look up a value for the supplied query."""

    return query


def test_context_usage_reports_tokenizer_fallback_and_drift_risk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_tiktoken(_name: str):
        raise ImportError("tiktoken unavailable")

    context_token_counting._resolve_tokenizer_detail.cache_clear()
    monkeypatch.setattr(context_token_counting.importlib, "import_module", missing_tiktoken)

    usage = build_context_usage(
        {
            "messages": [HumanMessage(content="Keep the Postgres migration path.")],
            "context_budget": ContextBudget(
                prompt_token_limit=1000,
                token_budget_mode="tokenizer_first",
                tokenizer_id="fake-model",
            ),
            "context_compaction": {
                "context_compaction_drift_report": {
                    "overall_drift": 0.5,
                }
            },
        }
    )

    payload = usage.to_dict()

    assert payload["counting_backend"] == "chars_fallback"
    assert payload["tokenizer_id"] == "fake-model"
    assert payload["estimated"] is True
    assert payload["drift_risk"] == "high"


def test_context_usage_exposes_final_request_budget_diagnostics() -> None:
    usage = build_context_usage(
        {
            "messages": [HumanMessage(content="Keep the migration path.")],
            "context_budget": ContextBudget(
                prompt_token_limit=2000,
                token_budget_mode="chars_fallback",
                chars_per_token=1,
            ),
        },
        available_tools=[context_usage_lookup],
        output_reserve_tokens=100,
    )

    payload = usage.to_dict()

    assert payload["configured_token_limit"] == 2000
    assert payload["input_token_limit"] == 2000 - payload["tool_schema_tokens"] - 100
    assert payload["tool_schema_tokens"] > 0
    assert payload["output_reserve_tokens"] == 100
    assert payload["posttrim_tokens"] == payload["used_tokens"]
    assert payload["remaining_tokens"] == max(
        0, payload["input_token_limit"] - payload["posttrim_tokens"]
    )


def test_context_usage_marks_zero_input_capacity_as_over() -> None:
    usage = build_context_usage(
        {
            "messages": [HumanMessage(content="Current request")],
            "context_budget": ContextBudget(
                prompt_token_limit=100,
                chars_per_token=1,
                token_budget_mode="chars_fallback",
            ),
        },
        output_reserve_tokens=100,
    )

    payload = usage.to_dict()

    assert payload["input_token_limit"] == 0
    assert payload["required_overflow"] is True
    assert payload["status"] == "over"
    assert payload["used_ratio"] == 1.0
