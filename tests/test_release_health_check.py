from __future__ import annotations

import json
from pathlib import Path

from scripts import release_health_check


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _readyz_path(tmp_path: Path, *, trajectory_ready: bool = True) -> Path:
    return _write_json(
        tmp_path / "readyz.json",
        {
            "ready": True,
            "status": "ok",
            "checks": [
                {
                    "name": "trajectory_recorder",
                    "ready": trajectory_ready,
                    "detail": "" if trajectory_ready else "database unavailable",
                }
            ],
        },
    )


def _trajectory_stats_path(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "trajectory-stats.json",
        {
            "overview": {
                "turn_count": 40,
                "non_succeeded_count": 0,
                "total_tool_calls": 40,
                "total_fallback_uses": 0,
            }
        },
    )


def _passing_eval_path(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "eval.json",
        {
            "summary": {"total": 2, "passed": 2, "failed": 0, "errors": 0},
            "comparison": {"regressions": []},
        },
    )


def _passing_replay_path(tmp_path: Path) -> Path:
    return _write_json(tmp_path / "replay.json", [{"case_id": "traj-1", "replay_passed": True}])


def _passing_alert_report_path(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "alert-report.json",
        {
            "alerts": [],
            "rules": [{"name": "runtime-ready", "query": "focus_agent_runtime_ready == 0"}],
            "status": "passed",
        },
    )


def _passing_postgres_migration_report_path(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "postgres-migration.json",
        {
            "command": "uv run python -m focus_agent.migrate_local_state --report-path reports/pg.json",
            "errors": [],
            "passed": True,
            "status": "passed",
        },
    )


def _passing_production_smoke_report_path(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "production-smoke.json",
        {
            "checks": [{"name": "readyz", "status": "passed", "passed": True}],
            "passed": True,
            "status": "passed",
        },
    )


def _passing_postgres_ops_report_path(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "postgres-ops.json",
        {
            "operations": [{"name": "connectivity", "status": "passed", "passed": True}],
            "passed": True,
            "status": "passed",
        },
    )


def _passing_otel_smoke_report_path(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "otel-smoke.json",
        {
            "checks": [{"name": "span_export", "status": "passed", "passed": True}],
            "passed": True,
            "spans": [{"name": "focus_agent.release.otel_smoke"}],
            "status": "passed",
        },
    )


def _passing_governance_report_path(tmp_path: Path) -> Path:
    return _write_json(
        tmp_path / "governance-quality.json",
        {
            "summary": {
                "status": "passed",
                "blocking_signals": [],
                "warning_signals": [],
            },
            "signals": [],
            "thresholds": {},
        },
    )


def _required_production_report_args(tmp_path: Path) -> list[str]:
    return [
        "--production-smoke-report-json",
        str(_passing_production_smoke_report_path(tmp_path)),
        "--postgres-ops-report-json",
        str(_passing_postgres_ops_report_path(tmp_path)),
        "--otel-smoke-report-json",
        str(_passing_otel_smoke_report_path(tmp_path)),
        "--governance-report-json",
        str(_passing_governance_report_path(tmp_path)),
    ]


def test_release_health_check_self_check_writes_report(tmp_path: Path) -> None:
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(["--self-check", "--report-json", str(report_path)])
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["status"] == "passed"
    assert report["passed"] is True
    assert [signal["status"] for signal in report["signals"]] == ["pass", "pass", "pass", "pass"]


def test_release_health_check_fails_when_expected_eval_report_is_missing(tmp_path: Path) -> None:
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--self-check",
            "--eval-report-json",
            str(tmp_path / "missing-eval.json"),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["status"] == "failed"
    assert report["signals"][-1]["key"] == "eval_report_missing"


def test_release_health_check_failed_eval_report_blocks_release(tmp_path: Path) -> None:
    eval_report = tmp_path / "eval.json"
    eval_report.write_text(
        json.dumps(
            {
                "summary": {"total": 2, "passed": 1, "failed": 1, "errors": 0},
                "comparison": {"regressions": ["task_success dropped 50.0pp"]},
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--self-check",
            "--eval-report-json",
            str(eval_report),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["signals"][-1]["key"] == "eval_replay_regression"
    assert report["signals"][-1]["details"]["failed"] == 1


def test_release_health_check_empty_eval_report_blocks_release(tmp_path: Path) -> None:
    eval_report = _write_json(tmp_path / "eval-empty.json", {"summary": {}})
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--mode",
            "production",
            "--readyz-json",
            str(_readyz_path(tmp_path)),
            "--trajectory-stats-json",
            str(_trajectory_stats_path(tmp_path)),
            "--replay-comparisons-json",
            str(_passing_replay_path(tmp_path)),
            "--eval-report-json",
            str(eval_report),
            *_required_production_report_args(tmp_path),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    eval_signal = next(signal for signal in report["signals"] if signal["key"] == "eval_report_invalid")

    assert exit_code == 1
    assert eval_signal["status"] == "fail"
    assert eval_signal["summary"] == "eval report has no covered cases"


def test_release_health_check_requires_real_input_without_explicit_fallback(tmp_path: Path) -> None:
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(["--report-json", str(report_path)])

    assert exit_code == 2
    assert not report_path.exists()


def test_release_health_check_production_mode_missing_inputs_fails_closed(tmp_path: Path) -> None:
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        ["--mode", "production", "--report-json", str(report_path)]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    missing_inputs = [
        signal["labels"]["input"]
        for signal in report["signals"]
        if signal["key"] == "release_health_required_input_missing"
    ]

    assert exit_code == 1
    assert report["status"] == "failed"
    assert missing_inputs == [
        "readyz",
        "trajectory_stats",
        "replay_comparisons",
        "eval_report",
        "production_smoke_report",
        "postgres_ops_report",
        "otel_smoke_report",
        "governance_report",
    ]


def test_release_health_check_production_bad_json_writes_failed_report(tmp_path: Path) -> None:
    readyz = tmp_path / "readyz-bad.json"
    readyz.write_text("{bad-json", encoding="utf-8")
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--mode",
            "production",
            "--readyz-json",
            str(readyz),
            "--trajectory-stats-json",
            str(_trajectory_stats_path(tmp_path)),
            "--replay-comparisons-json",
            str(_passing_replay_path(tmp_path)),
            "--eval-report-json",
            str(_passing_eval_path(tmp_path)),
            *_required_production_report_args(tmp_path),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    failed_input = next(
        signal
        for signal in report["signals"]
        if signal["key"] == "release_health_required_input_missing"
    )

    assert exit_code == 1
    assert report["status"] == "failed"
    assert failed_input["labels"]["input"] == "readyz"
    assert "failed to load" in failed_input["detail"]


def test_release_health_check_production_invalid_trajectory_stats_blocks_release(
    tmp_path: Path,
) -> None:
    trajectory_stats = _write_json(tmp_path / "trajectory-invalid.json", [])
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--mode",
            "production",
            "--readyz-json",
            str(_readyz_path(tmp_path)),
            "--trajectory-stats-json",
            str(trajectory_stats),
            "--replay-comparisons-json",
            str(_passing_replay_path(tmp_path)),
            "--eval-report-json",
            str(_passing_eval_path(tmp_path)),
            *_required_production_report_args(tmp_path),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    failed_input = next(
        signal
        for signal in report["signals"]
        if signal["key"] == "release_health_required_input_missing"
    )

    assert exit_code == 1
    assert failed_input["labels"]["input"] == "trajectory_stats"
    assert failed_input["detail"] == "invalid trajectory stats input"


def test_release_health_check_production_empty_replay_comparison_blocks_release(
    tmp_path: Path,
) -> None:
    replay = _write_json(tmp_path / "replay-empty.json", [])
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--mode",
            "production",
            "--readyz-json",
            str(_readyz_path(tmp_path)),
            "--trajectory-stats-json",
            str(_trajectory_stats_path(tmp_path)),
            "--replay-comparisons-json",
            str(replay),
            "--eval-report-json",
            str(_passing_eval_path(tmp_path)),
            *_required_production_report_args(tmp_path),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    failed_input = next(
        signal
        for signal in report["signals"]
        if signal["key"] == "release_health_required_input_missing"
    )

    assert exit_code == 1
    assert failed_input["labels"]["input"] == "replay_comparisons"
    assert failed_input["detail"] == "empty replay comparison input"


def test_release_health_check_marks_explicit_self_check_fallback(tmp_path: Path) -> None:
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--allow-self-check-fallback",
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    fallback_signals = [
        signal for signal in report["signals"] if signal["key"] == "release_health_self_check_fallback"
    ]

    assert exit_code == 0
    assert [signal["status"] for signal in fallback_signals] == ["warn", "warn"]


def test_release_health_check_replay_comparison_blocks_release(tmp_path: Path) -> None:
    replay = tmp_path / "replay.json"
    replay.write_text(
        json.dumps([{"case_id": "traj-1", "replay_passed": False}]),
        encoding="utf-8",
    )
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--self-check",
            "--replay-comparisons-json",
            str(replay),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["signals"][4]["key"] == "eval_replay_regression"
    assert report["signals"][4]["details"]["failures"] == ["traj-1: replay failed"]


def test_release_health_check_production_replay_comparison_blocks_release(tmp_path: Path) -> None:
    replay = _write_json(tmp_path / "replay.json", [{"case_id": "traj-1", "replay_passed": False}])
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--mode",
            "production",
            "--readyz-json",
            str(_readyz_path(tmp_path)),
            "--trajectory-stats-json",
            str(_trajectory_stats_path(tmp_path)),
            "--replay-comparisons-json",
            str(replay),
            "--eval-report-json",
            str(_passing_eval_path(tmp_path)),
            *_required_production_report_args(tmp_path),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    replay_signal = next(signal for signal in report["signals"] if signal["key"] == "eval_replay_regression")

    assert exit_code == 1
    assert replay_signal["status"] == "fail"
    assert replay_signal["details"]["failures"] == ["traj-1: replay failed"]


def test_release_health_check_production_eval_regression_blocks_release(tmp_path: Path) -> None:
    eval_report = _write_json(
        tmp_path / "eval-regression.json",
        {
            "summary": {"total": 4, "passed": 4, "failed": 0, "errors": 0},
            "comparison": {"regressions": ["task_success dropped 12.0pp"]},
        },
    )
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--mode",
            "production",
            "--readyz-json",
            str(_readyz_path(tmp_path)),
            "--trajectory-stats-json",
            str(_trajectory_stats_path(tmp_path)),
            "--replay-comparisons-json",
            str(_passing_replay_path(tmp_path)),
            "--eval-report-json",
            str(eval_report),
            *_required_production_report_args(tmp_path),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["signals"][-1]["key"] == "eval_replay_regression"
    assert report["signals"][-1]["details"]["regressions"] == ["task_success dropped 12.0pp"]


def test_release_health_check_production_baseline_eval_regression_blocks_release(
    tmp_path: Path,
) -> None:
    baseline_eval = _write_json(
        tmp_path / "eval-baseline.json",
        {
            "summary": {
                "total": 10,
                "passed": 10,
                "failed": 0,
                "errors": 0,
                "task_success": 1.0,
            },
            "comparison": {"regressions": []},
        },
    )
    current_eval = _write_json(
        tmp_path / "eval-current.json",
        {
            "summary": {
                "total": 10,
                "passed": 9,
                "failed": 0,
                "errors": 0,
                "task_success": 0.9,
            },
            "comparison": {"regressions": []},
        },
    )
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--mode",
            "production",
            "--readyz-json",
            str(_readyz_path(tmp_path)),
            "--trajectory-stats-json",
            str(_trajectory_stats_path(tmp_path)),
            "--replay-comparisons-json",
            str(_passing_replay_path(tmp_path)),
            "--eval-report-json",
            str(current_eval),
            "--baseline-eval-report-json",
            str(baseline_eval),
            *_required_production_report_args(tmp_path),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["signals"][-1]["key"] == "eval_replay_regression"
    assert report["signals"][-1]["details"]["regressions"] == ["task_success dropped 10.0pp"]


def test_release_health_check_production_trajectory_recorder_unavailable_blocks_release(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--mode",
            "production",
            "--readyz-json",
            str(_readyz_path(tmp_path, trajectory_ready=False)),
            "--trajectory-stats-json",
            str(_trajectory_stats_path(tmp_path)),
            "--replay-comparisons-json",
            str(_passing_replay_path(tmp_path)),
            "--eval-report-json",
            str(_passing_eval_path(tmp_path)),
            *_required_production_report_args(tmp_path),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    recorder_signal = next(
        signal for signal in report["signals"] if signal["key"] == "trajectory_recorder_unavailable"
    )

    assert exit_code == 1
    assert recorder_signal["status"] == "fail"
    assert recorder_signal["detail"] == "database unavailable"


def test_release_health_check_alert_report_blocks_release(tmp_path: Path) -> None:
    alert_report = _write_json(
        tmp_path / "alert-firing.json",
        {
            "alerts": [{"name": "runtime-ready", "state": "firing"}],
            "rules": [{"name": "runtime-ready"}],
            "status": "passed",
        },
    )
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--mode",
            "production",
            "--readyz-json",
            str(_readyz_path(tmp_path)),
            "--trajectory-stats-json",
            str(_trajectory_stats_path(tmp_path)),
            "--replay-comparisons-json",
            str(_passing_replay_path(tmp_path)),
            "--eval-report-json",
            str(_passing_eval_path(tmp_path)),
            "--alert-report-json",
            str(alert_report),
            *_required_production_report_args(tmp_path),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    alert_signal = next(signal for signal in report["signals"] if signal["key"] == "alert_rules_report")

    assert exit_code == 1
    assert alert_signal["status"] == "fail"
    assert alert_signal["details"]["firing_alerts"] == ["runtime-ready"]


def test_release_health_check_postgres_migration_report_blocks_release(tmp_path: Path) -> None:
    postgres_report = _write_json(
        tmp_path / "postgres-migration-failed.json",
        {"command": "uv run python -m focus_agent.migrate_local_state", "errors": ["schema drift"], "status": "failed"},
    )
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--mode",
            "production",
            "--readyz-json",
            str(_readyz_path(tmp_path)),
            "--trajectory-stats-json",
            str(_trajectory_stats_path(tmp_path)),
            "--replay-comparisons-json",
            str(_passing_replay_path(tmp_path)),
            "--eval-report-json",
            str(_passing_eval_path(tmp_path)),
            "--postgres-migration-report-json",
            str(postgres_report),
            *_required_production_report_args(tmp_path),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    postgres_signal = next(
        signal for signal in report["signals"] if signal["key"] == "postgres_migration_verification"
    )

    assert exit_code == 1
    assert postgres_signal["status"] == "fail"
    assert postgres_signal["details"]["errors"] == ["schema drift"]


def test_release_health_check_reads_production_ops_and_otel_reports(tmp_path: Path) -> None:
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--mode",
            "production",
            "--readyz-json",
            str(_readyz_path(tmp_path)),
            "--trajectory-stats-json",
            str(_trajectory_stats_path(tmp_path)),
            "--replay-comparisons-json",
            str(_passing_replay_path(tmp_path)),
            "--eval-report-json",
            str(_passing_eval_path(tmp_path)),
            "--production-smoke-report-json",
            str(_passing_production_smoke_report_path(tmp_path)),
            "--postgres-ops-report-json",
            str(_passing_postgres_ops_report_path(tmp_path)),
            "--otel-smoke-report-json",
            str(_passing_otel_smoke_report_path(tmp_path)),
            "--governance-report-json",
            str(_passing_governance_report_path(tmp_path)),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    statuses = {signal["key"]: signal["status"] for signal in report["signals"]}

    assert exit_code == 0
    assert statuses["production_smoke_report"] == "pass"
    assert statuses["postgres_ops_report"] == "pass"
    assert statuses["otel_smoke_report"] == "pass"


def test_release_health_check_production_rejects_dry_run_ops_report(tmp_path: Path) -> None:
    dry_run_postgres = _write_json(
        tmp_path / "postgres-ops-dry-run.json",
        {
            "operations": [{"name": "connectivity", "status": "dry-run"}],
            "passed": True,
            "status": "dry-run",
        },
    )
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--mode",
            "production",
            "--readyz-json",
            str(_readyz_path(tmp_path)),
            "--trajectory-stats-json",
            str(_trajectory_stats_path(tmp_path)),
            "--replay-comparisons-json",
            str(_passing_replay_path(tmp_path)),
            "--eval-report-json",
            str(_passing_eval_path(tmp_path)),
            "--production-smoke-report-json",
            str(_passing_production_smoke_report_path(tmp_path)),
            "--postgres-ops-report-json",
            str(dry_run_postgres),
            "--otel-smoke-report-json",
            str(_passing_otel_smoke_report_path(tmp_path)),
            "--governance-report-json",
            str(_passing_governance_report_path(tmp_path)),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    dry_run_signal = next(
        signal
        for signal in report["signals"]
        if signal["key"] == "release_health_required_input_missing"
        and signal["labels"]["input"] == "postgres_ops_report"
    )

    assert exit_code == 1
    assert dry_run_signal["status"] == "fail"
    assert "cannot be dry-run" in dry_run_signal["detail"]


def test_release_health_check_failed_otel_smoke_report_blocks_release(tmp_path: Path) -> None:
    otel_report = _write_json(
        tmp_path / "otel-failed.json",
        {
            "checks": [{"name": "span_export", "status": "failed"}],
            "passed": True,
            "status": "passed",
        },
    )
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--mode",
            "production",
            "--readyz-json",
            str(_readyz_path(tmp_path)),
            "--trajectory-stats-json",
            str(_trajectory_stats_path(tmp_path)),
            "--replay-comparisons-json",
            str(_passing_replay_path(tmp_path)),
            "--eval-report-json",
            str(_passing_eval_path(tmp_path)),
            "--production-smoke-report-json",
            str(_passing_production_smoke_report_path(tmp_path)),
            "--postgres-ops-report-json",
            str(_passing_postgres_ops_report_path(tmp_path)),
            "--otel-smoke-report-json",
            str(otel_report),
            "--governance-report-json",
            str(_passing_governance_report_path(tmp_path)),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    otel_signal = next(signal for signal in report["signals"] if signal["key"] == "otel_smoke_report")

    assert exit_code == 1
    assert otel_signal["status"] == "fail"
    assert otel_signal["details"]["failed_checks"] == ["span_export"]


def test_release_health_check_governance_blocking_signal_blocks_release(tmp_path: Path) -> None:
    governance_report = _write_json(
        tmp_path / "governance-quality.json",
        {
            "summary": {
                "status": "failed",
                "blocking_signals": ["delegation_success"],
                "warning_signals": ["cost_token_tool_budget"],
            },
            "thresholds": {
                "delegation_success": {"warning_min": 0.98, "blocking_min": 0.95}
            },
            "signals": [
                {
                    "key": "delegation_success",
                    "status": "block",
                    "severity": "blocking",
                    "value": 0.9,
                    "thresholds": {"warning": 0.98, "blocking": 0.95},
                }
            ],
        },
    )
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(
        [
            "--self-check",
            "--governance-report-json",
            str(governance_report),
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    governance_signal = next(
        signal for signal in report["signals"] if signal["key"] == "agent_governance_quality"
    )

    assert exit_code == 1
    assert governance_signal["status"] == "fail"
    assert governance_signal["details"]["blocking_signals"] == ["delegation_success"]
    assert governance_signal["details"]["thresholds"]["delegation_success"]["blocking_min"] == 0.95
