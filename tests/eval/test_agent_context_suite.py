"""Deterministic coverage for the agent context engineering eval suite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain.messages import AIMessage, HumanMessage

from .runner import load_dataset, run_case


DATASET_PATH = Path(__file__).parent / "datasets" / "agent_context.jsonl"


def _latest_user_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _agent_context_script(messages: list[Any], allow_tools: bool) -> AIMessage:  # noqa: ARG001
    user_text = _latest_user_text(messages)
    if "default off" in user_text:
        return AIMessage(content="Context Engineering v2 is default off, so the legacy prompt path stays unchanged.")
    if "tool observation" in user_text:
        return AIMessage(content="Long tool observation content becomes an artifact reference instead of raw prompt bloat.")
    if "Critic role" in user_text:
        return AIMessage(content="The critic role view uses acceptance criteria and artifact evidence with a smaller budget.")
    return AIMessage(content="When context is over budget, semantic blocks are summarized and refs are kept.")


def test_agent_context_dataset_covers_budget_artifact_and_role_views():
    cases = {case.id: case for case in load_dataset(DATASET_PATH)}

    assert {
        "gt_agent_context_default_off_legacy_safe",
        "gt_agent_context_long_observation_artifact_ref",
        "gt_agent_context_role_view_critic_budget",
        "gt_agent_context_over_budget_compression",
    } <= set(cases)
    assert "write_text_artifact" in cases["gt_agent_context_role_view_critic_budget"].expected["must_not_call_tools"]


@pytest.mark.parametrize("case", load_dataset(DATASET_PATH), ids=lambda case: case.id)
def test_agent_context_suite_cases_run_without_external_api(case, eval_runtime_factory):
    runtime = eval_runtime_factory(script=_agent_context_script, tools=[])

    result = run_case(case, runtime=runtime)

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
