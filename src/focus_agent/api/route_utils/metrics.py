"""Prometheus metrics helpers for API routes."""

from __future__ import annotations

from typing import Any, Sequence

from ..contracts import RuntimeReadinessResponse


def escape_prometheus_label_value(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def prometheus_metric_line(name: str, value: int | float, labels: dict[str, Any] | None = None) -> str:
    if labels:
        rendered = ",".join(
            f'{key}="{escape_prometheus_label_value(label_value)}"'
            for key, label_value in labels.items()
            if label_value is not None
        )
        return f"{name}{{{rendered}}} {value}"
    return f"{name} {value}"


def build_prometheus_metrics_payload(
    *,
    runtime_status: RuntimeReadinessResponse,
    trajectory_stats: dict[str, Any] | None,
    trajectory_available: bool,
    agent_governance_metrics: dict[str, int] | None = None,
) -> str:
    lines = [
        "# HELP focus_agent_runtime_ready Whether the application runtime is ready to serve traffic.",
        "# TYPE focus_agent_runtime_ready gauge",
        prometheus_metric_line("focus_agent_runtime_ready", 1 if runtime_status.ready else 0),
    ]
    lines.extend(
        [
            "# HELP focus_agent_runtime_build_info Build metadata for the running service.",
            "# TYPE focus_agent_runtime_build_info gauge",
            prometheus_metric_line(
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
            prometheus_metric_line(
                "focus_agent_runtime_component_ready",
                1 if check.ready else 0,
                labels={"component": check.name, "detail": check.detail or ""},
            )
        )

    lines.extend(
        [
            "# HELP focus_agent_trajectory_metrics_available Whether trajectory metrics were available for this scrape.",
            "# TYPE focus_agent_trajectory_metrics_available gauge",
            prometheus_metric_line("focus_agent_trajectory_metrics_available", 1 if trajectory_available else 0),
        ]
    )
    if not trajectory_available or not trajectory_stats:
        lines.extend(agent_governance_metric_lines(agent_governance_metrics or {}))
        return "\n".join(lines) + "\n"

    overview = trajectory_stats.get("overview") or {}
    lines.extend(
        [
            "# HELP focus_agent_trajectory_turn_count Total recorded trajectory turns in the selected scope.",
            "# TYPE focus_agent_trajectory_turn_count gauge",
            prometheus_metric_line("focus_agent_trajectory_turn_count", int(overview.get("turn_count") or 0)),
            "# HELP focus_agent_trajectory_non_succeeded_count Total non-succeeded trajectory turns in the selected scope.",
            "# TYPE focus_agent_trajectory_non_succeeded_count gauge",
            prometheus_metric_line(
                "focus_agent_trajectory_non_succeeded_count",
                int(overview.get("non_succeeded_count") or 0),
            ),
            "# HELP focus_agent_trajectory_avg_latency_ms Average end-to-end turn latency in milliseconds.",
            "# TYPE focus_agent_trajectory_avg_latency_ms gauge",
            prometheus_metric_line(
                "focus_agent_trajectory_avg_latency_ms",
                float(overview.get("avg_latency_ms") or 0.0),
            ),
            "# HELP focus_agent_trajectory_max_latency_ms Maximum end-to-end turn latency in milliseconds.",
            "# TYPE focus_agent_trajectory_max_latency_ms gauge",
            prometheus_metric_line(
                "focus_agent_trajectory_max_latency_ms",
                float(overview.get("max_latency_ms") or 0.0),
            ),
            "# HELP focus_agent_trajectory_total_tool_calls Total tool invocations across recorded turns.",
            "# TYPE focus_agent_trajectory_total_tool_calls gauge",
            prometheus_metric_line(
                "focus_agent_trajectory_total_tool_calls",
                int(overview.get("total_tool_calls") or 0),
            ),
            "# HELP focus_agent_trajectory_total_fallback_uses Total fallback tool executions across recorded turns.",
            "# TYPE focus_agent_trajectory_total_fallback_uses gauge",
            prometheus_metric_line(
                "focus_agent_trajectory_total_fallback_uses",
                int(overview.get("total_fallback_uses") or 0),
            ),
            "# HELP focus_agent_trajectory_turns_by_status Turn counts grouped by trajectory status.",
            "# TYPE focus_agent_trajectory_turns_by_status gauge",
        ]
    )
    for row in trajectory_stats.get("by_status") or []:
        lines.append(
            prometheus_metric_line(
                "focus_agent_trajectory_turns_by_status",
                int(row.get("turn_count") or 0),
                labels={"status": row.get("key") or "unknown"},
            )
        )
    lines.extend(agent_governance_metric_lines(agent_governance_metrics or {}))
    return "\n".join(lines) + "\n"


def agent_governance_metric_lines(metrics: dict[str, int]) -> list[str]:
    return [
        "# HELP focus_agent_memory_promotion_count Total memory promotions observed in trajectory plan_meta.",
        "# TYPE focus_agent_memory_promotion_count gauge",
        prometheus_metric_line("focus_agent_memory_promotion_count", int(metrics.get("memory_promotions") or 0)),
        "# HELP focus_agent_memory_conflict_count Total memory curator conflicts observed in trajectory plan_meta.",
        "# TYPE focus_agent_memory_conflict_count gauge",
        prometheus_metric_line("focus_agent_memory_conflict_count", int(metrics.get("memory_conflicts") or 0)),
        "# HELP focus_agent_tool_router_denied_count Total denied tools observed in tool_route_plan records.",
        "# TYPE focus_agent_tool_router_denied_count gauge",
        prometheus_metric_line("focus_agent_tool_router_denied_count", int(metrics.get("tool_router_denied") or 0)),
        "# HELP focus_agent_tool_router_enforced_count Total enforced tool_route_plan records.",
        "# TYPE focus_agent_tool_router_enforced_count gauge",
        prometheus_metric_line("focus_agent_tool_router_enforced_count", int(metrics.get("tool_router_enforced") or 0)),
        "# HELP focus_agent_delegation_run_count Total delegated agent runs observed in trajectory plan_meta.",
        "# TYPE focus_agent_delegation_run_count gauge",
        prometheus_metric_line("focus_agent_delegation_run_count", int(metrics.get("agent_delegation_runs") or 0)),
        "# HELP focus_agent_critic_reject_count Total critic rejection failures observed in trajectory plan_meta.",
        "# TYPE focus_agent_critic_reject_count gauge",
        prometheus_metric_line("focus_agent_critic_reject_count", int(metrics.get("critic_rejects") or 0)),
        "# HELP focus_agent_review_pending_count Pending agent review queue items observed in trajectory plan_meta.",
        "# TYPE focus_agent_review_pending_count gauge",
        prometheus_metric_line("focus_agent_review_pending_count", int(metrics.get("agent_review_pending") or 0)),
        "# HELP focus_agent_model_router_fallback_count Model Router fallback events observed in trajectory plan_meta.",
        "# TYPE focus_agent_model_router_fallback_count gauge",
        prometheus_metric_line("focus_agent_model_router_fallback_count", int(metrics.get("model_router_fallback") or 0)),
        "# HELP focus_agent_failure_count Agent failure records observed in trajectory plan_meta.",
        "# TYPE focus_agent_failure_count gauge",
        prometheus_metric_line("focus_agent_failure_count", int(metrics.get("agent_failures") or 0)),
        "# HELP focus_agent_context_artifact_ref_count Context Engineering artifact refs observed in trajectory plan_meta.",
        "# TYPE focus_agent_context_artifact_ref_count gauge",
        prometheus_metric_line("focus_agent_context_artifact_ref_count", int(metrics.get("context_artifact_refs") or 0)),
        "# HELP focus_agent_context_over_budget_count Context Engineering over-budget decisions observed in trajectory plan_meta.",
        "# TYPE focus_agent_context_over_budget_count gauge",
        prometheus_metric_line("focus_agent_context_over_budget_count", int(metrics.get("context_over_budget") or 0)),
        "# HELP focus_agent_task_ledger_task_count Agent Task Ledger tasks observed in trajectory plan_meta.",
        "# TYPE focus_agent_task_ledger_task_count gauge",
        prometheus_metric_line("focus_agent_task_ledger_task_count", int(metrics.get("agent_task_ledger_tasks") or 0)),
        "# HELP focus_agent_delegated_artifact_count Delegated artifacts observed in trajectory plan_meta.",
        "# TYPE focus_agent_delegated_artifact_count gauge",
        prometheus_metric_line("focus_agent_delegated_artifact_count", int(metrics.get("delegated_artifacts") or 0)),
        "# HELP focus_agent_critic_gate_rejected_count Rejected artifacts observed in critic gate results.",
        "# TYPE focus_agent_critic_gate_rejected_count gauge",
        prometheus_metric_line("focus_agent_critic_gate_rejected_count", int(metrics.get("critic_gate_rejected") or 0)),
    ]


def agent_governance_metrics_from_turns(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    metrics = {
        "memory_promotions": 0,
        "memory_conflicts": 0,
        "tool_router_denied": 0,
        "tool_router_enforced": 0,
        "agent_delegation_runs": 0,
        "critic_rejects": 0,
        "agent_review_pending": 0,
        "model_router_fallback": 0,
        "agent_failures": 0,
        "context_artifact_refs": 0,
        "context_over_budget": 0,
        "agent_task_ledger_tasks": 0,
        "delegated_artifacts": 0,
        "critic_gate_rejected": 0,
    }
    for row in rows:
        plan_meta = dict(row.get("plan_meta") or {})
        memory_decision = plan_meta.get("memory_curator_decision")
        if isinstance(memory_decision, dict):
            metrics["memory_promotions"] += len(memory_decision.get("promoted_memory_ids") or [])
            metrics["memory_conflicts"] += len(memory_decision.get("conflicts") or [])
        tool_plan = plan_meta.get("tool_route_plan")
        if isinstance(tool_plan, dict):
            metrics["tool_router_denied"] += len(tool_plan.get("denied_tools") or [])
            metrics["tool_router_enforced"] += 1 if tool_plan.get("enforce") else 0
        delegation_plan = plan_meta.get("agent_delegation_plan")
        if isinstance(delegation_plan, dict):
            metrics["agent_delegation_runs"] += len(delegation_plan.get("runs") or [])
        model_decision = plan_meta.get("model_route_decision")
        if isinstance(model_decision, dict):
            metrics["model_router_fallback"] += 1 if model_decision.get("fallback_used") else 0
        failures = plan_meta.get("agent_failure_records")
        if isinstance(failures, list):
            metrics["agent_failures"] += len(failures)
            metrics["critic_rejects"] += len(
                [item for item in failures if isinstance(item, dict) and item.get("failure_type") == "critic_rejected"]
            )
        review_queue = plan_meta.get("agent_review_queue")
        if isinstance(review_queue, list):
            metrics["agent_review_pending"] += len(
                [item for item in review_queue if isinstance(item, dict) and item.get("status") == "pending"]
            )
        context_refs = plan_meta.get("context_artifact_refs")
        if isinstance(context_refs, list):
            metrics["context_artifact_refs"] += len(context_refs)
        context_budget = plan_meta.get("context_budget_decision")
        if isinstance(context_budget, dict):
            metrics["context_over_budget"] += 1 if int(context_budget.get("over_budget_chars") or 0) > 0 else 0
        task_ledger = plan_meta.get("agent_task_ledger")
        if isinstance(task_ledger, dict):
            metrics["agent_task_ledger_tasks"] += len(task_ledger.get("tasks") or [])
        delegated_artifacts = plan_meta.get("delegated_artifacts")
        if isinstance(delegated_artifacts, list):
            metrics["delegated_artifacts"] += len(delegated_artifacts)
        critic_gate = plan_meta.get("critic_gate_result")
        if isinstance(critic_gate, dict):
            metrics["critic_gate_rejected"] += len(critic_gate.get("rejected_artifact_ids") or [])
    return metrics


__all__ = [
    "agent_governance_metric_lines",
    "agent_governance_metrics_from_turns",
    "build_prometheus_metrics_payload",
    "escape_prometheus_label_value",
    "prometheus_metric_line",
]
