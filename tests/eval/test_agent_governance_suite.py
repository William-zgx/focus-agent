"""Deterministic coverage for the agent governance eval suite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain.messages import AIMessage, HumanMessage
from langchain.tools import tool as langchain_tool

from .runner import load_dataset, run_case


DATASET_PATH = Path(__file__).parent / "datasets" / "agent_governance.jsonl"


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


def _agent_governance_script(messages: list[Any], allow_tools: bool) -> AIMessage:
    user_text = _latest_user_text(messages)
    if "web_search/web_fetch" in user_text:
        return AIMessage(content="Tool Router should deny web_search and web_fetch for workspace lookup.")
    if "ToolRoutePlan" in user_text:
        if allow_tools and not _has_tool_call(messages, "search_code"):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-agent-governance-search",
                        "name": "search_code",
                        "args": {"query": "class ToolRoutePlan"},
                    }
                ],
            )
        return AIMessage(content="ToolRoutePlan is defined in src/focus_agent/capabilities/tool_router.py.")
    if "branch-local memory" in user_text:
        return AIMessage(content="branch-local memory should become an approved finding only after an approved merge.")
    if "critic" in user_text:
        return AIMessage(content="critic workspace write tools are denied so review cannot mutate artifacts directly.")
    return AIMessage(content="Skill Scout uses the capability registry to select skills_list and skill_view.")


@langchain_tool
def search_code(query: str = "") -> str:  # type: ignore[no-untyped-def]
    """Fake repository search for agent governance eval tests."""
    return (
        '{"query": "'
        + query
        + '", "results": [{"path": "src/focus_agent/capabilities/tool_router.py", "line_number": 84, '
        + '"line": "class ToolRoutePlan(StateModel):"}]}'
    )


def test_agent_governance_dataset_covers_memory_and_tool_router_cases():
    cases = {case.id: case for case in load_dataset(DATASET_PATH)}

    assert {
        "gt_agent_governance_no_web_workspace_lookup",
        "gt_agent_governance_memory_branch_local_until_merge",
        "gt_agent_governance_critic_no_workspace_write",
        "gt_agent_governance_skill_scout_registry",
    } <= set(cases)
    assert "web_search" in cases["gt_agent_governance_no_web_workspace_lookup"].expected["must_not_call_tools"]
    assert "write_text_artifact" in cases["gt_agent_governance_critic_no_workspace_write"].expected["must_not_call_tools"]


@pytest.mark.parametrize("case", load_dataset(DATASET_PATH), ids=lambda case: case.id)
def test_agent_governance_suite_cases_run_without_external_api(case, eval_runtime_factory):
    runtime = eval_runtime_factory(script=_agent_governance_script, tools=[search_code])

    result = run_case(case, runtime=runtime)

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
