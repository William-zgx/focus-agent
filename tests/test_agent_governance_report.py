from __future__ import annotations

import json
from pathlib import Path

from scripts import agent_governance_report


def _write_report(path: Path, *, suite: str, per_tag_success: dict[str, float], failed: int = 0) -> None:
    total = 4
    path.write_text(
        json.dumps(
            {
                "meta": {"suite": suite},
                "summary": {
                    "total": total,
                    "passed": total - failed,
                    "failed": failed,
                    "errors": 0,
                    "task_success": (total - failed) / total,
                    "avg_cost_usd": 0.002,
                    "avg_input_tokens": 120.0,
                    "avg_output_tokens": 40.0,
                    "avg_tool_calls": 0.5,
                    "per_tag_success": per_tag_success,
                },
                "comparison": {"regressions": []},
                "results": [],
            }
        ),
        encoding="utf-8",
    )


def test_governance_report_aggregates_quality_dimensions(tmp_path: Path) -> None:
    delegation = tmp_path / "delegation.json"
    governance = tmp_path / "governance.json"
    task_ledger = tmp_path / "task-ledger.json"
    agent_team = tmp_path / "agent-team.json"
    _write_report(delegation, suite="agent_delegation", per_tag_success={"agent_delegation": 1.0})
    _write_report(
        governance,
        suite="agent_governance",
        per_tag_success={"critic": 1.0, "memory_curator": 1.0, "review_queue": 1.0},
    )
    _write_report(task_ledger, suite="agent_task_ledger", per_tag_success={"critic_gate": 1.0})
    _write_report(agent_team, suite="agent_team", per_tag_success={"merge_review": 1.0})

    report = agent_governance_report.build_governance_report(
        eval_reports=[
            ("delegation", delegation),
            ("governance", governance),
            ("task-ledger", task_ledger),
            ("agent-team", agent_team),
        ]
    )

    assert report["meta"]["suite"] == "agent_governance_quality"
    assert report["summary"]["status"] == "passed"
    assert report["summary"]["present_reports"] == 4
    assert report["quality"]["delegation"]["task_success"] == 1.0
    assert report["quality"]["critic"]["tags"] == {"critic": 1.0, "critic_gate": 1.0}
    assert report["quality"]["review"]["tags"] == {
        "memory_curator": 1.0,
        "review_queue": 1.0,
        "merge_review": 1.0,
    }
    assert report["quality"]["cost"]["avg_cost_usd"] == 0.002
    assert set(report) == {"meta", "commands", "artifacts", "quality", "summary"}


def test_governance_cli_accepts_label_path_reports(tmp_path: Path, capsys) -> None:
    delegation = tmp_path / "delegation.json"
    governance = tmp_path / "governance.json"
    report_json = tmp_path / "governance-quality.json"
    _write_report(delegation, suite="agent_delegation", per_tag_success={"agent_delegation": 1.0})
    _write_report(governance, suite="agent_governance", per_tag_success={"critic": 1.0})

    exit_code = agent_governance_report.main(
        [
            "--report-json",
            str(report_json),
            "--eval-report",
            f"delegation={delegation}",
            "--eval-report",
            f"governance={governance}",
        ]
    )
    stdout = json.loads(capsys.readouterr().out)
    report = json.loads(report_json.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert stdout["status"] == "passed"
    assert stdout["report_json"] == str(report_json)
    assert report["commands"][0]["label"] == "eval-delegation"
    assert report["summary"]["missing_reports"] == 0
    assert agent_governance_report.DEFAULT_REPORT_JSON == Path("reports/agent-governance/latest.json")
