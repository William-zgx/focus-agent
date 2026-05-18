"""Release-health gate facade built from domain-specific signal evaluators."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from focus_agent.observability.release_health_alerts import evaluate_alert_report
from focus_agent.observability.release_health_context import evaluate_context_probe
from focus_agent.observability.release_health_governance import evaluate_governance_quality_report
from focus_agent.observability.release_health_models import (
    FAIL,
    PASS,
    WARN,
    ReleaseHealthReport,
    ReleaseHealthSignal,
    ReleaseHealthThresholds,
)
from focus_agent.observability.release_health_otel import evaluate_otel_smoke_report
from focus_agent.observability.release_health_postgres import (
    evaluate_postgres_migration_report,
    evaluate_postgres_ops_report,
)
from focus_agent.observability.release_health_production import evaluate_production_smoke_report
from focus_agent.observability.release_health_replay import (
    eval_regression_signal,
    evaluate_replay_gate,
)
from focus_agent.observability.release_health_runtime import (
    evaluate_runtime_ready,
    evaluate_trajectory_recorder_ready,
)
from focus_agent.observability.release_health_trajectory import (
    evaluate_chat_failure_rate,
    evaluate_tool_fallback_spike,
)

__all__ = [
    "FAIL",
    "PASS",
    "WARN",
    "ReleaseHealthReport",
    "ReleaseHealthSignal",
    "ReleaseHealthThresholds",
    "evaluate_alert_report",
    "evaluate_chat_failure_rate",
    "evaluate_context_probe",
    "evaluate_governance_quality_report",
    "evaluate_otel_smoke_report",
    "evaluate_postgres_migration_report",
    "evaluate_postgres_ops_report",
    "evaluate_production_smoke_report",
    "evaluate_release_health",
    "evaluate_replay_gate",
    "evaluate_runtime_ready",
    "evaluate_tool_fallback_spike",
    "evaluate_trajectory_recorder_ready",
]


def evaluate_release_health(
    *,
    runtime_status: Any,
    trajectory_stats: Mapping[str, Any] | None = None,
    baseline_trajectory_stats: Mapping[str, Any] | None = None,
    replay_comparisons: Iterable[Mapping[str, Any]] | None = None,
    alert_report: Mapping[str, Any] | None = None,
    postgres_migration_report: Mapping[str, Any] | None = None,
    production_smoke_report: Mapping[str, Any] | None = None,
    postgres_ops_report: Mapping[str, Any] | None = None,
    otel_smoke_report: Mapping[str, Any] | None = None,
    governance_quality_report: Mapping[str, Any] | None = None,
    eval_regressions: Iterable[str] | None = None,
    thresholds: ReleaseHealthThresholds | None = None,
) -> ReleaseHealthReport:
    """Evaluate the release gate signals that can be derived without an LLM."""
    policy = thresholds or ReleaseHealthThresholds()
    signals = [
        evaluate_runtime_ready(runtime_status),
        evaluate_trajectory_recorder_ready(runtime_status),
        evaluate_chat_failure_rate(trajectory_stats or {}, thresholds=policy),
        evaluate_tool_fallback_spike(
            trajectory_stats or {},
            baseline_stats=baseline_trajectory_stats,
            thresholds=policy,
        ),
    ]

    regression_items = list(eval_regressions or [])
    if replay_comparisons is not None:
        signals.append(evaluate_replay_gate(replay_comparisons))
    elif regression_items:
        signals.append(eval_regression_signal(regression_items))
    if alert_report is not None:
        signals.append(evaluate_alert_report(alert_report))
    if postgres_migration_report is not None:
        signals.append(evaluate_postgres_migration_report(postgres_migration_report))
    if production_smoke_report is not None:
        signals.append(evaluate_production_smoke_report(production_smoke_report))
    if postgres_ops_report is not None:
        signals.append(evaluate_postgres_ops_report(postgres_ops_report))
    if otel_smoke_report is not None:
        signals.append(evaluate_otel_smoke_report(otel_smoke_report))
    if governance_quality_report is not None:
        signals.append(evaluate_governance_quality_report(governance_quality_report))

    return ReleaseHealthReport(signals=tuple(signals))


def _eval_regression_signal(regressions: list[str]) -> ReleaseHealthSignal:
    return eval_regression_signal(regressions)
