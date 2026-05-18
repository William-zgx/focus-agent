"""Production smoke release-health signals."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from focus_agent.observability.release_health_models import FAIL, PASS, ReleaseHealthSignal
from focus_agent.observability.release_health_utils import failed_report_rows, failed_report_status


def evaluate_production_smoke_report(production_smoke_report: Mapping[str, Any]) -> ReleaseHealthSignal:
    """Validate a production endpoint smoke report collected by deployment jobs."""
    checks = production_smoke_report.get("checks")
    rows = [row for row in checks if isinstance(row, Mapping)] if isinstance(checks, list) else []
    failures = failed_report_rows(rows)
    status = str(production_smoke_report.get("status") or "").lower()
    explicit_passed = production_smoke_report.get("passed")
    details = {
        "checks": len(rows),
        "failed_checks": failures,
        "status": status or None,
    }
    if not rows:
        return ReleaseHealthSignal(
            key="production_smoke_report",
            status=FAIL,
            summary="production smoke report has no probe coverage",
            details=details,
        )
    if explicit_passed is False or failed_report_status(status) or failures:
        return ReleaseHealthSignal(
            key="production_smoke_report",
            status=FAIL,
            summary="production smoke report failed",
            details=details,
        )
    return ReleaseHealthSignal(
        key="production_smoke_report",
        status=PASS,
        summary="production smoke report passed",
        details=details,
    )
