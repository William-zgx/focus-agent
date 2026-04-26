from __future__ import annotations

import json
from pathlib import Path
import sys

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


def test_postgres_ops_backup_command_failure_records_evidence() -> None:
    report = postgres_ops.build_report(
        backup_command=f'{sys.executable} -c "import sys; sys.exit(7)"',
        timeout_seconds=5,
    )

    backup = next(operation for operation in report["operations"] if operation["name"] == "backup_command")

    assert report["status"] == "failed"
    assert backup["status"] == "failed"
    assert backup["evidence"]["returncode"] == 7
    assert report["artifacts"][0]["operation"] == "backup_command"
    assert report["summary"]["failed_operations"].count("backup_command") == 1


def test_postgres_ops_restore_verification_evidence_failure(tmp_path: Path) -> None:
    evidence_path = tmp_path / "restore-verification.json"
    evidence_path.write_text(
        json.dumps({"status": "failed", "passed": False, "errors": ["missing restored row"]}),
        encoding="utf-8",
    )

    report = postgres_ops.build_report(
        restore_command=f'{sys.executable} -c "print(42)"',
        restore_verification_evidence=evidence_path,
        timeout_seconds=5,
    )
    restore = next(operation for operation in report["operations"] if operation["name"] == "restore_command")
    verification = next(operation for operation in report["operations"] if operation["name"] == "restore_verification")

    assert restore["status"] == "passed"
    assert verification["status"] == "failed"
    assert verification["evidence"]["errors"] == ["missing restored row"]
    assert "restore_verification" in report["summary"]["failed_operations"]
