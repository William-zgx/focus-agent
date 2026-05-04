"""Runtime readiness release-health signals."""

from __future__ import annotations

from typing import Any

from focus_agent.observability.release_health_models import FAIL, PASS, WARN, ReleaseHealthSignal
from focus_agent.observability.release_health_utils import check_by_name, value


def evaluate_runtime_ready(runtime_status: Any) -> ReleaseHealthSignal:
    ready = bool(value(runtime_status, "ready", False))
    status_text = str(value(runtime_status, "status", "unknown") or "unknown")
    if ready:
        return ReleaseHealthSignal(
            key="runtime_not_ready",
            status=PASS,
            summary="runtime ready",
            detail=status_text,
        )
    return ReleaseHealthSignal(
        key="runtime_not_ready",
        status=FAIL,
        summary="runtime is not ready",
        detail=status_text,
    )


def evaluate_trajectory_recorder_ready(runtime_status: Any) -> ReleaseHealthSignal:
    check = check_by_name(runtime_status, "trajectory_recorder")
    if check is None:
        return ReleaseHealthSignal(
            key="trajectory_recorder_unavailable",
            status=WARN,
            summary="trajectory recorder readiness is not reported",
        )

    ready = bool(value(check, "ready", False))
    detail = str(value(check, "detail", "") or "")
    if ready:
        return ReleaseHealthSignal(
            key="trajectory_recorder_unavailable",
            status=PASS,
            summary="trajectory recorder ready",
            detail=detail,
        )
    return ReleaseHealthSignal(
        key="trajectory_recorder_unavailable",
        status=FAIL,
        summary="trajectory recorder unavailable",
        detail=detail,
    )
