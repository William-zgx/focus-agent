"""Deterministic coverage for the Agent Team Workbench eval suite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from langchain.messages import AIMessage, HumanMessage

from .runner import load_dataset, run_case


DATASET_PATH = Path(__file__).parent / "datasets" / "agent_team.jsonl"


def _latest_user_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""


def _agent_team_script(messages: list[Any], allow_tools: bool) -> AIMessage:  # noqa: ARG001
    user_text = _latest_user_text(messages)
    if "固定角色" in user_text or "拆分复杂开发任务" in user_text:
        return AIMessage(
            content=(
                "Agent Team Workbench decomposes MVP work into planner, backend_executor, "
                "frontend_executor, test_engineer, reviewer, and verifier tasks."
            )
        )
    if "自己的 branch" in user_text or "rejected/local finding" in user_text:
        return AIMessage(
            content=(
                "Each task stays isolated in its own branch; local exploration remains branch-local, "
                "and a rejected task is not promoted to the main thread."
            )
        )
    if "team merge bundle" in user_text or "accepted/rejected tasks" in user_text:
        return AIMessage(
            content=(
                "A quality merge bundle lists accepted_tasks, rejected_tasks, changed files, "
                "test_evidence, risk_items, open questions, and recommended_next_action."
            )
        )
    if "恢复" in user_text or "注意力焦点" in user_text:
        return AIMessage(
            content=(
                "Resume task-verifier on the verifier branch in the verification panel, keep the "
                "open risk visible, and collect the remaining verification evidence next."
            )
        )
    return AIMessage(
        content=(
            "Rejected artifact output and any memory candidate stay out of main memory until an "
            "accepted merge review explicitly promotes them."
        )
    )


def test_agent_team_dataset_covers_mvp_attention_and_merge_gates():
    cases = {case.id: case for case in load_dataset(DATASET_PATH)}

    assert {
        "gt_agent_team_role_decomposition_fixed_mvp_roles",
        "gt_agent_team_branch_task_separation_keeps_exploration_local",
        "gt_agent_team_merge_bundle_quality_has_decision_evidence_and_risks",
        "gt_agent_team_attention_continuity_resumes_selected_task_after_interruption",
        "gt_agent_team_rejected_task_outputs_do_not_pollute_main_memory",
    } <= set(cases)
    assert "attention" in cases[
        "gt_agent_team_attention_continuity_resumes_selected_task_after_interruption"
    ].tags
    assert cases[
        "gt_agent_team_rejected_task_outputs_do_not_pollute_main_memory"
    ].expected["answer_must_not_contain"] == ["SECRET_REJECTED_FINDING"]


@pytest.mark.parametrize("case", load_dataset(DATASET_PATH), ids=lambda case: case.id)
def test_agent_team_suite_cases_run_without_external_api(case, eval_runtime_factory):
    runtime = eval_runtime_factory(script=_agent_team_script, tools=[])

    result = run_case(case, runtime=runtime)

    assert result.passed, [verdict.reasoning for verdict in result.verdicts]
