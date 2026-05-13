from __future__ import annotations

from typing import Any

from ..contracts import RuntimeReadinessResponse


def _escape_prometheus_label_value(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _prometheus_metric_line(name: str, value: int | float, labels: dict[str, Any] | None = None) -> str:
    if labels:
        rendered = ",".join(
            f'{key}="{_escape_prometheus_label_value(label_value)}"'
            for key, label_value in labels.items()
            if label_value is not None
        )
        return f"{name}{{{rendered}}} {value}"
    return f"{name} {value}"


def _build_prometheus_metrics_payload(
    *,
    runtime_status: RuntimeReadinessResponse,
    trajectory_stats: dict[str, Any] | None,
    trajectory_available: bool,
    agent_governance_metrics: dict[str, int] | None = None,
    background_metrics: dict[str, int] | None = None,
    tool_runtime_metrics: dict[str, int] | None = None,
) -> str:
    lines = [
        "# HELP focus_agent_runtime_ready Whether the application runtime is ready to serve traffic.",
        "# TYPE focus_agent_runtime_ready gauge",
        _prometheus_metric_line("focus_agent_runtime_ready", 1 if runtime_status.ready else 0),
    ]
    lines.extend(
        [
            "# HELP focus_agent_runtime_build_info Build metadata for the running service.",
            "# TYPE focus_agent_runtime_build_info gauge",
            _prometheus_metric_line(
                "focus_agent_runtime_build_info",
                1,
                labels={
                    "version": runtime_status.app_version or "unknown",
                    "environment": runtime_status.environment or "unknown",
                    "deployment": runtime_status.deployment or "unknown",
                },
            ),
            "# HELP focus_agent_runtime_component_ready Per-component readiness for the running service.",
            "# TYPE focus_agent_runtime_component_ready gauge",
        ]
    )
    for check in runtime_status.checks:
        lines.append(
            _prometheus_metric_line(
                "focus_agent_runtime_component_ready",
                1 if check.ready else 0,
                labels={"component": check.name, "detail": check.detail or ""},
            )
        )

    lines.extend(
        [
            "# HELP focus_agent_trajectory_metrics_available Whether trajectory metrics were available for this scrape.",
            "# TYPE focus_agent_trajectory_metrics_available gauge",
            _prometheus_metric_line("focus_agent_trajectory_metrics_available", 1 if trajectory_available else 0),
        ]
    )
    if not trajectory_available or not trajectory_stats:
        lines.extend(_agent_governance_metric_lines(agent_governance_metrics or {}))
        lines.extend(_background_metric_lines(background_metrics or {}))
        lines.extend(_tool_runtime_metric_lines(tool_runtime_metrics or {}))
        return "\n".join(lines) + "\n"

    overview = trajectory_stats.get("overview") or {}
    lines.extend(
        [
            "# HELP focus_agent_trajectory_turn_count Total recorded trajectory turns in the selected scope.",
            "# TYPE focus_agent_trajectory_turn_count gauge",
            _prometheus_metric_line("focus_agent_trajectory_turn_count", int(overview.get("turn_count") or 0)),
            "# HELP focus_agent_trajectory_non_succeeded_count Total non-succeeded trajectory turns in the selected scope.",
            "# TYPE focus_agent_trajectory_non_succeeded_count gauge",
            _prometheus_metric_line(
                "focus_agent_trajectory_non_succeeded_count",
                int(overview.get("non_succeeded_count") or 0),
            ),
            "# HELP focus_agent_trajectory_avg_latency_ms Average end-to-end turn latency in milliseconds.",
            "# TYPE focus_agent_trajectory_avg_latency_ms gauge",
            _prometheus_metric_line(
                "focus_agent_trajectory_avg_latency_ms",
                float(overview.get("avg_latency_ms") or 0.0),
            ),
            "# HELP focus_agent_trajectory_max_latency_ms Maximum end-to-end turn latency in milliseconds.",
            "# TYPE focus_agent_trajectory_max_latency_ms gauge",
            _prometheus_metric_line(
                "focus_agent_trajectory_max_latency_ms",
                float(overview.get("max_latency_ms") or 0.0),
            ),
            "# HELP focus_agent_trajectory_total_tool_calls Total tool invocations across recorded turns.",
            "# TYPE focus_agent_trajectory_total_tool_calls gauge",
            _prometheus_metric_line(
                "focus_agent_trajectory_total_tool_calls",
                int(overview.get("total_tool_calls") or 0),
            ),
            "# HELP focus_agent_trajectory_total_fallback_uses Total fallback tool executions across recorded turns.",
            "# TYPE focus_agent_trajectory_total_fallback_uses gauge",
            _prometheus_metric_line(
                "focus_agent_trajectory_total_fallback_uses",
                int(overview.get("total_fallback_uses") or 0),
            ),
            "# HELP focus_agent_trajectory_turns_by_status Turn counts grouped by trajectory status.",
            "# TYPE focus_agent_trajectory_turns_by_status gauge",
        ]
    )
    for row in trajectory_stats.get("by_status") or []:
        lines.append(
            _prometheus_metric_line(
                "focus_agent_trajectory_turns_by_status",
                int(row.get("turn_count") or 0),
                labels={"status": row.get("key") or "unknown"},
            )
        )
    lines.extend(_agent_governance_metric_lines(agent_governance_metrics or {}))
    lines.extend(_background_metric_lines(background_metrics or {}))
    lines.extend(_tool_runtime_metric_lines(tool_runtime_metrics or {}))
    return "\n".join(lines) + "\n"


def _agent_governance_metric_lines(metrics: dict[str, int]) -> list[str]:
    return [
        "# HELP focus_agent_memory_promotion_count Total memory promotions observed in governance records.",
        "# TYPE focus_agent_memory_promotion_count gauge",
        _prometheus_metric_line("focus_agent_memory_promotion_count", int(metrics.get("memory_promotions") or 0)),
        "# HELP focus_agent_memory_conflict_count Total memory curator conflicts observed in governance records.",
        "# TYPE focus_agent_memory_conflict_count gauge",
        _prometheus_metric_line("focus_agent_memory_conflict_count", int(metrics.get("memory_conflicts") or 0)),
        "# HELP focus_agent_tool_router_denied_count Total denied tools observed in tool_route_plan records.",
        "# TYPE focus_agent_tool_router_denied_count gauge",
        _prometheus_metric_line("focus_agent_tool_router_denied_count", int(metrics.get("tool_router_denied") or 0)),
        "# HELP focus_agent_tool_router_enforced_count Total enforced tool_route_plan records.",
        "# TYPE focus_agent_tool_router_enforced_count gauge",
        _prometheus_metric_line("focus_agent_tool_router_enforced_count", int(metrics.get("tool_router_enforced") or 0)),
        "# HELP focus_agent_tool_intent_direct_answer_count Tool intent plans classified as direct_answer.",
        "# TYPE focus_agent_tool_intent_direct_answer_count gauge",
        _prometheus_metric_line("focus_agent_tool_intent_direct_answer_count", int(metrics.get("tool_intent_direct_answer") or 0)),
        "# HELP focus_agent_tool_intent_workspace_lookup_count Tool intent plans classified as workspace_lookup.",
        "# TYPE focus_agent_tool_intent_workspace_lookup_count gauge",
        _prometheus_metric_line("focus_agent_tool_intent_workspace_lookup_count", int(metrics.get("tool_intent_workspace_lookup") or 0)),
        "# HELP focus_agent_tool_intent_live_web_research_count Tool intent plans classified as live_web_research.",
        "# TYPE focus_agent_tool_intent_live_web_research_count gauge",
        _prometheus_metric_line("focus_agent_tool_intent_live_web_research_count", int(metrics.get("tool_intent_live_web_research") or 0)),
        "# HELP focus_agent_tool_intent_execution_count Tool intent plans classified as execution.",
        "# TYPE focus_agent_tool_intent_execution_count gauge",
        _prometheus_metric_line("focus_agent_tool_intent_execution_count", int(metrics.get("tool_intent_execution") or 0)),
        "# HELP focus_agent_tool_intent_first_tool_count Tool intent plans that selected a preferred first tool.",
        "# TYPE focus_agent_tool_intent_first_tool_count gauge",
        _prometheus_metric_line("focus_agent_tool_intent_first_tool_count", int(metrics.get("tool_intent_first_tool") or 0)),
        "# HELP focus_agent_tool_intent_carryover_count Tool intent plans recovered from pending tool actions.",
        "# TYPE focus_agent_tool_intent_carryover_count gauge",
        _prometheus_metric_line("focus_agent_tool_intent_carryover_count", int(metrics.get("tool_intent_carryover") or 0)),
        "# HELP focus_agent_temporal_anchor_forced_count Live turns that forced a current-time anchor before search.",
        "# TYPE focus_agent_temporal_anchor_forced_count gauge",
        _prometheus_metric_line("focus_agent_temporal_anchor_forced_count", int(metrics.get("temporal_anchor_forced") or 0)),
        "# HELP focus_agent_memory_quality_skipped_count Memory writes skipped by quality gates.",
        "# TYPE focus_agent_memory_quality_skipped_count gauge",
        _prometheus_metric_line("focus_agent_memory_quality_skipped_count", int(metrics.get("memory_quality_skipped") or 0)),
        "# HELP focus_agent_external_answer_missing_citation_count External answers flagged for missing citations.",
        "# TYPE focus_agent_external_answer_missing_citation_count gauge",
        _prometheus_metric_line("focus_agent_external_answer_missing_citation_count", int(metrics.get("external_answer_missing_citation") or 0)),
        "# HELP focus_agent_delegation_run_count Total delegated agent runs observed in governance records.",
        "# TYPE focus_agent_delegation_run_count gauge",
        _prometheus_metric_line("focus_agent_delegation_run_count", int(metrics.get("agent_delegation_runs") or 0)),
        "# HELP focus_agent_critic_reject_count Total critic rejection failures observed in governance records.",
        "# TYPE focus_agent_critic_reject_count gauge",
        _prometheus_metric_line("focus_agent_critic_reject_count", int(metrics.get("critic_rejects") or 0)),
        "# HELP focus_agent_review_pending_count Pending agent review queue items observed in governance records.",
        "# TYPE focus_agent_review_pending_count gauge",
        _prometheus_metric_line("focus_agent_review_pending_count", int(metrics.get("agent_review_pending") or 0)),
        "# HELP focus_agent_model_router_fallback_count Model Router fallback events observed in governance records.",
        "# TYPE focus_agent_model_router_fallback_count gauge",
        _prometheus_metric_line("focus_agent_model_router_fallback_count", int(metrics.get("model_router_fallback") or 0)),
        "# HELP focus_agent_failure_count Agent failure records observed in governance records.",
        "# TYPE focus_agent_failure_count gauge",
        _prometheus_metric_line("focus_agent_failure_count", int(metrics.get("agent_failures") or 0)),
        "# HELP focus_agent_context_artifact_ref_count Context Engineering artifact refs observed in governance records.",
        "# TYPE focus_agent_context_artifact_ref_count gauge",
        _prometheus_metric_line("focus_agent_context_artifact_ref_count", int(metrics.get("context_artifact_refs") or 0)),
        "# HELP focus_agent_context_over_budget_count Context Engineering over-budget decisions observed in governance records.",
        "# TYPE focus_agent_context_over_budget_count gauge",
        _prometheus_metric_line("focus_agent_context_over_budget_count", int(metrics.get("context_over_budget") or 0)),
        "# HELP focus_agent_task_ledger_task_count Agent Task Ledger tasks observed in governance records.",
        "# TYPE focus_agent_task_ledger_task_count gauge",
        _prometheus_metric_line("focus_agent_task_ledger_task_count", int(metrics.get("agent_task_ledger_tasks") or 0)),
        "# HELP focus_agent_delegated_artifact_count Delegated artifacts observed in governance records.",
        "# TYPE focus_agent_delegated_artifact_count gauge",
        _prometheus_metric_line("focus_agent_delegated_artifact_count", int(metrics.get("delegated_artifacts") or 0)),
        "# HELP focus_agent_critic_gate_rejected_count Rejected artifacts observed in critic gate results.",
        "# TYPE focus_agent_critic_gate_rejected_count gauge",
        _prometheus_metric_line("focus_agent_critic_gate_rejected_count", int(metrics.get("critic_gate_rejected") or 0)),
    ]


def _background_metric_lines(metrics: dict[str, int]) -> list[str]:
    return [
        "# HELP focus_agent_background_queue_depth Pending best-effort background tasks.",
        "# TYPE focus_agent_background_queue_depth gauge",
        _prometheus_metric_line(
            "focus_agent_background_queue_depth",
            int(metrics.get("queue_depth") or 0),
        ),
        "# HELP focus_agent_background_worker_active Active best-effort background workers.",
        "# TYPE focus_agent_background_worker_active gauge",
        _prometheus_metric_line(
            "focus_agent_background_worker_active",
            int(metrics.get("active_workers") or 0),
        ),
        "# HELP focus_agent_background_task_submitted_total Submitted best-effort background tasks.",
        "# TYPE focus_agent_background_task_submitted_total counter",
        _prometheus_metric_line(
            "focus_agent_background_task_submitted_total",
            int(metrics.get("submitted_total") or 0),
        ),
        "# HELP focus_agent_background_task_deduplicated_total Deduplicated best-effort background tasks.",
        "# TYPE focus_agent_background_task_deduplicated_total counter",
        _prometheus_metric_line(
            "focus_agent_background_task_deduplicated_total",
            int(metrics.get("deduplicated_total") or 0),
        ),
        "# HELP focus_agent_background_task_dropped_total Dropped best-effort background tasks.",
        "# TYPE focus_agent_background_task_dropped_total counter",
        _prometheus_metric_line(
            "focus_agent_background_task_dropped_total",
            int(metrics.get("dropped_total") or 0),
        ),
        "# HELP focus_agent_background_task_failed_total Failed best-effort background tasks.",
        "# TYPE focus_agent_background_task_failed_total counter",
        _prometheus_metric_line(
            "focus_agent_background_task_failed_total",
            int(metrics.get("failed_total") or 0),
        ),
        "# HELP focus_agent_background_job_durable_enabled Whether durable background job coordination is enabled.",
        "# TYPE focus_agent_background_job_durable_enabled gauge",
        _prometheus_metric_line(
            "focus_agent_background_job_durable_enabled",
            int(metrics.get("job_backend_durable") or 0),
        ),
        "# HELP focus_agent_background_job_status_count Durable background jobs grouped by status.",
        "# TYPE focus_agent_background_job_status_count gauge",
        _prometheus_metric_line(
            "focus_agent_background_job_status_count",
            int(metrics.get("job_pending_total") or 0),
            labels={"status": "pending"},
        ),
        _prometheus_metric_line(
            "focus_agent_background_job_status_count",
            int(metrics.get("job_running_total") or 0),
            labels={"status": "running"},
        ),
        _prometheus_metric_line(
            "focus_agent_background_job_status_count",
            int(metrics.get("job_succeeded_total") or 0),
            labels={"status": "succeeded"},
        ),
        _prometheus_metric_line(
            "focus_agent_background_job_status_count",
            int(metrics.get("job_failed_total") or 0),
            labels={"status": "failed"},
        ),
        _prometheus_metric_line(
            "focus_agent_background_job_status_count",
            int(metrics.get("job_released_total") or 0),
            labels={"status": "released"},
        ),
        "# HELP focus_agent_background_job_attempt_total Total durable background job attempts.",
        "# TYPE focus_agent_background_job_attempt_total counter",
        _prometheus_metric_line(
            "focus_agent_background_job_attempt_total",
            int(metrics.get("job_attempt_total") or 0),
        ),
        "# HELP focus_agent_background_durable_worker_active Active durable background job handlers.",
        "# TYPE focus_agent_background_durable_worker_active gauge",
        _prometheus_metric_line(
            "focus_agent_background_durable_worker_active",
            int(metrics.get("durable_worker_active") or 0),
        ),
        "# HELP focus_agent_background_durable_worker_claimed_total Durable jobs claimed by this worker.",
        "# TYPE focus_agent_background_durable_worker_claimed_total counter",
        _prometheus_metric_line(
            "focus_agent_background_durable_worker_claimed_total",
            int(metrics.get("durable_worker_claimed_total") or 0),
        ),
        "# HELP focus_agent_background_durable_worker_completed_total Durable jobs completed by this worker.",
        "# TYPE focus_agent_background_durable_worker_completed_total counter",
        _prometheus_metric_line(
            "focus_agent_background_durable_worker_completed_total",
            int(metrics.get("durable_worker_completed_total") or 0),
        ),
        "# HELP focus_agent_background_durable_worker_failed_total Durable jobs failed by this worker.",
        "# TYPE focus_agent_background_durable_worker_failed_total counter",
        _prometheus_metric_line(
            "focus_agent_background_durable_worker_failed_total",
            int(metrics.get("durable_worker_failed_total") or 0),
        ),
        "# HELP focus_agent_background_job_backend_error Whether the background job backend snapshot failed.",
        "# TYPE focus_agent_background_job_backend_error gauge",
        _prometheus_metric_line(
            "focus_agent_background_job_backend_error",
            int(metrics.get("job_backend_error") or 0),
        ),
    ]


def _tool_runtime_metric_lines(metrics: dict[str, int]) -> list[str]:
    return [
        "# HELP focus_agent_tool_timeout_active Timed-out read-only tool calls still running in the bounded executor.",
        "# TYPE focus_agent_tool_timeout_active gauge",
        _prometheus_metric_line(
            "focus_agent_tool_timeout_active",
            int(metrics.get("timeout_active") or 0),
        ),
        "# HELP focus_agent_tool_timeout_total Timed-out read-only tool calls observed by the bounded executor.",
        "# TYPE focus_agent_tool_timeout_total counter",
        _prometheus_metric_line(
            "focus_agent_tool_timeout_total",
            int(metrics.get("timeout_total") or 0),
        ),
        "# HELP focus_agent_tool_timeout_max_workers Maximum workers for timeout-wrapped tool calls.",
        "# TYPE focus_agent_tool_timeout_max_workers gauge",
        _prometheus_metric_line(
            "focus_agent_tool_timeout_max_workers",
            int(metrics.get("max_workers") or 0),
        ),
    ]




__all__ = [
    "_build_prometheus_metrics_payload",
]
