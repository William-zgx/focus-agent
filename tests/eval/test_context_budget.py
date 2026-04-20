from __future__ import annotations

import json
from typing import Any

from langchain.messages import AIMessage, ToolMessage
from langchain.tools import tool as langchain_tool

from focus_agent.core.types import ContextBudget

from .runner import run_case
from .schema import EvalCase


def _long_history_direct_writing_script(messages: list[Any], allow_tools: bool) -> AIMessage:
    assert not allow_tools, "direct writing turn should not bind tools"
    prompt_text = "\n".join(str(getattr(message, "content", "")) for message in messages)
    assert "帮我写一段关于杨絮好处的短文" in prompt_text
    assert "Keep the current writing request authoritative." in prompt_text
    assert "OBSOLETE_HISTORY" not in prompt_text
    return AIMessage(content="杨絮随风飘散，帮助柳树传播种子，也提醒人们观察季节变化。")


def test_eval_long_history_direct_writing_stays_tool_free(eval_runtime_factory):
    user_message = "帮我写一段关于杨絮好处的短文，直接发给我。"
    case = EvalCase(
        id="budget_long_history_direct_writing_no_tools",
        tags=["smoke", "regression", "context_budget"],
        input={
            "user_message": user_message,
            "initial_state": {
                "rolling_summary": "OBSOLETE_HISTORY " * 500,
                "user_constraints": [
                    {"constraint": "Keep the current writing request authoritative."}
                ],
                "context_budget": ContextBudget(prompt_token_limit=360, chars_per_token=1),
            },
        },
        expected={
            "answer_contains_any": ["杨絮"],
            "max_tool_calls": 0,
            "must_not_call_tools": ["web_search", "web_fetch", "write_text_artifact"],
        },
        judge={"rule": True, "llm": {"enabled": False}},
    )

    result = run_case(case, runtime=eval_runtime_factory(script=_long_history_direct_writing_script))

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
    assert result.metrics["tool_calls"] == 0


@langchain_tool
def search_code(query: str = "") -> str:  # type: ignore[no-untyped-def]
    """Return a deliberately oversized structured code-search observation."""
    return json.dumps(
        {
            "query": query,
            "results": [
                {
                    "path": "src/focus_agent/core/context_policy.py",
                    "line_number": 42,
                    "line": "def assemble_context(state, mode):",
                }
            ],
            "noise": "POLLUTION" * 2000,
        },
        ensure_ascii=False,
    )


def _long_tool_output_script(messages: list[Any], allow_tools: bool) -> AIMessage:
    if allow_tools and not any(isinstance(message, ToolMessage) for message in messages):
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call-1",
                    "name": "search_code",
                    "args": {"query": "assemble_context"},
                }
            ],
        )

    tool_text = "\n".join(
        str(message.content) for message in messages if isinstance(message, ToolMessage)
    )
    if "POLLUTION" in tool_text:
        return AIMessage(content="POLLUTION leaked into the answer.")
    return AIMessage(content="Relevant hit: src/focus_agent/core/context_policy.py:42.")


def test_eval_long_tool_output_does_not_pollute_final_answer(eval_runtime_factory):
    case = EvalCase(
        id="budget_long_tool_output_no_answer_pollution",
        tags=["smoke", "regression", "context_budget", "tools"],
        input={
            "user_message": "找到仓库里 assemble_context 的定义位置。",
            "initial_state": {
                "context_budget": ContextBudget(
                    prompt_token_limit=500,
                    chars_per_token=1,
                    tool_observation_token_limit=260,
                )
            },
        },
        expected={
            "must_call_tools_any_order": ["search_code"],
            "answer_contains_all": ["context_policy.py"],
            "answer_must_not_contain": ["POLLUTION"],
            "max_tool_calls": 1,
        },
        judge={"rule": True, "llm": {"enabled": False}},
    )

    result = run_case(
        case,
        runtime=eval_runtime_factory(script=_long_tool_output_script, tools=[search_code]),
    )

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
    assert result.metrics["tool_calls"] == 1
    assert "POLLUTION" not in result.answer
    assert "POLLUTION" not in result.trajectory[0].observation
