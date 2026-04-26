from __future__ import annotations

import json
from pathlib import Path

from scripts import production_smoke


def test_production_smoke_dry_run_writes_report(tmp_path: Path) -> None:
    report_path = tmp_path / "production-smoke.json"

    exit_code = production_smoke.main(
        [
            "--dry-run",
            "--base-url",
            "https://focus-agent.example.com",
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["report_type"] == "production_smoke"
    assert report["status"] == "dry-run"
    assert report["passed"] is True
    assert report["summary"]["total"] == 13
    assert set(report["summary"]["by_category"]) == {
        "api",
        "sdk",
        "web",
        "graph",
        "security",
        "rate-limit",
    }
    assert {check["status"] for check in report["checks"]} == {"dry-run"}
    assert report["checks"][0]["url"] == "https://focus-agent.example.com/healthz"
    assert {check["category"] for check in report["checks"]} == {
        "api",
        "sdk",
        "web",
        "graph",
        "security",
        "rate-limit",
    }
    assert any(check["name"] == "graph_min_chat_turn" and check["method"] == "POST" for check in report["checks"])
