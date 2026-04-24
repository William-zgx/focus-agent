"""Deterministic coverage for the agent delegation eval suite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain.messages import AIMessage, HumanMessage

from .runner import load_dataset, run_case


DATASET_PATH = Path(__file__).parent / "datasets" / "agent_delegation.jsonl"


def _latest_user_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _agent_delegation_script(messages: list[Any], allow_tools: bool) -> AIMessage:  # noqa: ARG001
    user_text = _latest_user_text(messages)
    if "default off" in user_text or "legacy single-run" in user_text:
        return AIMessage(content="Agent delegation is default off, so the legacy single-run path stays unchanged.")
    if "orchestrator" in user_text:
        return AIMessage(content="Complex work can flow through orchestrator, planner, executor, and critic.")
    if "effective_model" in user_text:
        return AIMessage(content="Model Router records effective_model and fallback decisions under enforce mode.")
    return AIMessage(content="A failed delegated run can produce a self-repair preview and enter the review queue.")


def test_agent_delegation_dataset_covers_runtime_router_and_repair():
    cases = {case.id: case for case in load_dataset(DATASET_PATH)}

    assert {
        "gt_agent_delegation_default_off_direct",
        "gt_agent_delegation_complex_role_path",
        "gt_agent_delegation_model_router_fallback",
        "gt_agent_delegation_self_repair_review_queue",
    } <= set(cases)
    assert cases["gt_agent_delegation_self_repair_review_queue"].expected["must_not_call_tools"] == [
        "web_search",
        "web_fetch",
        "write_text_artifact",
    ]


@pytest.mark.parametrize("case", load_dataset(DATASET_PATH), ids=lambda case: case.id)
def test_agent_delegation_suite_cases_run_without_external_api(case, eval_runtime_factory):
    runtime = eval_runtime_factory(script=_agent_delegation_script, tools=[])

    result = run_case(case, runtime=runtime)

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
