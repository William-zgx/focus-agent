from __future__ import annotations

import json
from pathlib import Path

from scripts import otel_smoke


def test_otel_smoke_dry_run_writes_report(tmp_path: Path) -> None:
    report_path = tmp_path / "otel-smoke.json"

    exit_code = otel_smoke.main(
        [
            "--dry-run",
            "--endpoint",
            "http://otel-collector:4318",
            "--service-name",
            "focus-agent-prod",
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["report_type"] == "otel_smoke"
    assert report["status"] == "dry-run"
    assert report["passed"] is True
    assert report["summary"]["spans"] == 1
    assert {check["status"] for check in report["checks"]} == {"dry-run"}
