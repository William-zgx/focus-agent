from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest
from langchain.messages import AIMessage, HumanMessage

from focus_agent.eval.handoff import (
    HANDOFF_ARMS,
    HANDOFF_EVALUATION_LIMITATION,
    HandoffEffectJournal,
    _ModelCallRecorder,
    project_handoff_arm,
    run_handoff_arm,
    summarize_handoff_results,
    synthetic_handoff_cases,
)


def _tool_call(operation_id: str, version: str, call_id: str = "eval-call") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "id": call_id,
                "name": "record_operation",
                "args": {"operation_id": operation_id, "execution_version": version},
                "type": "tool_call",
            }
        ],
    )


def _correct_script(case_id: str):
    tool_emitted = False

    def script(_messages, allow_tools):
        nonlocal tool_emitted
        if case_id == "completed-update":
            return AIMessage(content="update_address already completed")
        if case_id == "stale-decision":
            if allow_tools and not tool_emitted:
                tool_emitted = True
                return _tool_call("deploy_green", "v2")
            return AIMessage(content="deploy_green")
        if allow_tools and not tool_emitted:
            tool_emitted = True
            return _tool_call("publish_report", "v2")
        return AIMessage(content="publish_report@v2")

    return script


def test_arm_projection_is_derived_from_one_episode_without_window_collisions():
    for case in synthetic_handoff_cases():
        projections = {arm: project_handoff_arm(case, arm) for arm in HANDOFF_ARMS}
        recent = projections["recent"].eval_case.input["initial_state"]
        full = projections["full_history"].eval_case.input["initial_state"]
        assert projections["recent"].message_count < projections["full_history"].message_count
        assert recent["messages"][-1].content == case.continuation
        assert full["messages"][-1].content == case.continuation
        assert "context_compaction" not in recent
        assert recent["context_budget"]["recent_message_limit"] == case.recent_message_limit
        assert full["context_budget"]["recent_message_limit"] == 64
        assert recent["rolling_summary"] == ""
        assert full["rolling_summary"] == ""
        assert (
            projections["narrative"].summary_sha256 != projections["resume_packet"].summary_sha256
        )


def test_model_prompt_contains_the_intended_arm_history_and_summary(eval_runtime_factory):
    case = synthetic_handoff_cases()[0]
    for arm in HANDOFF_ARMS:
        prompts = []
        correct = _correct_script(case.id)

        def capture(messages, allow_tools, prompts=prompts, correct=correct):
            prompts.append("\n".join(str(message.content) for message in messages))
            return correct(messages, allow_tools)

        projection = project_handoff_arm(case, arm)
        result = run_handoff_arm(
            case,
            arm,
            runtime=eval_runtime_factory(script=capture),
        )
        prompt = "\n".join(prompts)
        summary = projection.eval_case.input["initial_state"]["rolling_summary"]
        assert result.error is None
        assert case.continuation in prompt
        if summary:
            assert summary in prompt
        if arm == "full_history":
            assert "Apply update_address exactly once at v1." in prompt
        elif arm == "recent":
            assert "Apply update_address exactly once at v1." not in prompt


def test_projection_characterizes_resume_completed_operation_and_version_gaps():
    completed, decision, version = synthetic_handoff_cases()
    recent = project_handoff_arm(completed, "recent").eval_case.input["initial_state"]
    full = project_handoff_arm(completed, "full_history").eval_case.input["initial_state"]
    resume = project_handoff_arm(completed, "resume_packet").eval_case.input["initial_state"]
    assert "completed-1" not in {message.id for message in recent["messages"]}
    assert "completed-1" in {message.id for message in full["messages"]}
    assert "update_address" not in resume["rolling_summary"]
    assert set(project_handoff_arm(completed, "resume_packet").missing_state_markers) == {
        "update_address",
        "v1",
        "succeeded",
    }

    decision_resume = project_handoff_arm(decision, "resume_packet").eval_case.input[
        "initial_state"
    ]
    assert "deploy_green" in decision_resume["rolling_summary"]
    assert not project_handoff_arm(decision, "resume_packet").missing_state_markers

    version_resume = project_handoff_arm(version, "resume_packet").eval_case.input["initial_state"]
    assert "publish_report@v2" not in version_resume["rolling_summary"]
    assert "v2" in project_handoff_arm(version, "resume_packet").missing_state_markers


def test_oversized_full_history_fails_loudly_instead_of_becoming_recent():
    case = synthetic_handoff_cases()[0]
    case.canonical_state["messages"].extend(case.canonical_state["messages"] * 8)
    with pytest.raises(ValueError, match="truncated its seeded history"):
        project_handoff_arm(case, "full_history")


def test_full_history_token_truncation_also_fails_loudly():
    case = synthetic_handoff_cases()[0]
    case.canonical_state["messages"] = [
        HumanMessage(content="early turn", id="oversized-early-user"),
        AIMessage(content="x " * 250000, id="oversized-early"),
        HumanMessage(content="later turn", id="later-user"),
        AIMessage(content="later answer", id="later-ai"),
    ]
    with pytest.raises(ValueError, match="truncated its seeded history"):
        project_handoff_arm(case, "full_history")


def test_recording_model_preserves_unbound_invoke():
    class Model:
        def with_config(self, _config):
            return self

        def invoke(self, _messages):
            return AIMessage(content="no-tool response")

    recorder = _ModelCallRecorder(lambda *_args, **_kwargs: Model())
    response = recorder().with_config({}).invoke([HumanMessage(content="continue")])

    assert response.content == "no-tool response"
    assert recorder.responses[-1].content == "no-tool response"


def test_cli_rejects_unknown_case_ids(monkeypatch, tmp_path):
    script_path = Path(__file__).parents[2] / "scripts" / "handoff_continuity_eval.py"
    monkeypatch.syspath_prepend(str(script_path.parent))
    script = runpy.run_path(str(script_path))
    monkeypatch.setattr(
        "sys.argv",
        [
            "handoff_continuity_eval.py",
            "--model",
            "unused",
            "--cases",
            "completed-update,unknown-case",
            "--report-json",
            str(tmp_path / "report.json"),
        ],
    )
    with pytest.raises(SystemExit) as exit_info:
        script["main"]()
    assert exit_info.value.code == 2


@pytest.mark.parametrize("case", synthetic_handoff_cases(), ids=lambda case: case.id)
def test_correct_script_passes_exactly_when_required_state_is_present(case, eval_runtime_factory):
    results = [
        run_handoff_arm(
            case,
            arm,
            runtime=eval_runtime_factory(script=_correct_script(case.id)),
        )
        for arm in HANDOFF_ARMS
    ]

    expected = [not project_handoff_arm(case, arm).missing_state_markers for arm in HANDOFF_ARMS]
    assert [result.passed for result in results] == expected, [
        (result.case_id, [verdict.reasoning for verdict in result.verdicts]) for result in results
    ]
    assert all(
        bool(result.metrics["handoff_missing_state_markers"]) == (not passed)
        for result, passed in zip(results, expected, strict=True)
    )
    report = summarize_handoff_results(results)
    assert report["passed"] is False
    assert report["case_count"] == 4
    assert "not production Resume Packet prompt integration" in HANDOFF_EVALUATION_LIMITATION


def test_repeating_completed_operation_fails_even_with_safe_final_answer(eval_runtime_factory):
    case = synthetic_handoff_cases()[0]
    tool_emitted = False

    def repeat(_messages, allow_tools):
        nonlocal tool_emitted
        if allow_tools and not tool_emitted:
            tool_emitted = True
            return _tool_call("update_address", "v1")
        return AIMessage(content="update_address already completed")

    result = run_handoff_arm(
        case,
        "recent",
        runtime=eval_runtime_factory(script=repeat),
    )
    assert result.passed is False
    assert result.metrics["handoff_repeated_completed_attempt_count"] == 1
    assert result.metrics["handoff_attempts"][0]["operation_id"] == "update_address"


def test_stale_decision_and_old_version_attempts_are_not_hidden_by_tool_ack(eval_runtime_factory):
    _, decision, version = synthetic_handoff_cases()

    tool_emitted = False

    def stale(_messages, allow_tools):
        nonlocal tool_emitted
        if allow_tools and not tool_emitted:
            tool_emitted = True
            return _tool_call("deploy_blue", "v1")
        return AIMessage(content="deploy_green")

    stale_result = run_handoff_arm(
        decision,
        "narrative",
        runtime=eval_runtime_factory(script=stale),
    )
    assert stale_result.passed is False
    assert stale_result.metrics["handoff_stale_decision_attempt_count"] == 1
    assert stale_result.metrics["handoff_superseded_version_attempt_count"] == 1
    assert stale_result.metrics["handoff_effects"][0]["violations"]

    tool_emitted = False

    def old_version(_messages, allow_tools):
        nonlocal tool_emitted
        if allow_tools and not tool_emitted:
            tool_emitted = True
            return _tool_call("publish_report", "v1")
        return AIMessage(content="publish_report@v2")

    version_result = run_handoff_arm(
        version,
        "resume_packet",
        runtime=eval_runtime_factory(script=old_version),
    )
    assert version_result.passed is False
    assert version_result.metrics["handoff_superseded_version_attempt_count"] == 1
    assert version_result.metrics["handoff_operation_count_mismatches"]


def test_same_batch_duplicate_counts_model_attempts_not_only_executed_effects(eval_runtime_factory):
    _, decision, _ = synthetic_handoff_cases()
    tool_emitted = False

    def duplicate(_messages, allow_tools):
        nonlocal tool_emitted
        if allow_tools and not tool_emitted:
            tool_emitted = True
            response = _tool_call("deploy_green", "v2", "call-1")
            response.tool_calls.append(
                {
                    "id": "call-2",
                    "name": "record_operation",
                    "args": {"operation_id": "deploy_green", "execution_version": "v2"},
                    "type": "tool_call",
                }
            )
            return response
        return AIMessage(content="deploy_green")

    result = run_handoff_arm(
        decision,
        "narrative",
        runtime=eval_runtime_factory(script=duplicate),
    )

    assert len(result.metrics["handoff_attempts"]) == 2
    assert result.metrics["handoff_operation_count_mismatches"]["deploy_green@v2"]["actual"] == 2
    assert result.passed is False


def test_effect_journal_accepts_and_labels_every_simulated_call():
    case = synthetic_handoff_cases()[0]
    journal = HandoffEffectJournal(case)
    journal.record("update_address", "v1")
    journal.record("update_address", "v1")

    assert len(journal.effects) == 2
    assert all(effect["violations"] == ["repeated_completed"] for effect in journal.effects)


def test_summary_fails_for_empty_or_failed_results(eval_runtime_factory):
    assert summarize_handoff_results([])["passed"] is False
    case = synthetic_handoff_cases()[0]
    result = run_handoff_arm(
        case,
        "recent",
        runtime=eval_runtime_factory(script=_correct_script(case.id)),
    )
    result.passed = False
    assert summarize_handoff_results([result])["passed"] is False


def main() -> int:
    results = []
    for case in synthetic_handoff_cases():
        for arm in HANDOFF_ARMS:
            # The CLI self-check exercises projections and oracle fixtures without providers.
            projection = project_handoff_arm(case, arm)
            results.append(
                {
                    "case_id": projection.eval_case.id,
                    "message_count": projection.message_count,
                    "summary_sha256": projection.summary_sha256,
                }
            )
    print(json.dumps({"projection_count": len(results), "provider_calls": 0}, indent=2))
    return 0 if len(results) == len(synthetic_handoff_cases()) * len(HANDOFF_ARMS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
