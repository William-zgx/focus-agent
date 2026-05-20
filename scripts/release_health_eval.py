"""Eval report release-health signal helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from focus_agent.observability.release_health import FAIL, WARN, ReleaseHealthSignal
from scripts._report_io import load_json, resolve_path


def _eval_report_signals(paths: Iterable[str | Path], *, root: Path) -> list[ReleaseHealthSignal]:
    signals: list[ReleaseHealthSignal] = []
    for raw_path in paths:
        path = resolve_path(raw_path, root)
        if not path.exists():
            signals.append(
                ReleaseHealthSignal(
                    key="eval_report_missing",
                    status=FAIL,
                    summary="eval report is missing",
                    detail=str(path),
                )
            )
            continue

        try:
            payload = load_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            signals.append(
                ReleaseHealthSignal(
                    key="eval_report_invalid",
                    status=FAIL,
                    summary="eval report could not be loaded",
                    detail=f"{path}: {exc}",
                )
            )
            continue
        if not isinstance(payload, dict):
            signals.append(
                ReleaseHealthSignal(
                    key="eval_report_invalid",
                    status=FAIL,
                    summary="eval report is not a JSON object",
                    detail=str(path),
                )
            )
            continue

        if not isinstance(payload.get("summary"), dict):
            signals.append(
                ReleaseHealthSignal(
                    key="eval_report_invalid",
                    status=FAIL,
                    summary="eval report has no summary",
                    detail=str(path),
                )
            )
            continue

        summary = payload["summary"]
        comparison = (
            payload.get("comparison") if isinstance(payload.get("comparison"), dict) else {}
        )
        failed = int(_number(summary.get("failed")))
        errors = int(_number(summary.get("errors")))
        passed = int(_number(summary.get("passed")))
        total = int(_number(summary.get("total")))
        regressions = list(comparison.get("regressions") or [])
        if total <= 0 or passed + failed + errors <= 0:
            signals.append(
                ReleaseHealthSignal(
                    key="eval_report_invalid",
                    status=FAIL,
                    summary="eval report has no covered cases",
                    detail=str(path),
                    details={
                        "total": total,
                        "passed": passed,
                        "failed": failed,
                        "errors": errors,
                    },
                )
            )
            continue
        if failed or errors or regressions:
            signals.append(
                ReleaseHealthSignal(
                    key="eval_replay_regression",
                    status=FAIL,
                    summary="eval report contains failures or regressions",
                    detail=str(path),
                    details={
                        "failed": failed,
                        "errors": errors,
                        "regressions": regressions,
                    },
                )
            )
        else:
            signals.append(
                ReleaseHealthSignal(
                    key="eval_replay_regression",
                    status="pass",
                    summary="eval report passed",
                    detail=str(path),
                    details={
                        "total": total,
                        "passed": passed,
                    },
                )
            )
    return signals

def _baseline_eval_report_signals(
    current_paths: Sequence[str | Path],
    baseline_paths: Sequence[str | Path],
    *,
    root: Path,
) -> list[ReleaseHealthSignal]:
    if not baseline_paths:
        return []

    signals: list[ReleaseHealthSignal] = []
    if not current_paths:
        return signals
    for index, raw_baseline_path in enumerate(baseline_paths):
        raw_current_path = current_paths[index] if index < len(current_paths) else current_paths[-1]
        baseline_path = resolve_path(raw_baseline_path, root)
        current_path = resolve_path(raw_current_path, root)
        if not baseline_path.exists():
            signals.append(
                ReleaseHealthSignal(
                    key="eval_report_missing",
                    status=FAIL,
                    summary="baseline eval report is missing",
                    detail=str(baseline_path),
                )
            )
            continue
        if not current_path.exists():
            continue

        try:
            baseline_payload = load_json(baseline_path)
            current_payload = load_json(current_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            signals.append(
                ReleaseHealthSignal(
                    key="eval_report_invalid",
                    status=FAIL,
                    summary="eval baseline comparison report could not be loaded",
                    detail=str(exc),
                    details={
                        "baseline": str(baseline_path),
                        "current": str(current_path),
                    },
                )
            )
            continue
        regressions = _compare_eval_summaries(
            _summary_from_eval_report(baseline_payload),
            _summary_from_eval_report(current_payload),
        )
        if regressions:
            signals.append(
                ReleaseHealthSignal(
                    key="eval_replay_regression",
                    status=FAIL,
                    summary="eval report regressed against baseline",
                    detail=str(current_path),
                    details={
                        "baseline": str(baseline_path),
                        "regressions": regressions,
                    },
                )
            )
        else:
            signals.append(
                ReleaseHealthSignal(
                    key="eval_baseline_regression",
                    status="pass",
                    summary="eval report is within baseline thresholds",
                    detail=str(current_path),
                    details={"baseline": str(baseline_path)},
                )
            )
    return signals

def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0

def _summary_from_eval_report(payload: Any) -> dict[str, float]:
    if not isinstance(payload, dict) or not isinstance(payload.get("summary"), dict):
        return {}
    summary = payload["summary"]
    total = _number(summary.get("total"))
    passed = _number(summary.get("passed"))
    task_success = summary.get("task_success")
    if task_success is None:
        task_success = passed / total if total else 0.0
    return {
        "task_success": _number(task_success),
        "avg_tool_calls": _number(summary.get("avg_tool_calls")),
        "avg_llm_calls": _number(summary.get("avg_llm_calls")),
        "avg_input_tokens": _number(summary.get("avg_input_tokens")),
        "avg_output_tokens": _number(summary.get("avg_output_tokens")),
        "p95_latency_ms": _number(summary.get("p95_latency_ms")),
        "avg_cost_usd": _number(summary.get("avg_cost_usd")),
        "forbidden_tool_violation_rate": _number(summary.get("forbidden_tool_violation_rate")),
    }

def _compare_eval_summaries(baseline: dict[str, float], current: dict[str, float]) -> list[str]:
    regressions: list[str] = []
    task_success_drop = baseline.get("task_success", 0.0) - current.get("task_success", 0.0)
    if task_success_drop > 0.02:
        regressions.append(f"task_success dropped {task_success_drop * 100:.1f}pp")
    if (
        current.get("forbidden_tool_violation_rate", 0.0)
        > baseline.get("forbidden_tool_violation_rate", 0.0) + 1e-9
    ):
        regressions.append(
            "forbidden tool violations grew "
            f"{baseline.get('forbidden_tool_violation_rate', 0.0):.3f} -> "
            f"{current.get('forbidden_tool_violation_rate', 0.0):.3f}"
        )

    for name in (
        "avg_tool_calls",
        "avg_llm_calls",
        "avg_input_tokens",
        "avg_output_tokens",
        "p95_latency_ms",
        "avg_cost_usd",
    ):
        base = baseline.get(name, 0.0)
        cur = current.get(name, 0.0)
        if base > 0 and (cur - base) / base > 0.20:
            regressions.append(f"{name} grew >20%: {base:.3f} -> {cur:.3f}")
    return regressions

def _fallback_signal(input_name: str) -> ReleaseHealthSignal:
    return ReleaseHealthSignal(
        key="release_health_self_check_fallback",
        status=WARN,
        summary="release-health used self-check fallback because live input was unavailable",
        detail=input_name,
    )

def _required_input_signal(input_name: str, detail: str) -> ReleaseHealthSignal:
    return ReleaseHealthSignal(
        key="release_health_required_input_missing",
        status=FAIL,
        summary="release-health live mode is missing a required deployment signal",
        detail=detail,
        labels={"input": input_name},
    )
