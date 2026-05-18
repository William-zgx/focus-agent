from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts import postgres_ops


def test_postgres_ops_dry_run_writes_report(tmp_path: Path) -> None:
    report_path = tmp_path / "postgres-ops.json"

    exit_code = postgres_ops.main(["--dry-run", "--report-json", str(report_path)])
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["report_type"] == "postgres_ops"
    assert report["report_version"] == 3
    assert report["status"] == "dry-run"
    assert report["passed"] is True
    assert report["summary"]["total"] == len(postgres_ops.DEFAULT_OPERATIONS)
    assert {operation["status"] for operation in report["operations"]} == {"dry-run"}
    assert report["checks"] == report["operations"]
    assert report["errors"] == []
    assert report["artifacts"] == []
    assert report["command"] == "uv run python scripts/postgres_ops.py --dry-run"
    assert report["schema"]["expected_schema_version"] == postgres_ops._expected_schema_version()
    assert report["schema"]["missing_migrations"] == []
    assert report["pgvector"]["status"] == "dry-run"
    assert report["pool"]["status"] == "dry-run"
    assert report["slow_query"]["status"] == "dry-run"


def test_postgres_ops_live_without_database_uri_fails_closed(tmp_path: Path) -> None:
    report_path = tmp_path / "postgres-ops.json"

    exit_code = postgres_ops.main(["--report-json", str(report_path)])
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["status"] == "failed"
    assert report["summary"]["failed"] == len(postgres_ops.DEFAULT_OPERATIONS)
    assert len(report["errors"]) == len(postgres_ops.DEFAULT_OPERATIONS)


def test_postgres_ops_v3_live_schema_doctor_checks(monkeypatch) -> None:
    expected_versions = postgres_ops._expected_migration_versions()
    expected_schema_version = postgres_ops._expected_schema_version()

    def fake_run_query(database_uri, query, params=None):  # noqa: ARG001
        if "pg_extension" in query:
            return (False, True, None, True)
        if "SELECT 1" in query:
            return (1,)
        if "pg_try_advisory_lock" in query:
            return (True,)
        if "pg_advisory_unlock" in query:
            return (True,)
        if "focus_background_jobs" in query:
            return (True,)
        if "focus_trajectory_turns" in query:
            return (True,)
        raise AssertionError(f"unexpected query: {query}")

    monkeypatch.setattr(postgres_ops, "_run_query", fake_run_query)
    monkeypatch.setattr(postgres_ops, "_run_query_rows", lambda database_uri, query, params=None: [(v,) for v in expected_versions])

    report = postgres_ops.build_report(database_uri="postgresql://example/focus")

    assert report["report_version"] == 3
    assert report["passed"] is True
    assert report["v3"]["expected_schema_version"] == expected_schema_version
    assert report["schema"]["current_schema_version"] == expected_schema_version
    assert report["schema"]["missing_migrations"] == []
    assert report["pgvector"]["available"] is True
    assert "pool" in report
    assert "slow_query" in report
    operations = {operation["name"]: operation for operation in report["operations"]}
    assert operations["schema_version"]["max_applied_version"] == expected_schema_version
    assert operations["migration_state"]["missing_versions"] == []
    assert operations["migration_state"]["future_versions"] == []
    assert operations["pgvector_readiness"]["available"] is True


def test_postgres_ops_v3_flags_missing_and_future_migrations(monkeypatch) -> None:
    def fake_run_query(database_uri, query, params=None):  # noqa: ARG001
        if "pg_extension" in query:
            return (False, True, None, False)
        return (True,)

    monkeypatch.setattr(postgres_ops, "_run_query", fake_run_query)
    monkeypatch.setattr(
        postgres_ops,
        "_run_query_rows",
        lambda database_uri, query, params=None: [(1,), (postgres_ops._expected_schema_version() + 1,)],
    )

    report = postgres_ops.build_report(database_uri="postgresql://example/focus")
    migration_state = next(operation for operation in report["operations"] if operation["name"] == "migration_state")

    assert report["passed"] is False
    assert migration_state["status"] == "failed"
    assert 2 in migration_state["missing_versions"]
    assert postgres_ops._expected_schema_version() + 1 in migration_state["future_versions"]


def test_postgres_ops_migration_and_doctor_commands_record_evidence(monkeypatch) -> None:
    def live_checks(**kwargs):  # noqa: ARG001
        return [
            postgres_ops._operation(
                name,
                status="passed",
                detail="stubbed live check",
                passed=True,
            )
            for name in postgres_ops.DEFAULT_OPERATIONS
        ]

    monkeypatch.setattr(postgres_ops, "_live_database_operations", live_checks)
    report = postgres_ops.build_report(
        database_uri="postgresql://example/focus",
        migration_command=f'{sys.executable} -c "print(123)"',
        doctor_command=f'{sys.executable} -c "print(456)"',
        timeout_seconds=5,
    )

    command_operations = {
        operation["name"]: operation
        for operation in report["operations"]
        if operation["name"] in {"migration_command", "doctor_command"}
    }

    assert command_operations["migration_command"]["status"] == "passed"
    assert command_operations["doctor_command"]["status"] == "passed"
    assert [artifact["operation"] for artifact in report["artifacts"][-2:]] == [
        "migration_command",
        "doctor_command",
    ]


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
