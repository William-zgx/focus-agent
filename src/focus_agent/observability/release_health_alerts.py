"""Alert report release-health signals."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from focus_agent.observability.release_health_models import FAIL, PASS, ReleaseHealthSignal
from focus_agent.observability.release_health_utils import number


def evaluate_alert_report(alert_report: Mapping[str, Any]) -> ReleaseHealthSignal:
    """Validate an executable alert-rules report collected by the deployment job."""
    rules = alert_report.get("rules")
    alerts = alert_report.get("alerts")
    summary = (
        alert_report.get("summary") if isinstance(alert_report.get("summary"), Mapping) else {}
    )
    rules_checked = int(number(summary.get("rules_checked")))
    if isinstance(rules, list):
        rules_checked = max(rules_checked, len(rules))

    firing_alerts: list[str] = []
    for index, alert in enumerate(alerts if isinstance(alerts, list) else []):
        if not isinstance(alert, Mapping):
            continue
        state = str(alert.get("state") or alert.get("status") or "").lower()
        active = alert.get("active")
        if state in {"firing", "alerting", "critical", "page"} or active is True:
            firing_alerts.append(
                str(alert.get("name") or alert.get("alert") or f"alert-{index + 1}")
            )

    status = str(alert_report.get("status") or "").lower()
    explicit_passed = alert_report.get("passed")
    details = {
        "firing_alerts": firing_alerts,
        "rules_checked": rules_checked,
        "status": status or None,
    }
    if rules_checked <= 0:
        return ReleaseHealthSignal(
            key="alert_rules_report",
            status=FAIL,
            summary="alert rules report has no executable rule coverage",
            details=details,
        )
    if explicit_passed is False or status in {"fail", "failed", "error"} or firing_alerts:
        return ReleaseHealthSignal(
            key="alert_rules_report",
            status=FAIL,
            summary="alert rules report contains firing or failed alerts",
            details=details,
        )
    return ReleaseHealthSignal(
        key="alert_rules_report",
        status=PASS,
        summary="alert rules report passed",
        details=details,
    )
