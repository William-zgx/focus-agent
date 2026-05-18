from __future__ import annotations

import json
from pathlib import Path

from scripts import eval_provider_gate


def test_eval_workflow_missing_provider_key_policy_defaults() -> None:
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "eval.yml"
    text = workflow.read_text(encoding="utf-8")

    assert (
        "PROVIDER_EVAL_MISSING_KEY_POLICY: "
        "${{ vars.PROVIDER_EVAL_MISSING_KEY_POLICY || "
        "(github.event_name == 'pull_request' && 'skip' || 'fail') }}"
    ) in text


def test_provider_eval_gate_skips_missing_key_with_annotation(tmp_path: Path, capsys) -> None:
    report_json = tmp_path / "gate.json"

    exit_code = eval_provider_gate.run_provider_eval_gate(
        command=["python", "-c", "raise SystemExit(99)"],
        key_envs=["OPENAI_API_KEY"],
        missing_policy="skip",
        gate_report_json=report_json,
        env={},
    )
    report = json.loads(report_json.read_text(encoding="utf-8"))
    stdout = capsys.readouterr().out

    assert exit_code == 0
    assert "::notice title=Provider-backed eval skipped::" in stdout
    assert report["status"] == "skipped"
    assert report["missing_key_envs"] == ["OPENAI_API_KEY"]
    assert report["exit_code"] is None


def test_provider_eval_gate_fails_closed_when_policy_requires_key(tmp_path: Path, capsys) -> None:
    report_json = tmp_path / "gate.json"

    exit_code = eval_provider_gate.run_provider_eval_gate(
        command=["python", "-c", "raise SystemExit(99)"],
        key_envs=["OPENAI_API_KEY"],
        missing_policy="fail",
        gate_report_json=report_json,
        env={},
    )
    report = json.loads(report_json.read_text(encoding="utf-8"))
    stdout = capsys.readouterr().out

    assert exit_code == 1
    assert "::error title=Provider-backed eval blocked::" in stdout
    assert report["status"] == "failed"
    assert report["policy"] == "fail"


def test_provider_eval_gate_runs_command_when_key_present(tmp_path: Path) -> None:
    report_json = tmp_path / "gate.json"
    marker = tmp_path / "ran.txt"

    exit_code = eval_provider_gate.run_provider_eval_gate(
        command=[
            "python",
            "-c",
            f"from pathlib import Path; Path({str(marker)!r}).write_text('ok')",
        ],
        key_envs=["OPENAI_API_KEY"],
        missing_policy="fail",
        gate_report_json=report_json,
        env={"OPENAI_API_KEY": "test-key"},
    )
    report = json.loads(report_json.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert marker.read_text(encoding="utf-8") == "ok"
    assert report["status"] == "passed"
    assert report["missing_key_envs"] == []
