"""Deterministic coverage for the agent architecture eval suite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain.messages import AIMessage, HumanMessage
from langchain.tools import tool as langchain_tool

from .runner import load_dataset, run_case


DATASET_PATH = Path(__file__).parent / "datasets" / "agent_arch.jsonl"


def _latest_user_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _has_tool_call(messages: list[Any], name: str) -> bool:
    return any(
        isinstance(message, AIMessage)
        and any(call.get("name") == name for call in (getattr(message, "tool_calls", None) or []))
        for message in messages
    )


def _agent_arch_script(messages: list[Any], allow_tools: bool) -> AIMessage:
    user_text = _latest_user_text(messages)
    if "selected_model" in user_text:
        if allow_tools and not _has_tool_call(messages, "search_code"):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-agent-arch-search",
                        "name": "search_code",
                        "args": {"query": "AgentState selected_model"},
                    }
                ],
            )
        return AIMessage(content="AgentState.selected_model is defined in src/focus_agent/core/state.py.")
    if "MEMORY_PREVIEW_DO_NOT_PERSIST" in user_text:
        return AIMessage(content="Owner 结论需要以当前问题为准，不读取未写入的 memory preview。")
    if "helper_model" in user_text:
        return AIMessage(content="If a role-specific model is unset, role routing should use helper_model and fallback to the main model.")
    return AIMessage(content="ReAct alternates reasoning and acting; role routing stays default off.")


@langchain_tool
def search_code(query: str = "") -> str:  # type: ignore[no-untyped-def]
    """Fake repository search for agent architecture eval tests."""
    return (
        '{"query": "'
        + query
        + '", "results": [{"path": "src/focus_agent/core/state.py", "line_number": 106, '
        + '"line": "selected_model: str"}]}'
    )


def test_agent_arch_dataset_covers_role_routing_gate_cases():
    cases = {case.id: case for case in load_dataset(DATASET_PATH)}

    assert {
        "gt_agent_role_routing_default_off_direct",
        "gt_agent_role_workspace_lookup_no_web",
        "gt_agent_role_memory_preview_no_pollution",
        "gt_agent_role_helper_model_fallback_no_external_api",
    } <= set(cases)
    assert cases["gt_agent_role_routing_default_off_direct"].input["initial_state"]["role_route_plan"]["enabled"] is False
    assert "web_search" in cases["gt_agent_role_workspace_lookup_no_web"].expected["must_not_call_tools"]
    assert "MEMORY_PREVIEW_DO_NOT_PERSIST" in cases[
        "gt_agent_role_memory_preview_no_pollution"
    ].expected["answer_must_not_contain"]
    assert "helper_model" in cases[
        "gt_agent_role_helper_model_fallback_no_external_api"
    ].expected["answer_contains_all"]


@pytest.mark.parametrize("case", load_dataset(DATASET_PATH), ids=lambda case: case.id)
def test_agent_arch_suite_cases_run_without_external_api(case, eval_runtime_factory):
    runtime = eval_runtime_factory(script=_agent_arch_script, tools=[search_code])

    result = run_case(case, runtime=runtime)

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
