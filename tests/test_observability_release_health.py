from __future__ import annotations

from types import SimpleNamespace

from focus_agent.observability.release_health import (
    FAIL,
    PASS,
    WARN,
    ReleaseHealthThresholds,
    evaluate_chat_failure_rate,
    evaluate_context_probe,
    evaluate_release_health,
    evaluate_replay_gate,
    evaluate_runtime_ready,
    evaluate_tool_fallback_spike,
    evaluate_trajectory_recorder_ready,
)


def test_runtime_ready_signal_passes_for_ready_payload() -> None:
    signal = evaluate_runtime_ready({"ready": True, "status": "ok"})

    assert signal.key == "runtime_not_ready"
    assert signal.status == PASS
    assert signal.passed is True


def test_runtime_ready_signal_fails_for_unready_payload() -> None:
    signal = evaluate_runtime_ready({"ready": False, "status": "degraded"})

    assert signal.status == FAIL
    assert signal.summary == "runtime is not ready"
    assert signal.detail == "degraded"


def test_trajectory_recorder_signal_reads_readiness_checks() -> None:
    runtime_status = SimpleNamespace(
        checks=[
            {"name": "graph", "ready": True},
            {"name": "trajectory_recorder", "ready": False, "detail": "repository down"},
        ]
    )

    signal = evaluate_trajectory_recorder_ready(runtime_status)

    assert signal.key == "trajectory_recorder_unavailable"
    assert signal.status == FAIL
    assert signal.detail == "repository down"


def test_chat_failure_rate_warns_when_sample_is_too_small() -> None:
    signal = evaluate_chat_failure_rate(
        {"overview": {"turn_count": 3, "non_succeeded_count": 3}},
        thresholds=ReleaseHealthThresholds(chat_failure_min_turns=20),
    )

    assert signal.status == WARN
    assert signal.details["turn_count"] == 3


def test_chat_failure_rate_fails_above_threshold() -> None:
    signal = evaluate_chat_failure_rate(
        {"overview": {"turn_count": 100, "non_succeeded_count": 8}},
        thresholds=ReleaseHealthThresholds(chat_failure_rate=0.05, chat_failure_min_turns=20),
    )

    assert signal.status == FAIL
    assert signal.value == 0.08


def test_tool_fallback_spike_fails_on_rate_or_growth() -> None:
    signal = evaluate_tool_fallback_spike(
        {"overview": {"total_tool_calls": 100, "total_fallback_uses": 22}},
        baseline_stats={"overview": {"total_tool_calls": 100, "total_fallback_uses": 4}},
        thresholds=ReleaseHealthThresholds(
            fallback_rate=0.25,
            fallback_min_tool_calls=20,
            fallback_rate_growth=0.15,
        ),
    )

    assert signal.status == FAIL
    assert signal.details["growth"] == 0.18


def test_replay_gate_fails_failed_replays_and_warns_on_tool_path_drift() -> None:
    failed = evaluate_replay_gate([{"case_id": "case-1", "replay_passed": False}])
    drift = evaluate_replay_gate([{"case_id": "case-2", "tool_path_changed": True}])

    assert failed.status == FAIL
    assert failed.details["failures"] == ["case-1: replay failed"]
    assert drift.status == WARN
    assert drift.details["warnings"] == ["case-2: tool path changed"]


def test_context_probe_checks_required_forbidden_and_size_markers() -> None:
    passed = evaluate_context_probe(
        "Approved finding: postgres migration path",
        required_markers=["Approved", "postgres"],
        forbidden_markers=["OBSOLETE"],
        max_chars=80,
    )
    failed = evaluate_context_probe(
        "OBSOLETE summary",
        required_markers=["Approved"],
        forbidden_markers=["OBSOLETE"],
        max_chars=8,
    )

    assert passed.status == PASS
    assert failed.status == FAIL
    assert failed.details["missing"] == ["Approved"]
    assert failed.details["forbidden"] == ["OBSOLETE"]


def test_release_health_report_combines_core_signals() -> None:
    report = evaluate_release_health(
        runtime_status={
            "ready": True,
            "checks": [{"name": "trajectory_recorder", "ready": True}],
        },
        trajectory_stats={
            "overview": {
                "turn_count": 100,
                "non_succeeded_count": 0,
                "total_tool_calls": 100,
                "total_fallback_uses": 0,
            }
        },
        replay_comparisons=[{"case_id": "case-1", "replay_passed": True}],
    )

    assert report.passed is True
    assert [signal.status for signal in report.signals] == [PASS, PASS, PASS, PASS, PASS]
