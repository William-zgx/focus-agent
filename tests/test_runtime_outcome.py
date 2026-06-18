from __future__ import annotations

import json

from langchain.messages import AIMessage, ToolMessage

from focus_agent.core.runtime_outcome import (
    build_task_outcome,
    build_tool_outcomes_from_messages,
    tool_outcome_from_message,
)


def test_tool_outcome_classifies_approval_and_validation_as_blocked():
    approval = tool_outcome_from_message(
        ToolMessage(
            content="approval denied",
            tool_call_id="approval-1",
            artifact={"runtime": {"tool_approval_denied": True}},
        ),
        call_names_by_id={"approval-1": "run_workspace_command"},
    )
    validation = tool_outcome_from_message(
        ToolMessage(
            content="invalid args",
            tool_call_id="validation-1",
            artifact={"runtime": {"parameter_validation_error": "missing command"}},
        ),
        call_names_by_id={"validation-1": "run_workspace_command"},
    )

    assert approval["status"] == "blocked"
    assert approval["error_category"] == "approval"
    assert approval["retryable"] is False
    assert validation["status"] == "blocked"
    assert validation["error_category"] == "validation"
    assert validation["retryable"] is False


def test_tool_outcome_classifies_stdout_business_error_as_failed():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "skill-1",
                    "name": "run_workspace_command",
                    "args": {"command": ["python3", "scripts/stocks_client.py"]},
                }
            ],
        ),
        ToolMessage(
            content=json.dumps(
                {
                    "exit_code": 0,
                    "stdout": json.dumps(
                        {
                            "status": "error",
                            "message": "symbol unsupported",
                        }
                    ),
                }
            ),
            tool_call_id="skill-1",
        ),
    ]

    outcome = build_tool_outcomes_from_messages(messages)[0]

    assert outcome["tool_name"] == "run_workspace_command"
    assert outcome["status"] == "failed"
    assert outcome["error_category"] == "business_error"
    assert outcome["error_message"] == "symbol unsupported"


def test_tool_outcome_attempt_index_is_per_tool_call_id():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"id": "quote-1", "name": "run_workspace_command", "args": {}},
                {"id": "history-1", "name": "run_workspace_command", "args": {}},
            ],
        ),
        ToolMessage(
            content=json.dumps({"status": "completed", "exit_code": 0}),
            tool_call_id="quote-1",
        ),
        ToolMessage(
            content=json.dumps({"error": "Failed to fetch history for 003035.SZ"}),
            tool_call_id="history-1",
        ),
    ]

    first_pass = build_tool_outcomes_from_messages(messages)
    retry = tool_outcome_from_message(
        ToolMessage(
            content=json.dumps({"status": "completed", "exit_code": 0}),
            tool_call_id="history-1",
        ),
        call_names_by_id={"history-1": "run_workspace_command"},
        prior_outcomes=first_pass,
    )

    assert [item["attempt_index"] for item in first_pass] == [1, 1]
    assert first_pass[1]["retryable"] is True
    assert retry["attempt_index"] == 2
    assert retry["status"] == "recovered"
    assert retry["recovery_of_tool_call_id"] == "history-1"


def test_tool_outcome_carries_turn_scope_metadata():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"id": "lookup-1", "name": "run_workspace_command", "args": {}},
            ],
        ),
        ToolMessage(
            content=json.dumps({"status": "completed", "exit_code": 0}),
            tool_call_id="lookup-1",
        ),
    ]

    outcome = build_tool_outcomes_from_messages(
        messages,
        turn_id="turn-7",
        human_turn_index=7,
    )[0]

    assert outcome["turn_id"] == "turn-7"
    assert outcome["human_turn_index"] == 7
    assert outcome["contract_satisfied"] is True
    assert outcome["degraded_reason"] == ""


def test_tool_outcome_marks_fallback_success_as_recovered():
    failed = {
        "outcome_id": "search-1:1",
        "tool_call_id": "search-1",
        "tool_name": "web_search",
        "status": "failed",
    }
    recovered = tool_outcome_from_message(
        ToolMessage(
            content=json.dumps({"results": [{"title": "fallback result"}]}),
            tool_call_id="search-2",
            artifact={
                "runtime": {
                    "fallback_used": True,
                    "fallback_group": "web_search",
                    "duration_ms": 42,
                }
            },
        ),
        call_names_by_id={"search-2": "web_search"},
        prior_outcomes=[failed],
    )

    assert recovered["status"] == "recovered"
    assert recovered["fallback_used"] is True
    assert recovered["fallback_group"] == "web_search"
    assert recovered["recovery_of_tool_call_id"] == "search-1"
    assert recovered["duration_ms"] == 42


def test_task_outcome_filters_tool_outcomes_to_current_turn():
    previous_turn_failure = {
        "outcome_id": "old:1",
        "tool_call_id": "old",
        "tool_name": "run_workspace_command",
        "status": "failed",
        "error_message": "old failure",
        "turn_id": "turn-1",
        "human_turn_index": 1,
    }
    current_turn_success = {
        "outcome_id": "new:1",
        "tool_call_id": "new",
        "tool_name": "run_workspace_command",
        "status": "succeeded",
        "turn_id": "turn-2",
        "human_turn_index": 2,
    }

    outcome = build_task_outcome(
        user_goal="answer current question",
        execution_contract={"status": "not_required", "policy": "direct_answer"},
        answer_verification={"status": "not_required"},
        tool_outcomes=[previous_turn_failure, current_turn_success],
        final_answer="current answer",
        current_turn_id="turn-2",
        current_human_turn_index=2,
    )

    assert outcome["status"] == "answered"
    assert outcome["tool_outcome_ids"] == ["new:1"]
    assert outcome["warnings"] == []


def test_blocked_tool_outcome_blocks_task_without_contract_block():
    outcome = build_task_outcome(
        user_goal="run a command",
        execution_contract={"status": "not_required", "policy": "direct_answer"},
        answer_verification={"status": "not_required"},
        tool_outcomes=[
            {
                "outcome_id": "approval:1",
                "tool_call_id": "approval",
                "tool_name": "run_workspace_command",
                "status": "blocked",
                "error_category": "approval",
                "error_message": "approval denied",
            }
        ],
        final_answer="不能继续。",
    )

    assert outcome["status"] == "blocked"
    assert outcome["answer_basis"] == "blocked"
    assert outcome["degradation_reason"] == "approval denied"


def test_task_outcome_distinguishes_answered_degraded_and_blocked():
    answered = build_task_outcome(
        user_goal="summarize evidence",
        execution_contract={"status": "satisfied", "policy": "live_web_research"},
        answer_verification={"status": "verified"},
        evidence_ledger=[{"source": "web_search"}],
        final_answer="Answer with evidence.",
    )
    degraded = build_task_outcome(
        user_goal="quote stock movement",
        execution_contract={"status": "missing_required_tools", "policy": "skill_execution"},
        answer_verification={
            "status": "unsupported",
            "repair_action": "fallback_to_tool_results",
        },
        evidence_ledger=[],
        tool_outcomes=[
            {
                "outcome_id": "skill-1:1",
                "tool_name": "run_workspace_command",
                "status": "failed",
                "error_message": "symbol unsupported",
            }
        ],
        final_answer="只能给出保守结论。",
    )
    blocked = build_task_outcome(
        user_goal="delete data",
        execution_contract={
            "status": "blocked",
            "policy": "execution",
            "blocked_reason": "tool approval denied",
        },
        answer_verification={"status": "not_required"},
        final_answer="不能继续。",
    )

    assert answered["status"] == "answered"
    assert answered["answer_basis"] == "verified_evidence"
    assert degraded["status"] == "degraded_answer"
    assert degraded["answer_basis"] == "tool_failure"
    assert degraded["degradation_reason"] == "symbol unsupported"
    assert blocked["status"] == "blocked"
    assert blocked["answer_basis"] == "blocked"
    assert blocked["degradation_reason"] == "tool approval denied"
