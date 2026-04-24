"""Deterministic coverage for the agent task ledger eval suite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain.messages import AIMessage, HumanMessage

from .runner import load_dataset, run_case


DATASET_PATH = Path(__file__).parent / "datasets" / "agent_task_ledger.jsonl"


def _latest_user_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _agent_task_ledger_script(messages: list[Any], allow_tools: bool) -> AIMessage:  # noqa: ARG001
    user_text = _latest_user_text(messages)
    if "legacy single-run" in user_text:
        return AIMessage(content="Agent Task Ledger is default off, so legacy single-run behavior stays unchanged.")
    if "orchestrator" in user_text and "critic" in user_text:
        return AIMessage(content="Complex tasks can produce an orchestrator, planner, executor, and critic path.")
    if "accepted artifact" in user_text:
        return AIMessage(content="Only an accepted artifact participates in final synthesis.")
    if "rejected artifact" in user_text:
        return AIMessage(content="A rejected artifact is blocked by the critic gate and skipped from final synthesis.")
    return AIMessage(content="Memory candidates, tool route evidence, and context refs remain traceable artifacts.")


def test_agent_task_ledger_dataset_covers_artifact_synthesis_and_gate():
    cases = {case.id: case for case in load_dataset(DATASET_PATH)}

    assert {
        "gt_agent_task_ledger_default_off_legacy_safe",
        "gt_agent_task_ledger_complex_role_path",
        "gt_agent_task_ledger_accepted_artifact_synthesis",
        "gt_agent_task_ledger_rejected_artifact_blocked",
        "gt_agent_task_ledger_memory_tool_context_artifacts",
    } <= set(cases)
    assert "write_text_artifact" in cases[
        "gt_agent_task_ledger_memory_tool_context_artifacts"
    ].expected["must_not_call_tools"]


@pytest.mark.parametrize("case", load_dataset(DATASET_PATH), ids=lambda case: case.id)
def test_agent_task_ledger_suite_cases_run_without_external_api(case, eval_runtime_factory):
    runtime = eval_runtime_factory(script=_agent_task_ledger_script, tools=[])

    result = run_case(case, runtime=runtime)

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
