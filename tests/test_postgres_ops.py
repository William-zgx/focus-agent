from __future__ import annotations

import json
from pathlib import Path

from scripts import postgres_ops


def test_postgres_ops_dry_run_writes_report(tmp_path: Path) -> None:
    report_path = tmp_path / "postgres-ops.json"

    exit_code = postgres_ops.main(["--dry-run", "--report-json", str(report_path)])
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["report_type"] == "postgres_ops"
    assert report["status"] == "dry-run"
    assert report["passed"] is True
    assert report["summary"]["total"] == 4
    assert {operation["status"] for operation in report["operations"]} == {"dry-run"}
    assert report["checks"] == report["operations"]
    assert report["errors"] == []
    assert report["artifacts"] == []
    assert report["command"] == "uv run python scripts/postgres_ops.py --dry-run"


def test_postgres_ops_live_without_database_uri_fails_closed(tmp_path: Path) -> None:
    report_path = tmp_path / "postgres-ops.json"

    exit_code = postgres_ops.main(["--report-json", str(report_path)])
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["status"] == "failed"
    assert report["summary"]["failed"] == 4
    assert len(report["errors"]) == 4
