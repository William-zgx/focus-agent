"""Small release-health gates built from runtime, trajectory, and eval signals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


PASS = "pass"
WARN = "warn"
FAIL = "fail"


@dataclass(frozen=True, slots=True)
class ReleaseHealthThresholds:
    chat_failure_rate: float = 0.05
    chat_failure_min_turns: int = 20
    fallback_rate: float = 0.25
    fallback_min_tool_calls: int = 20
    fallback_rate_growth: float = 0.15


@dataclass(frozen=True, slots=True)
class ReleaseHealthSignal:
    key: str
    status: str
    summary: str
    detail: str = ""
    value: float | None = None
    threshold: float | None = None
    labels: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status != FAIL

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "status": self.status,
            "summary": self.summary,
            "detail": self.detail,
            "value": self.value,
            "threshold": self.threshold,
            "labels": dict(self.labels),
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class ReleaseHealthReport:
    signals: tuple[ReleaseHealthSignal, ...]

    @property
    def passed(self) -> bool:
        return all(signal.passed for signal in self.signals)

    @property
    def failed(self) -> tuple[ReleaseHealthSignal, ...]:
        return tuple(signal for signal in self.signals if signal.status == FAIL)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "signals": [signal.to_dict() for signal in self.signals],
        }


def evaluate_release_health(
    *,
    runtime_status: Any,
    trajectory_stats: Mapping[str, Any] | None = None,
    baseline_trajectory_stats: Mapping[str, Any] | None = None,
    replay_comparisons: Iterable[Mapping[str, Any]] | None = None,
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
        signals.append(_eval_regression_signal(regression_items))

    return ReleaseHealthReport(signals=tuple(signals))


def evaluate_runtime_ready(runtime_status: Any) -> ReleaseHealthSignal:
    ready = bool(_value(runtime_status, "ready", False))
    status_text = str(_value(runtime_status, "status", "unknown") or "unknown")
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
    check = _check_by_name(runtime_status, "trajectory_recorder")
    if check is None:
        return ReleaseHealthSignal(
            key="trajectory_recorder_unavailable",
            status=WARN,
            summary="trajectory recorder readiness is not reported",
        )

    ready = bool(_value(check, "ready", False))
    detail = str(_value(check, "detail", "") or "")
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


def evaluate_chat_failure_rate(
    trajectory_stats: Mapping[str, Any],
    *,
    thresholds: ReleaseHealthThresholds | None = None,
) -> ReleaseHealthSignal:
    policy = thresholds or ReleaseHealthThresholds()
    overview = _overview(trajectory_stats)
    turn_count = int(_number(overview.get("turn_count")))
    failed_count = int(_number(overview.get("non_succeeded_count")))
    failure_rate = _ratio(failed_count, turn_count)
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
    overview = _overview(trajectory_stats)
    tool_calls = int(_number(overview.get("total_tool_calls")))
    fallback_uses = int(_number(overview.get("total_fallback_uses")))
    fallback_rate = _ratio(fallback_uses, tool_calls)
    baseline_rate = None
    if baseline_stats is not None:
        baseline_overview = _overview(baseline_stats)
        baseline_rate = _ratio(
            _number(baseline_overview.get("total_fallback_uses")),
            _number(baseline_overview.get("total_tool_calls")),
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


def evaluate_context_probe(
    rendered_context: str,
    *,
    required_markers: Iterable[str] = (),
    forbidden_markers: Iterable[str] = (),
    max_chars: int | None = None,
    key: str = "memory_context_probe",
) -> ReleaseHealthSignal:
    text = str(rendered_context or "")
    missing = [marker for marker in required_markers if marker not in text]
    forbidden = [marker for marker in forbidden_markers if marker in text]
    too_large = max_chars is not None and len(text) > max_chars
    details = {
        "chars": len(text),
        "missing": missing,
        "forbidden": forbidden,
        "max_chars": max_chars,
    }
    if missing or forbidden or too_large:
        return ReleaseHealthSignal(
            key=key,
            status=FAIL,
            summary="memory/context probe failed",
            details=details,
        )
    return ReleaseHealthSignal(
        key=key,
        status=PASS,
        summary="memory/context probe passed",
        details=details,
    )


def _eval_regression_signal(regressions: list[str]) -> ReleaseHealthSignal:
    return ReleaseHealthSignal(
        key="eval_replay_regression",
        status=FAIL,
        summary="eval replay regression detected",
        details={"regressions": regressions},
    )


def _overview(stats: Mapping[str, Any]) -> Mapping[str, Any]:
    overview = stats.get("overview") if isinstance(stats, Mapping) else None
    if isinstance(overview, Mapping):
        return overview
    return stats


def _check_by_name(runtime_status: Any, name: str) -> Any | None:
    for check in list(_value(runtime_status, "checks", []) or []):
        if str(_value(check, "name", "")) == name:
            return check
    return None


def _value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator
