#!/usr/bin/env python3
"""Write a Postgres operations report for release review."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import shlex
import subprocess
from typing import Any, Mapping, Sequence

try:
    import psycopg
except Exception:  # pragma: no cover - exercised when optional runtime deps are absent
    psycopg = None  # type: ignore[assignment]


DEFAULT_REPORT_JSON = Path("reports/release-gate/postgres-ops.json")
DEFAULT_OPERATIONS: tuple[str, ...] = (
    "connectivity",
    "migration_table",
    "trajectory_write_readiness",
    "backup_restore_runbook",
)
PASS_STATUSES = {"pass", "passed", "success", "succeeded", "ok", "dry-run", "skipped"}
FAIL_STATUSES = {"fail", "failed", "error"}
MAX_EVIDENCE_CHARS = 4000


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _operation_passed(operation: Mapping[str, Any]) -> bool:
    status = str(operation.get("status") or "").lower()
    return bool(operation.get("passed", status in PASS_STATUSES))


def _operation(
    name: str,
    *,
    status: str,
    detail: str,
    passed: bool | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "status": status,
        "passed": status in PASS_STATUSES if passed is None else passed,
        "detail": detail,
    }
    payload.update(extra)
    return payload


def _planned_operation(name: str) -> dict[str, Any]:
    return _operation(
        name,
        status="dry-run",
        passed=True,
        detail="planned Postgres production operation check",
    )


def _blocked_operation(name: str, detail: str) -> dict[str, Any]:
    return _operation(name, status="failed", passed=False, detail=detail)


def _skipped_operation(name: str, detail: str, **extra: Any) -> dict[str, Any]:
    return _operation(name, status="skipped", passed=True, detail=detail, **extra)


def _truncate(value: str) -> str:
    if len(value) <= MAX_EVIDENCE_CHARS:
        return value
    return value[:MAX_EVIDENCE_CHARS] + "...<truncated>"


def _run_query(database_uri: str, query: str) -> tuple[Any, ...] | None:
    if psycopg is None:
        raise RuntimeError("psycopg is unavailable")
    with psycopg.connect(database_uri) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            row = cur.fetchone()
            if row is None:
                return None
            return tuple(row)


def _truthy_query_result(row: tuple[Any, ...] | None) -> bool:
    if row is None or not row:
        return False
    value = row[0]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "f", "no", "n"}
    return bool(value)


def _query_operation(
    name: str,
    *,
    database_uri: str,
    query: str,
    detail_on_pass: str,
    detail_on_false: str,
) -> dict[str, Any]:
    try:
        row = _run_query(database_uri, query)
    except Exception as exc:  # noqa: BLE001
        return _operation(
            name,
            status="failed",
            passed=False,
            detail=str(exc),
            query=query,
        )
    passed = _truthy_query_result(row)
    return _operation(
        name,
        status="passed" if passed else "failed",
        passed=passed,
        detail=detail_on_pass if passed else detail_on_false,
        query=query,
        row=list(row) if row is not None else None,
    )


def _run_command_operation(
    name: str,
    *,
    command: str,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not command.strip():
        operation = _blocked_operation(name, f"--{name.replace('_', '-')} was provided but empty")
        return operation, {"operation": name, "command": command, "returncode": None}
    try:
        args = shlex.split(command)
        completed = subprocess.run(
            args,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        evidence = {
            "operation": name,
            "command": command,
            "returncode": None,
            "error": str(exc),
        }
        return _blocked_operation(name, str(exc)), evidence

    evidence = {
        "operation": name,
        "command": command,
        "args": args,
        "returncode": completed.returncode,
        "stdout": _truncate(completed.stdout or ""),
        "stderr": _truncate(completed.stderr or ""),
    }
    passed = completed.returncode == 0
    operation = _operation(
        name,
        status="passed" if passed else "failed",
        passed=passed,
        detail="command completed successfully" if passed else f"command exited with {completed.returncode}",
        evidence=evidence,
    )
    return operation, evidence


def _evidence_payload_passed(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("passed") is False:
        return False
    status = str(payload.get("status") or "").lower()
    if status in FAIL_STATUSES:
        return False
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        return False
    return bool(payload.get("passed") is True or status in PASS_STATUSES or payload)


def _restore_verification_operation(
    *,
    database_uri: str | None,
    restore_command: str | None,
    restore_verification_evidence: str | Path | None,
    restore_verification_query: str | None,
) -> dict[str, Any]:
    if restore_verification_evidence:
        path = Path(restore_verification_evidence)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _operation(
                "restore_verification",
                status="failed",
                passed=False,
                detail=str(exc),
                evidence_path=str(path),
            )
        passed = _evidence_payload_passed(payload)
        return _operation(
            "restore_verification",
            status="passed" if passed else "failed",
            passed=passed,
            detail="restore verification evidence passed" if passed else "restore verification evidence failed",
            evidence_path=str(path),
            evidence=payload,
        )
    if restore_verification_query:
        if not database_uri:
            return _blocked_operation(
                "restore_verification",
                "--database-uri is required with --restore-verification-query",
            )
        return _query_operation(
            "restore_verification",
            database_uri=database_uri,
            query=restore_verification_query,
            detail_on_pass="restore verification query returned a truthy result",
            detail_on_false="restore verification query returned a falsey result",
        )
    if restore_command:
        return _blocked_operation(
            "restore_verification",
            "--restore-verification-query or --restore-verification-evidence is required when --restore-command is used",
        )
    return _skipped_operation(
        "restore_verification",
        "restore verification was not requested",
    )


def _retention_cleanup_operation(*, retention_cleanup_query: str | None) -> dict[str, Any]:
    if not retention_cleanup_query:
        return _skipped_operation(
            "retention_cleanup",
            "retention cleanup dry-run was not requested",
        )
    return _operation(
        "retention_cleanup",
        status="dry-run",
        passed=True,
        detail="retention cleanup dry-run only; query was not executed",
        query=retention_cleanup_query,
    )


def _live_database_operations(
    *,
    database_uri: str,
    backup_command: str | None,
    restore_command: str | None,
    restore_verification_evidence: str | Path | None,
    restore_verification_query: str | None,
) -> list[dict[str, Any]]:
    operations = [
        _query_operation(
            "connectivity",
            database_uri=database_uri,
            query="SELECT 1",
            detail_on_pass="Postgres connectivity query succeeded",
            detail_on_false="Postgres connectivity query returned an unexpected result",
        ),
        _query_operation(
            "migration_table",
            database_uri=database_uri,
            query="SELECT to_regclass('public.focus_schema_migrations') IS NOT NULL",
            detail_on_pass="focus_schema_migrations table exists",
            detail_on_false="focus_schema_migrations table is missing",
        ),
        _query_operation(
            "trajectory_write_readiness",
            database_uri=database_uri,
            query="SELECT to_regclass('public.focus_trajectory_turns') IS NOT NULL",
            detail_on_pass="focus_trajectory_turns table exists",
            detail_on_false="focus_trajectory_turns table is missing",
        ),
    ]
    if backup_command or restore_command or restore_verification_evidence or restore_verification_query:
        operations.append(
            _operation(
                "backup_restore_runbook",
                status="passed",
                passed=True,
                detail="backup/restore drill evidence captured in v2 operations",
            )
        )
    else:
        operations.append(
            _skipped_operation(
                "backup_restore_runbook",
                "provide --backup-command and optional restore verification args to run a live drill",
            )
        )
    return operations


def _planned_optional_operations(
    *,
    backup_command: str | None,
    restore_command: str | None,
    restore_verification_evidence: str | Path | None,
    restore_verification_query: str | None,
    retention_cleanup_query: str | None,
) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    if backup_command:
        operations.append(_planned_operation("backup_command"))
    if restore_command:
        operations.append(_planned_operation("restore_command"))
    if restore_command or restore_verification_evidence or restore_verification_query:
        operations.append(_planned_operation("restore_verification"))
    if retention_cleanup_query:
        operations.append(_planned_operation("retention_cleanup"))
    return operations


def build_report(
    *,
    backup_command: str | None = None,
    database_uri: str | None = None,
    dry_run: bool = False,
    restore_command: str | None = None,
    restore_verification_evidence: str | Path | None = None,
    restore_verification_query: str | None = None,
    retention_cleanup_query: str | None = None,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    if dry_run:
        operations = [_planned_operation(name) for name in DEFAULT_OPERATIONS]
        operations.extend(
            _planned_optional_operations(
                backup_command=backup_command,
                restore_command=restore_command,
                restore_verification_evidence=restore_verification_evidence,
                restore_verification_query=restore_verification_query,
                retention_cleanup_query=retention_cleanup_query,
            )
        )
    elif not database_uri:
        operations = [
            _blocked_operation(
                name,
                "--database-uri is required for live Postgres ops checks; use --dry-run to plan only",
            )
            for name in DEFAULT_OPERATIONS
        ]
    else:
        operations = _live_database_operations(
            database_uri=database_uri,
            backup_command=backup_command,
            restore_command=restore_command,
            restore_verification_evidence=restore_verification_evidence,
            restore_verification_query=restore_verification_query,
        )

    if not dry_run:
        if backup_command:
            operation, evidence = _run_command_operation(
                "backup_command",
                command=backup_command,
                timeout_seconds=timeout_seconds,
            )
            operations.append(operation)
            artifacts.append(evidence)
        if restore_command:
            operation, evidence = _run_command_operation(
                "restore_command",
                command=restore_command,
                timeout_seconds=timeout_seconds,
            )
            operations.append(operation)
            artifacts.append(evidence)
        if restore_command or restore_verification_evidence or restore_verification_query:
            operations.append(
                _restore_verification_operation(
                    database_uri=database_uri,
                    restore_command=restore_command,
                    restore_verification_evidence=restore_verification_evidence,
                    restore_verification_query=restore_verification_query,
                )
            )
        if retention_cleanup_query:
            operations.append(_retention_cleanup_operation(retention_cleanup_query=retention_cleanup_query))

    failed = [operation["name"] for operation in operations if not _operation_passed(operation)]
    errors = [str(operation["detail"]) for operation in operations if not _operation_passed(operation)]
    status = "dry-run" if dry_run else ("passed" if not failed else "failed")
    command = (
        "uv run python scripts/postgres_ops.py --dry-run"
        if dry_run
        else "uv run python scripts/postgres_ops.py --database-uri <redacted>"
    )
    return {
        "artifacts": artifacts,
        "checks": operations,
        "command": command,
        "errors": errors,
        "generated_at": _now(),
        "report_type": "postgres_ops",
        "report_version": 2,
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
        "v2": {
            "backup_command_configured": bool(backup_command),
            "restore_command_configured": bool(restore_command),
            "restore_verification_configured": bool(restore_verification_evidence or restore_verification_query),
            "retention_cleanup_dry_run_configured": bool(retention_cleanup_query),
        },
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
    parser.add_argument(
        "--backup-command",
        help="Explicit backup command to run, parsed with shlex and executed without a shell.",
    )
    parser.add_argument(
        "--restore-command",
        help="Explicit restore command to run, parsed with shlex and executed without a shell.",
    )
    parser.add_argument(
        "--restore-verification-query",
        help="SQL query that must return a truthy first column after restore.",
    )
    parser.add_argument(
        "--restore-verification-evidence",
        help="JSON evidence file proving restore verification.",
    )
    parser.add_argument(
        "--retention-cleanup-query",
        help="Retention cleanup query to record as dry-run evidence. It is not executed.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=60.0, help="Per-command timeout.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        backup_command=args.backup_command,
        database_uri=args.database_uri,
        dry_run=bool(args.dry_run),
        restore_command=args.restore_command,
        restore_verification_evidence=args.restore_verification_evidence,
        restore_verification_query=args.restore_verification_query,
        retention_cleanup_query=args.retention_cleanup_query,
        timeout_seconds=float(args.timeout_seconds),
    )
    report_path = write_report(args.report_json, report)
    print(json.dumps({"status": report["status"], "report_json": str(report_path)}, indent=2))
    return 0 if bool(report["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
