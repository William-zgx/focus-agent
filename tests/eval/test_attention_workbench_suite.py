from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from focus_agent.core.attention import AttentionCursor, AttentionEvidence
from focus_agent.eval.attention import ATTENTION_EVALUATION_LIMITATION, evaluate_attention_workbench
from focus_agent.services.attention import build_attention_snapshot


def _state(case_id: str) -> dict:
    return {
        "thread_id": case_id,
        "messages": [
            {"id": "m1", "type": "human", "content": "Investigate focus"},
            {"id": "m2", "type": "ai", "content": "Initial answer"},
        ],
        "tool_outcomes": [
            {"outcome_id": "outcome-1", "tool_name": "search", "status": "succeeded"}
        ],
        "branch_actions": [
            {
                "action_id": "action-1",
                "kind": "fork_child_branch",
                "status": "executed",
                "handoff_message": "Explore focus",
            }
        ],
        "interrupts": [],
        "task_outcome": {"status": "answered"},
    }


def _cases() -> list[dict]:
    ordinary = _state("ordinary")
    failure = _state("failure")
    failure["task_outcome"] = {"status": "failed"}
    pending = _state("pending")
    pending["branch_actions"][0]["status"] = "pending"
    recovered = _state("recovered")
    recovered["tool_outcomes"].append({"outcome_id": "recovered-failure", "status": "failed"})
    resumed = _state("resumed")
    resumed["branch_meta"] = {"fork_brief": {"goal": "Resume branch focus"}}
    resumed["messages"].append({"id": "m3", "type": "ai", "content": "New answer"})
    resumed["tool_outcomes"].append({"outcome_id": "outcome-2", "status": "failed"})
    resumed["branch_actions"][0]["status"] = "pending"
    missing = _state("missing")
    return [
        {"id": "ordinary", "state": ordinary},
        {"id": "failure", "state": failure},
        {"id": "pending", "state": pending},
        {"id": "recovered", "state": recovered},
        {
            "id": "resumed",
            "state": resumed,
            "stored_cursor": AttentionCursor(
                last_message_id="m2",
                seen_outcome_ids=["outcome-1"],
                action_statuses={"action-1": "executed"},
            ),
        },
        {
            "id": "missing",
            "state": missing,
            "stored_cursor": AttentionCursor(last_message_id="not-present"),
            "expect_frontier_missing": True,
        },
    ]


def test_metric_math_and_deduplication():
    report = evaluate_attention_workbench([_cases()[0]])
    case = report["cases"][0]
    assert case["baseline_units"] == 4
    assert case["attention_units"] == 2
    assert case["reduction_ratio"] == 0.5
    assert case["required_source_count"] == 0
    assert case["passed"] is True
    assert "not measurements of human attention" in ATTENTION_EVALUATION_LIMITATION


def test_actionable_and_failure_sources_keep_policy_and_evidence():
    report = evaluate_attention_workbench(_cases()[1:3])
    failure, pending = report["cases"]
    assert failure["policy"] == "notify"
    assert failure["required_source_count"] == 1
    assert failure["recalled_source_count"] == 1
    assert failure["evidence_covered_source_count"] == 1
    assert pending["policy"] == "ask"
    assert pending["recalled_source_count"] == 1
    assert pending["evidence_covered_source_count"] == 1
    assert report["summary"]["passed"] is True


def test_recovered_failure_does_not_create_required_alert():
    report = evaluate_attention_workbench([_cases()[3]])
    case = report["cases"][0]
    assert case["policy"] == "quiet"
    assert case["required_source_count"] == 0
    assert case["passed"] is True


def test_unexpected_alert_fails_even_without_required_sources():
    state = _state("recovered")
    snapshot = build_attention_snapshot(thread_id="recovered", state=state, stored_cursor=None)
    noisy_snapshot = snapshot.model_copy(
        update={"policy": snapshot.policy.model_copy(update={"level": "notify"})}
    )
    with patch(
        "focus_agent.eval.attention.build_attention_snapshot",
        return_value=noisy_snapshot,
    ):
        report = evaluate_attention_workbench([{"id": "noisy", "state": state}])

    case = report["cases"][0]
    assert case["unexpected_alert"] is True
    assert case["passed"] is False
    assert report["summary"]["passed"] is False


def test_required_source_cannot_pass_with_quiet_policy():
    state = _state("pending")
    state["branch_actions"][0]["status"] = "pending"
    snapshot = build_attention_snapshot(thread_id="pending", state=state, stored_cursor=None)
    quiet_snapshot = snapshot.model_copy(
        update={
            "policy": snapshot.policy.model_copy(
                update={"level": "quiet", "reasons": snapshot.policy.reasons}
            )
        }
    )
    with patch(
        "focus_agent.eval.attention.build_attention_snapshot",
        return_value=quiet_snapshot,
    ):
        report = evaluate_attention_workbench([{"id": "quiet-pending", "state": state}])

    case = report["cases"][0]
    assert case["missing_required_alert"] is True
    assert case["missing_policy_source_ids"] == []
    assert case["passed"] is False


def test_policy_reason_does_not_cover_another_kind_with_same_id():
    state = _state("shared")
    state["branch_actions"][0].update({"action_id": "shared", "status": "pending"})
    state["interrupts"] = [{"interrupt_id": "shared"}]
    snapshot = build_attention_snapshot(thread_id="shared", state=state, stored_cursor=None)
    reasons = [
        reason for reason in snapshot.policy.reasons if reason.code == "branch_action_pending"
    ]
    with patch(
        "focus_agent.eval.attention.build_attention_snapshot",
        return_value=snapshot.model_copy(
            update={"policy": snapshot.policy.model_copy(update={"reasons": reasons})}
        ),
    ):
        report = evaluate_attention_workbench([{"id": "shared", "state": state}])

    case = report["cases"][0]
    assert case["missing_policy_source_ids"] == ["interrupt:shared"]
    assert case["passed"] is False


def test_pending_action_cannot_pass_as_notify_instead_of_ask():
    state = _state("pending")
    state["branch_actions"][0]["status"] = "pending"
    snapshot = build_attention_snapshot(thread_id="pending", state=state, stored_cursor=None)
    notify_snapshot = snapshot.model_copy(
        update={"policy": snapshot.policy.model_copy(update={"level": "notify"})}
    )
    with patch(
        "focus_agent.eval.attention.build_attention_snapshot",
        return_value=notify_snapshot,
    ):
        report = evaluate_attention_workbench([{"id": "notify-pending", "state": state}])

    case = report["cases"][0]
    assert case["required_level"] == "ask"
    assert case["policy"] == "notify"
    assert case["passed"] is False


def test_generic_thread_evidence_does_not_cover_merge_proposal():
    state = _state("merge")
    state["branch_meta"] = {"branch_status": "awaiting_merge_review"}
    state["merge_proposal"] = {"proposal_id": "merge-1", "summary": "Review"}
    snapshot = build_attention_snapshot(thread_id="merge", state=state, stored_cursor=None)
    resume = snapshot.resume.model_copy(
        update={
            "evidence": [AttentionEvidence(source_id="merge", kind="thread", thread_id="merge")]
        }
    )
    with patch(
        "focus_agent.eval.attention.build_attention_snapshot",
        return_value=snapshot.model_copy(update={"resume": resume}),
    ):
        report = evaluate_attention_workbench([{"id": "merge", "state": state}])

    case = report["cases"][0]
    assert case["uncovered_source_ids"] == ["proposal:merge"]
    assert case["passed"] is False


def test_resumed_branch_diff_and_missing_frontier_are_honest():
    report = evaluate_attention_workbench(_cases()[4:])
    resumed, missing = report["cases"]
    assert resumed["policy"] == "ask"
    assert resumed["required_source_count"] == 1
    assert resumed["evidence_covered_source_count"] == 1
    assert resumed["baseline_units"] == 6
    assert resumed["attention_units"] > 0
    assert missing["frontier_missing"] is True
    assert missing["passed"] is True


def test_frontier_expectation_mismatch_fails():
    case = _cases()[-1]
    case["expect_frontier_missing"] = False
    report = evaluate_attention_workbench([case])
    assert report["cases"][0]["passed"] is False
    assert report["summary"]["passed"] is False


def test_empty_suite_does_not_pass_vacuously():
    report = evaluate_attention_workbench([])
    assert report["summary"]["case_count"] == 0
    assert report["summary"]["passed"] is False


def test_zero_baseline_has_no_ratio():
    report = evaluate_attention_workbench([{"id": "empty", "state": {"messages": []}}])
    case = report["cases"][0]
    assert case["baseline_units"] == 0
    assert case["reduction_ratio"] is None
    assert report["summary"]["reduction_ratio"] is None


@pytest.mark.parametrize("variant", ["nested", "mapping", "interrupt", "idless", "uppercase"])
def test_state_normalization_matches_production_projection(variant):
    state = _state("normalized")
    if variant == "nested":
        state["branch_actions"][0]["status"] = "pending"
        state = {"values": state}
    elif variant == "mapping":
        state["branch_actions"][0]["status"] = "pending"
        state["branch_actions"] = {"action-1": state["branch_actions"][0]}
    elif variant == "interrupt":
        state["branch_actions"] = []
        state["__interrupt__"] = [{"interrupt_id": "approval-1"}]
        state.pop("interrupts")
    elif variant == "idless":
        state["branch_actions"][0].pop("action_id")
        state["branch_actions"][0]["status"] = "pending"
    else:
        state["branch_meta"] = {"branch_status": "AWAITING_MERGE_REVIEW"}
        state["merge_proposal"] = {"proposal_id": "merge-1", "summary": "Review"}

    report = evaluate_attention_workbench([{"id": "normalized", "state": state}])
    case = report["cases"][0]
    assert case["policy"] == "ask"
    assert case["required_source_count"] == 1
    assert case["unexpected_alert"] is False
    assert case["passed"] is True
    assert case["baseline_units"] > 0


def test_handoff_timeout_has_required_notify_and_evidence():
    state = _state("handoff")
    state["branch_decision_summary"] = {
        "latest_decision": {
            "decision_id": "decision-1",
            "error": "",
            "metadata": {"handoff_run_id": "run-1", "handoff_run_status": "timeout"},
        }
    }
    report = evaluate_attention_workbench([{"id": "handoff", "state": state}])
    case = report["cases"][0]
    assert case["policy"] == "notify"
    assert case["required_level"] == "notify"
    assert case["required_source_count"] == 1
    assert case["recalled_source_count"] == 1
    assert case["evidence_covered_source_count"] == 1
    assert case["passed"] is True


def test_tool_call_id_interrupt_uses_stable_identity():
    state = _state("tool-call-interrupt")
    state["interrupts"] = [{"tool_call_id": "tc1"}]
    report = evaluate_attention_workbench([{"id": "tool-call-interrupt", "state": state}])
    case = report["cases"][0]
    assert case["required_source_count"] == 1
    assert case["missing_source_ids"] == []
    assert case["uncovered_source_ids"] == []
    assert case["passed"] is True


def test_representative_suite_summary():
    report = evaluate_attention_workbench(_cases())
    summary = report["summary"]
    assert summary["case_count"] == 6
    assert summary["required_source_count"] == 3
    assert summary["recalled_source_count"] == 3
    assert summary["evidence_covered_source_count"] == 3
    assert summary["passed"] is True
    assert summary["baseline_units"] > summary["attention_units"]
    assert 0 < summary["reduction_ratio"] < 1
    assert json.loads(json.dumps(report)) == report


def test_main_returns_nonzero_when_suite_fails():
    with patch(
        "tests.eval.test_attention_workbench_suite.evaluate_attention_workbench",
        return_value={"summary": {"passed": False}},
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1


def main() -> None:
    report = evaluate_attention_workbench(_cases())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["summary"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
