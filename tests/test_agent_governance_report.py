from __future__ import annotations

import json
from pathlib import Path

from scripts import agent_governance_report


def _write_report(
    path: Path,
    *,
    suite: str,
    per_tag_success: dict[str, float],
    failed: int = 0,
    summary_extra: dict[str, object] | None = None,
) -> None:
    total = 4
    summary = {
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
    }
    if summary_extra:
        summary.update(summary_extra)
    path.write_text(
        json.dumps(
            {
                "meta": {"suite": suite},
                "summary": summary,
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
    assert report["signals"][0]["key"] == "delegation_success"
    assert report["signals"][0]["thresholds"]["blocking"] == 0.95
    assert set(report) == {
        "meta",
        "commands",
        "artifacts",
        "quality",
        "thresholds",
        "signals",
        "summary",
    }


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


def test_governance_report_threshold_blocking_signals(tmp_path: Path) -> None:
    delegation = tmp_path / "delegation.json"
    governance = tmp_path / "governance.json"
    _write_report(
        delegation,
        suite="agent_delegation",
        per_tag_success={"agent_delegation": 0.9},
    )
    _write_report(
        governance,
        suite="agent_governance",
        per_tag_success={"critic": 0.82, "review_queue": 1.0},
        summary_extra={
            "critic_precision": 0.82,
            "critic_recall": 0.9,
            "review_queue_backlog": 11,
        },
    )

    report = agent_governance_report.build_governance_report(
        eval_reports=[("delegation", delegation), ("governance", governance)]
    )
    signals = {signal["key"]: signal for signal in report["signals"]}

    assert report["summary"]["status"] == "failed"
    assert signals["delegation_success"]["status"] == "block"
    assert signals["delegation_success"]["thresholds"] == {"warning": 0.98, "blocking": 0.95}
    assert signals["critic_precision"]["status"] == "block"
    assert signals["critic_recall"]["status"] == "pass"
    assert signals["review_queue_backlog"]["status"] == "block"
    assert set(report["summary"]["blocking_signals"]) >= {
        "delegation_success",
        "critic_precision",
        "review_queue_backlog",
    }


def test_governance_report_cost_budget_warning_without_block(tmp_path: Path) -> None:
    delegation = tmp_path / "delegation.json"
    governance = tmp_path / "governance.json"
    _write_report(
        delegation,
        suite="agent_delegation",
        per_tag_success={"agent_delegation": 1.0},
        summary_extra={"avg_cost_usd": 0.04},
    )
    _write_report(
        governance,
        suite="agent_governance",
        per_tag_success={"critic": 1.0, "review_queue": 1.0},
        summary_extra={"critic_precision": 0.95, "critic_recall": 0.96, "avg_cost_usd": 0.04},
    )

    report = agent_governance_report.build_governance_report(
        eval_reports=[("delegation", delegation), ("governance", governance)]
    )
    budget_signal = next(signal for signal in report["signals"] if signal["key"] == "cost_token_tool_budget")

    assert report["summary"]["status"] == "passed"
    assert budget_signal["status"] == "warn"
    assert "cost_token_tool_budget" in report["summary"]["warning_signals"]
    assert budget_signal["details"]["checks"][0]["thresholds"] == {
        "warning": 0.03,
        "blocking": 0.05,
    }
