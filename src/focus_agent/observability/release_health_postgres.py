"""Postgres release-health signals."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from focus_agent.observability.release_health_models import FAIL, PASS, ReleaseHealthSignal
from focus_agent.observability.release_health_utils import (
    failed_report_rows,
    failed_report_status,
    number,
)


def evaluate_postgres_migration_report(postgres_migration_report: Mapping[str, Any]) -> ReleaseHealthSignal:
    """Validate the machine-readable Postgres migration verification report."""
    status = str(postgres_migration_report.get("status") or "").lower()
    explicit_passed = postgres_migration_report.get("passed")
    migrations = postgres_migration_report.get("migrations")
    command = postgres_migration_report.get("command") or postgres_migration_report.get("verification_command")
    errors = postgres_migration_report.get("errors")
    if not isinstance(errors, list):
        errors = []
    migration_count = (
        len(migrations)
        if isinstance(migrations, list)
        else int(number(postgres_migration_report.get("migration_count")))
    )
    details = {
        "command": str(command) if command else "",
        "errors": [str(error) for error in errors],
        "migration_count": migration_count,
        "status": status or None,
    }
    if not command and migration_count <= 0:
        return ReleaseHealthSignal(
            key="postgres_migration_verification",
            status=FAIL,
            summary="postgres migration verification has no report or command evidence",
            details=details,
        )
    if explicit_passed is False or status in {"fail", "failed", "error"} or errors:
        return ReleaseHealthSignal(
            key="postgres_migration_verification",
            status=FAIL,
            summary="postgres migration verification failed",
            details=details,
        )
    return ReleaseHealthSignal(
        key="postgres_migration_verification",
        status=PASS,
        summary="postgres migration verification passed",
        details=details,
    )


def evaluate_postgres_ops_report(postgres_ops_report: Mapping[str, Any]) -> ReleaseHealthSignal:
    """Validate a Postgres operations report collected by deployment jobs."""
    operations = postgres_ops_report.get("operations")
    rows = [row for row in operations if isinstance(row, Mapping)] if isinstance(operations, list) else []
    if not rows:
        checks = postgres_ops_report.get("checks")
        rows = [row for row in checks if isinstance(row, Mapping)] if isinstance(checks, list) else []
    failures = failed_report_rows(rows)
    status = str(postgres_ops_report.get("status") or "").lower()
    explicit_passed = postgres_ops_report.get("passed")
    details = {
        "operations": len(rows),
        "failed_operations": failures,
        "status": status or None,
    }
    if not rows:
        return ReleaseHealthSignal(
            key="postgres_ops_report",
            status=FAIL,
            summary="postgres ops report has no operation coverage",
            details=details,
        )
    if explicit_passed is False or failed_report_status(status) or failures:
        return ReleaseHealthSignal(
            key="postgres_ops_report",
            status=FAIL,
            summary="postgres ops report failed",
            details=details,
        )
    return ReleaseHealthSignal(
        key="postgres_ops_report",
        status=PASS,
        summary="postgres ops report passed",
        details=details,
    )
