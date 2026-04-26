from __future__ import annotations

import json
from pathlib import Path

from scripts import release_health_check


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


def test_release_health_check_requires_real_input_without_explicit_fallback(tmp_path: Path) -> None:
    report_path = tmp_path / "release-health.json"

    exit_code = release_health_check.main(["--report-json", str(report_path)])

    assert exit_code == 2
    assert not report_path.exists()


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
