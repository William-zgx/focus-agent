"""Replay and eval regression release-health signals."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from focus_agent.observability.release_health_models import FAIL, PASS, WARN, ReleaseHealthSignal


def evaluate_replay_gate(
    comparisons: Iterable[Mapping[str, Any]],
    *,
    fail_on_tool_path_change: bool = False,
) -> ReleaseHealthSignal:
    rows = [dict(row) for row in comparisons]
    failures: list[str] = []
    warnings: list[str] = []
    for row in rows:
        case_id = str(row.get("case_id") or row.get("trajectory_id") or "unknown")
        if row.get("replay_error"):
            failures.append(f"{case_id}: replay error")
        if not bool(row.get("replay_passed", True)):
            failures.append(f"{case_id}: replay failed")
        if bool(row.get("tool_path_changed")):
            message = f"{case_id}: tool path changed"
            if fail_on_tool_path_change:
                failures.append(message)
            else:
                warnings.append(message)

    details = {
        "checked": len(rows),
        "failures": failures,
        "warnings": warnings,
    }
    if failures:
        return ReleaseHealthSignal(
            key="eval_replay_regression",
            status=FAIL,
            summary="eval replay regression detected",
            details=details,
        )
    if warnings:
        return ReleaseHealthSignal(
            key="eval_replay_regression",
            status=WARN,
            summary="eval replay completed with trajectory drift",
            details=details,
        )
    return ReleaseHealthSignal(
        key="eval_replay_regression",
        status=PASS,
        summary="eval replay gate passed",
        details=details,
    )


def eval_regression_signal(regressions: list[str]) -> ReleaseHealthSignal:
    return ReleaseHealthSignal(
        key="eval_replay_regression",
        status=FAIL,
        summary="eval replay regression detected",
        details={"regressions": regressions},
    )
