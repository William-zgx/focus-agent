"""Trajectory-derived release-health signals."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from focus_agent.observability.release_health_models import (
    FAIL,
    PASS,
    WARN,
    ReleaseHealthSignal,
    ReleaseHealthThresholds,
)
from focus_agent.observability.release_health_utils import number, overview, ratio


def evaluate_chat_failure_rate(
    trajectory_stats: Mapping[str, Any],
    *,
    thresholds: ReleaseHealthThresholds | None = None,
) -> ReleaseHealthSignal:
    policy = thresholds or ReleaseHealthThresholds()
    stats_overview = overview(trajectory_stats)
    turn_count = int(number(stats_overview.get("turn_count")))
    failed_count = int(number(stats_overview.get("non_succeeded_count")))
    failure_rate = ratio(failed_count, turn_count)
    details = {"turn_count": turn_count, "non_succeeded_count": failed_count}

    if turn_count < policy.chat_failure_min_turns:
        return ReleaseHealthSignal(
            key="chat_failure_rate",
            status=WARN,
            summary="not enough trajectory turns for chat failure-rate gate",
            value=failure_rate,
            threshold=policy.chat_failure_rate,
            details=details,
        )
    if failure_rate >= policy.chat_failure_rate:
        return ReleaseHealthSignal(
            key="chat_failure_rate",
            status=FAIL,
            summary="chat failure rate is above release threshold",
            value=failure_rate,
            threshold=policy.chat_failure_rate,
            details=details,
        )
    return ReleaseHealthSignal(
        key="chat_failure_rate",
        status=PASS,
        summary="chat failure rate is within threshold",
        value=failure_rate,
        threshold=policy.chat_failure_rate,
        details=details,
    )


def evaluate_tool_fallback_spike(
    trajectory_stats: Mapping[str, Any],
    *,
    baseline_stats: Mapping[str, Any] | None = None,
    thresholds: ReleaseHealthThresholds | None = None,
) -> ReleaseHealthSignal:
    policy = thresholds or ReleaseHealthThresholds()
    stats_overview = overview(trajectory_stats)
    tool_calls = int(number(stats_overview.get("total_tool_calls")))
    fallback_uses = int(number(stats_overview.get("total_fallback_uses")))
    fallback_rate = ratio(fallback_uses, tool_calls)
    baseline_rate = None
    if baseline_stats is not None:
        baseline_overview = overview(baseline_stats)
        baseline_rate = ratio(
            number(baseline_overview.get("total_fallback_uses")),
            number(baseline_overview.get("total_tool_calls")),
        )

    details = {
        "total_tool_calls": tool_calls,
        "total_fallback_uses": fallback_uses,
        "baseline_rate": baseline_rate,
    }
    if tool_calls < policy.fallback_min_tool_calls:
        return ReleaseHealthSignal(
            key="tool_fallback_spike",
            status=WARN,
            summary="not enough tool calls for fallback spike gate",
            value=fallback_rate,
            threshold=policy.fallback_rate,
            details=details,
        )

    growth = (fallback_rate - baseline_rate) if baseline_rate is not None else 0.0
    if fallback_rate >= policy.fallback_rate or growth >= policy.fallback_rate_growth:
        return ReleaseHealthSignal(
            key="tool_fallback_spike",
            status=FAIL,
            summary="tool fallback rate is above release threshold",
            value=fallback_rate,
            threshold=policy.fallback_rate,
            details={**details, "growth": growth},
        )
    return ReleaseHealthSignal(
        key="tool_fallback_spike",
        status=PASS,
        summary="tool fallback rate is within threshold",
        value=fallback_rate,
        threshold=policy.fallback_rate,
        details={**details, "growth": growth},
    )
