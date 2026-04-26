from __future__ import annotations

import json
from pathlib import Path

from scripts import release_gate


def test_release_gate_plan_matches_release_checklist_order() -> None:
    planned = [
        (command.label, release_gate._command_text(command.command))
        for command in release_gate.RELEASE_GATE_COMMANDS
    ]

    assert planned == [
        ("lint", "make lint"),
        ("ci-test", "make ci-test"),
        ("sdk-check", "make sdk-check"),
        ("sdk-build", "make sdk-build"),
        ("web-check", "make web-check"),
        ("web-build", "make web-build"),
        (
            "observability-ui-smoke",
            "uv run python scripts/observability_ui_smoke.py --scenario all",
        ),
        ("web-observability-smoke", "pnpm --dir apps/web smoke:observability"),
        ("ui-smoke", "uv run python scripts/ui_smoke_test.py"),
        (
            "eval-smoke",
            "uv run python -m tests.eval --suite smoke --concurrency 1 "
            "--report-json reports/release-gate/eval-smoke.json",
        ),
        (
            "eval-observability",
            "uv run python -m tests.eval --suite observability --concurrency 1 "
            "--report-json reports/release-gate/eval-observability.json",
        ),
        (
            "memory-context-eval",
            "uv run python scripts/memory_context_eval.py "
            "--report-json reports/release-gate/memory-context-eval.json",
        ),
        (
            "agent-governance-report",
            "uv run python scripts/agent_governance_report.py "
            "--report-json reports/agent-governance/latest.json",
        ),
        (
            "release-health",
            "uv run python scripts/release_health_check.py "
            "--mode local "
            "--ready-url http://127.0.0.1:8000/readyz "
            "--trajectory-stats-url http://127.0.0.1:8000/v1/observability/trajectory/stats "
            "--allow-self-check-fallback "
            "--eval-report-json reports/release-gate/eval-smoke.json "
            "--eval-report-json reports/release-gate/eval-observability.json "
            "--eval-report-json reports/release-gate/memory-context-eval.json "
            "--governance-report-json reports/agent-governance/latest.json "
            "--report-json reports/release-gate/release-health.json",
        ),
    ]


def test_release_gate_dry_run_writes_report_without_running_commands(tmp_path: Path) -> None:
    report_path = tmp_path / "release-gate.json"

    def _unexpected_runner(command: release_gate.GateCommand, root: Path):  # noqa: ARG001
        raise AssertionError("dry-run must not execute release gate commands")

    report = release_gate.run_release_gate(
        dry_run=True,
        only_labels=["lint", "ci-test"],
        report_json=report_path,
        root=tmp_path,
        runner=_unexpected_runner,
    )
    saved_report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["status"] == "dry-run"
    assert saved_report["status"] == "dry-run"
    assert saved_report["summary"]["dry-run"] == 2
    assert saved_report["summary"]["skipped"] == len(release_gate.RELEASE_GATE_COMMANDS) - 2
    assert saved_report["commands"][0]["label"] == "lint"
    assert saved_report["commands"][0]["status"] == "dry-run"
    assert saved_report["commands"][0]["skip_reason"] == "dry-run"
    assert saved_report["commands"][1]["label"] == "ci-test"
    assert saved_report["commands"][1]["status"] == "dry-run"
    assert saved_report["commands"][2]["label"] == "sdk-check"
    assert saved_report["commands"][2]["status"] == "skipped"
    assert saved_report["commands"][2]["skip_reason"] == "not selected by --only"


def test_release_gate_skip_overrides_selected_command(tmp_path: Path) -> None:
    report = release_gate.run_release_gate(
        dry_run=True,
        only_labels=["lint", "ci-test"],
        skip_labels=["ci-test"],
        report_json=tmp_path / "report.json",
        root=tmp_path,
    )
    commands = {command["label"]: command for command in report["commands"]}

    assert commands["lint"]["status"] == "dry-run"
    assert commands["ci-test"]["status"] == "skipped"
    assert commands["ci-test"]["skip_reason"] == "requested by --skip"


def test_release_gate_failure_records_output_tail_and_skips_remaining(tmp_path: Path) -> None:
    calls: list[str] = []

    def _fake_runner(command: release_gate.GateCommand, root: Path):  # noqa: ARG001
        calls.append(command.label)
        if command.label == "lint":
            return release_gate.CommandOutcome(exit_code=0, stdout="lint ok\n")
        return release_gate.CommandOutcome(
            exit_code=23,
            stdout="\n".join(f"stdout line {index}" for index in range(100)),
            stderr="first error\nfinal error\n",
        )

    report = release_gate.run_release_gate(
        only_labels=["lint", "ci-test", "sdk-check"],
        report_json=tmp_path / "report.json",
        root=tmp_path,
        runner=_fake_runner,
    )
    commands = {command["label"]: command for command in report["commands"]}

    assert report["status"] == "failed"
    assert calls == ["lint", "ci-test"]
    assert commands["lint"]["status"] == "passed"
    assert commands["ci-test"]["status"] == "failed"
    assert commands["ci-test"]["exit_code"] == 23
    assert "stdout line 99" in commands["ci-test"]["stdout_tail"]
    assert "stdout line 0" not in commands["ci-test"]["stdout_tail"]
    assert commands["ci-test"]["stderr_tail"] == "first error\nfinal error"
    assert commands["sdk-check"]["status"] == "skipped"
    assert commands["sdk-check"]["skip_reason"] == "prior failure: ci-test"


def test_release_gate_keep_going_runs_after_failure(tmp_path: Path) -> None:
    calls: list[str] = []

    def _fake_runner(command: release_gate.GateCommand, root: Path):  # noqa: ARG001
        calls.append(command.label)
        return release_gate.CommandOutcome(
            exit_code=7 if command.label == "ci-test" else 0,
            stdout=f"{command.label} done\n",
        )

    report = release_gate.run_release_gate(
        only_labels=["lint", "ci-test", "sdk-check"],
        report_json=tmp_path / "report.json",
        root=tmp_path,
        runner=_fake_runner,
        keep_going=True,
    )
    commands = {command["label"]: command for command in report["commands"]}

    assert report["status"] == "failed"
    assert report["keep_going"] is True
    assert calls == ["lint", "ci-test", "sdk-check"]
    assert commands["ci-test"]["status"] == "failed"
    assert commands["sdk-check"]["status"] == "passed"


def test_release_gate_main_dry_run_uses_cli_options(tmp_path: Path) -> None:
    report_path = tmp_path / "cli-report.json"

    exit_code = release_gate.main(
        [
            "--dry-run",
            "--only",
            "lint,ci-test",
            "--skip",
            "ci-test",
            "--report-json",
            str(report_path),
            "--keep-going",
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["keep_going"] is True
    assert report["commands"][0]["status"] == "dry-run"
    assert report["summary"]["dry-run"] == 1
    assert report["summary"]["skipped"] == len(release_gate.RELEASE_GATE_COMMANDS) - 1
