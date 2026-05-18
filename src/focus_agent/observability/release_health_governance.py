"""Agent governance release-health signals."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from focus_agent.observability.release_health_models import FAIL, PASS, WARN, ReleaseHealthSignal


def evaluate_governance_quality_report(
    governance_quality_report: Mapping[str, Any],
) -> ReleaseHealthSignal:
    """Validate Agent Governance quality thresholds produced by scripts/agent_governance_report.py."""
    summary = (
        governance_quality_report.get("summary")
        if isinstance(governance_quality_report.get("summary"), Mapping)
        else {}
    )
    signals = [
        signal
        for signal in governance_quality_report.get("signals", [])
        if isinstance(signal, Mapping)
    ]
    blocking_signals = _governance_signal_keys(
        signals,
        summary_values=summary.get("blocking_signals"),
        statuses={"block", "blocking", "fail", "failed"},
        severities={"blocking"},
    )
    warning_signals = _governance_signal_keys(
        signals,
        summary_values=summary.get("warning_signals"),
        statuses={"warn", "warning"},
        severities={"warning"},
    )
    report_status = str(
        summary.get("status") or governance_quality_report.get("status") or ""
    ).lower()
    details = {
        "status": report_status or None,
        "blocking_signals": blocking_signals,
        "warning_signals": warning_signals,
        "thresholds": governance_quality_report.get("thresholds")
        if isinstance(governance_quality_report.get("thresholds"), Mapping)
        else {},
    }
    if blocking_signals or report_status in {"failed", "blocked", "block"}:
        return ReleaseHealthSignal(
            key="agent_governance_quality",
            status=FAIL,
            summary="agent governance quality report has blocking threshold violations",
            details=details,
        )
    if warning_signals or report_status in {"warning", "warn"}:
        return ReleaseHealthSignal(
            key="agent_governance_quality",
            status=WARN,
            summary="agent governance quality report has warning threshold violations",
            details=details,
        )
    return ReleaseHealthSignal(
        key="agent_governance_quality",
        status=PASS,
        summary="agent governance quality report passed",
        details=details,
    )


def _governance_signal_keys(
    signals: Iterable[Mapping[str, Any]],
    *,
    summary_values: Any,
    statuses: set[str],
    severities: set[str],
) -> list[str]:
    keys: list[str] = []
    for signal in signals:
        status = str(signal.get("status") or "").lower()
        severity = str(signal.get("severity") or "").lower()
        if status in statuses or severity in severities:
            keys.append(str(signal.get("key") or "unknown"))
    if isinstance(summary_values, (list, tuple, set)):
        keys.extend(str(value) for value in summary_values)
    return sorted(set(keys))
