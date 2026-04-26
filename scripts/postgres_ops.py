#!/usr/bin/env python3
"""Write a Postgres operations report for release review."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Sequence


DEFAULT_REPORT_JSON = Path("reports/release-gate/postgres-ops.json")
DEFAULT_OPERATIONS: tuple[str, ...] = (
    "connectivity",
    "migration_table",
    "trajectory_write_readiness",
    "backup_restore_runbook",
)
PASS_STATUSES = {"pass", "passed", "success", "succeeded", "ok", "dry-run"}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _operation_passed(operation: dict[str, Any]) -> bool:
    status = str(operation.get("status") or "").lower()
    return bool(operation.get("passed", status in PASS_STATUSES))


def _planned_operation(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "dry-run",
        "passed": True,
        "detail": "planned Postgres production operation check",
    }


def _blocked_operation(name: str, detail: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "failed",
        "passed": False,
        "detail": detail,
    }


def build_report(
    *,
    database_uri: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if dry_run:
        operations = [_planned_operation(name) for name in DEFAULT_OPERATIONS]
    elif not database_uri:
        operations = [
            _blocked_operation(
                name,
                "--database-uri is required for live Postgres ops checks; use --dry-run to plan only",
            )
            for name in DEFAULT_OPERATIONS
        ]
    else:
        operations = [
            _blocked_operation(
                name,
                "live Postgres ops checks are intentionally report-only until a repo-local driver is wired",
            )
            for name in DEFAULT_OPERATIONS
        ]

    failed = [operation["name"] for operation in operations if not _operation_passed(operation)]
    errors = [str(operation["detail"]) for operation in operations if not _operation_passed(operation)]
    status = "dry-run" if dry_run else ("passed" if not failed else "failed")
    return {
        "artifacts": [],
        "checks": operations,
        "command": (
            "uv run python scripts/postgres_ops.py --dry-run"
            if dry_run
            else "uv run python scripts/postgres_ops.py --database-uri <redacted>"
        ),
        "errors": errors,
        "generated_at": _now(),
        "report_type": "postgres_ops",
        "status": status,
        "passed": not failed,
        "dry_run": dry_run,
        "database_uri_configured": bool(database_uri),
        "summary": {
            "total": len(operations),
            "passed": len(operations) - len(failed),
            "failed": len(failed),
            "failed_operations": failed,
        },
        "operations": operations,
    }


def write_report(path: str | Path, report: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Plan checks without connecting to Postgres.")
    parser.add_argument("--database-uri", help="Postgres URI for live operation checks.")
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON), help="Structured report path.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(database_uri=args.database_uri, dry_run=bool(args.dry_run))
    report_path = write_report(args.report_json, report)
    print(json.dumps({"status": report["status"], "report_json": str(report_path)}, indent=2))
    return 0 if bool(report["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
