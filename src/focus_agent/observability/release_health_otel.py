"""OpenTelemetry smoke release-health signals."""

from __future__ import annotations

from typing import Any, Mapping

from focus_agent.observability.release_health_models import FAIL, PASS, ReleaseHealthSignal
from focus_agent.observability.release_health_utils import failed_report_rows, failed_report_status, number


def evaluate_otel_smoke_report(otel_smoke_report: Mapping[str, Any]) -> ReleaseHealthSignal:
    """Validate an OpenTelemetry smoke report collected by deployment jobs."""
    checks = otel_smoke_report.get("checks")
    rows = [row for row in checks if isinstance(row, Mapping)] if isinstance(checks, list) else []
    failures = failed_report_rows(rows)
    status = str(otel_smoke_report.get("status") or "").lower()
    explicit_passed = otel_smoke_report.get("passed")
    summary = otel_smoke_report.get("summary") if isinstance(otel_smoke_report.get("summary"), Mapping) else {}
    spans = int(number(summary.get("spans")))
    if spans <= 0 and isinstance(otel_smoke_report.get("spans"), list):
        spans = len(otel_smoke_report["spans"])
    details = {
        "checks": len(rows),
        "failed_checks": failures,
        "spans": spans,
        "status": status or None,
    }
    if not rows and spans <= 0:
        return ReleaseHealthSignal(
            key="otel_smoke_report",
            status=FAIL,
            summary="otel smoke report has no check or span coverage",
            details=details,
        )
    if explicit_passed is False or failed_report_status(status) or failures:
        return ReleaseHealthSignal(
            key="otel_smoke_report",
            status=FAIL,
            summary="otel smoke report failed",
            details=details,
        )
    return ReleaseHealthSignal(
        key="otel_smoke_report",
        status=PASS,
        summary="otel smoke report passed",
        details=details,
    )
