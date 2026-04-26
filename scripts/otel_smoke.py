#!/usr/bin/env python3
"""Write an OpenTelemetry smoke report for release review."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any, Sequence


DEFAULT_REPORT_JSON = Path("reports/release-gate/otel-smoke.json")
DEFAULT_SERVICE_NAME = "focus-agent"
PASS_STATUSES = {"pass", "passed", "success", "succeeded", "ok", "dry-run"}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _check_passed(check: dict[str, Any]) -> bool:
    status = str(check.get("status") or "").lower()
    return bool(check.get("passed", status in PASS_STATUSES))


def _check(name: str, *, status: str, detail: str, passed: bool | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "passed": status in PASS_STATUSES if passed is None else passed,
        "detail": detail,
    }


def build_report(
    *,
    endpoint: str | None = None,
    service_name: str = DEFAULT_SERVICE_NAME,
    dry_run: bool = False,
) -> dict[str, Any]:
    resolved_endpoint = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if dry_run:
        checks = [
            _check("service_name", status="dry-run", detail=f"planned service.name={service_name}"),
            _check(
                "otlp_endpoint",
                status="dry-run",
                detail=f"planned OTLP endpoint={resolved_endpoint or '<from deployment env>'}",
            ),
            _check("span_export", status="dry-run", detail="planned synthetic span export"),
        ]
        spans = [{"name": "focus_agent.release.otel_smoke", "status": "dry-run"}]
    else:
        checks = [
            _check("service_name", status="passed", detail=f"service.name={service_name}"),
            _check(
                "otlp_endpoint",
                status="passed" if resolved_endpoint else "failed",
                detail=resolved_endpoint or "OTEL_EXPORTER_OTLP_ENDPOINT is not configured",
            ),
            _check(
                "span_export",
                status="failed",
                detail="live span export requires deployment collector credentials",
                passed=False,
            ),
        ]
        spans = []

    failed = [check["name"] for check in checks if not _check_passed(check)]
    status = "dry-run" if dry_run else ("passed" if not failed else "failed")
    return {
        "generated_at": _now(),
        "report_type": "otel_smoke",
        "status": status,
        "passed": not failed,
        "dry_run": dry_run,
        "service_name": service_name,
        "endpoint": resolved_endpoint,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "failed_checks": failed,
            "spans": len(spans),
        },
        "checks": checks,
        "spans": spans,
    }


def write_report(path: str | Path, report: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Plan OTel checks without exporting a span.")
    parser.add_argument("--endpoint", help="OTLP endpoint. Defaults to OTEL_EXPORTER_OTLP_ENDPOINT.")
    parser.add_argument("--service-name", default=DEFAULT_SERVICE_NAME, help="OTel service.name value.")
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON), help="Structured report path.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        endpoint=args.endpoint,
        service_name=args.service_name,
        dry_run=bool(args.dry_run),
    )
    report_path = write_report(args.report_json, report)
    print(json.dumps({"status": report["status"], "report_json": str(report_path)}, indent=2))
    return 0 if bool(report["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
