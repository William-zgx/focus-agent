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


def _tool_query(text: str, *, default: str = "agent governance") -> str:
    text = " ".join(text.strip().split())
    return text or default


def _agent_governance_script(messages: list[Any], allow_tools: bool) -> AIMessage:
    user_text = _latest_user_text(messages)
    lowered = user_text.casefold()
    if "web_search/web_fetch" in user_text:
        return AIMessage(content="Tool Router should deny web_search and web_fetch for workspace lookup.")
    if "不要联网" in user_text:
        return AIMessage(content="LangGraph ToolNode can be summarized without live tools when no-network is explicit.")
    if "plan:" in lowered or "方案大纲" in user_text:
        return AIMessage(content="工具调用优化方案 outline: intent, exposure, guardrail, telemetry.")
    if "branch-local memory" in user_text:
        return AIMessage(content="branch-local memory should become an approved finding only after an approved merge.")
    if "critic" in user_text:
        return AIMessage(content="critic workspace write tools are denied so review cannot mutate artifacts directly.")
    if "直接回复" in user_text:
        return AIMessage(content="通用 Agent 工具调用优化能减少误触发、降低成本，并提升结果的可验证性。")
    mixed_readonly = "Tavily" in user_text and "web_search" in user_text
    if mixed_readonly:
        if allow_tools and not _has_tool_call(messages, "search_code"):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-agent-governance-search",
                        "name": "search_code",
                        "args": {"query": "web_search implementation"},
                    }
                ],
            )
        if allow_tools and not _has_tool_call(messages, "web_search"):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-agent-governance-web",
                        "name": "web_search",
                        "args": {"query": "latest Tavily API documentation"},
                    }
                ],
            )
        return AIMessage(content="对比完成：workspace web_search implementation and latest Tavily docs.")
    if "ToolRoutePlan" in user_text or "ToolIntentPlan" in user_text:
        if allow_tools and not _has_tool_call(messages, "search_code"):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-agent-governance-search",
                        "name": "search_code",
                        "args": {
                            "query": "class ToolIntentPlan"
                            if "ToolIntentPlan" in user_text
                            else "class ToolRoutePlan"
                        },
                    }
                ],
            )
        if "ToolIntentPlan" in user_text:
            return AIMessage(content="ToolIntentPlan is defined in src/focus_agent/capabilities/tool_router.py.")
        return AIMessage(content="ToolRoutePlan is defined in src/focus_agent/capabilities/tool_router.py.")
    wants_web = any(
        marker in lowered
        for marker in (
            "memory in the age of ai agents",
            "openai agents sdk",
            "aapl",
            "arxiv",
        )
    ) or "天气" in user_text
    if wants_web:
        if allow_tools and not _has_tool_call(messages, "web_search"):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-agent-governance-web",
                        "name": "web_search",
                        "args": {"query": _tool_query(user_text)},
                    }
                ],
            )
        if "AAPL" in user_text:
            return AIMessage(content="AAPL 股价需要 live web source 才能确认。")
        if "天气" in user_text:
            return AIMessage(content="北京天气需要 weather/source style live web lookup.")
        return AIMessage(content="Found arXiv/PDF or Agents SDK tools results via web_search.")
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


@langchain_tool
def web_search(query: str = "") -> str:  # type: ignore[no-untyped-def]
    """Fake live web search for agent governance eval tests."""
    return '{"query": "' + query + '", "results": [{"title": "fixture", "url": "https://example.test"}]}'


def test_agent_governance_dataset_covers_memory_and_tool_router_cases():
    cases = {case.id: case for case in load_dataset(DATASET_PATH)}

    assert {
        "gt_agent_governance_no_web_workspace_lookup",
        "gt_agent_governance_memory_branch_local_until_merge",
        "gt_agent_governance_critic_no_workspace_write",
        "gt_agent_governance_skill_scout_registry",
        "gt_tool_intent_research_prefix_arxiv_first_web",
        "gt_tool_intent_research_skill_web_default",
        "gt_tool_intent_no_tool_overrides_research",
        "gt_tool_intent_plan_skill_no_tools",
        "gt_tool_intent_review_workspace_only",
        "gt_tool_intent_workspace_symbol_lookup_first_search",
        "gt_tool_intent_live_weather_uses_web",
        "gt_tool_intent_live_stock_uses_web",
        "gt_tool_intent_mixed_readonly_no_write",
        "gt_tool_intent_direct_writing_no_tools",
    } <= set(cases)
    assert "web_search" in cases["gt_agent_governance_no_web_workspace_lookup"].expected["must_not_call_tools"]
    assert "write_text_artifact" in cases["gt_agent_governance_critic_no_workspace_write"].expected["must_not_call_tools"]
    assert len(cases) >= 10
    assert cases["gt_tool_intent_research_prefix_arxiv_first_web"].expected["must_call_tools_any_order"] == ["web_search"]
    assert "search_code" in cases["gt_tool_intent_review_workspace_only"].expected["must_call_tools_any_order"]


@pytest.mark.parametrize("case", load_dataset(DATASET_PATH), ids=lambda case: case.id)
def test_agent_governance_suite_cases_run_without_external_api(case, eval_runtime_factory):
    runtime = eval_runtime_factory(script=_agent_governance_script, tools=[search_code, web_search])

    result = run_case(case, runtime=runtime)

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
