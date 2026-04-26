#!/usr/bin/env python3
"""Evaluate release-health signals and write a structured JSON report."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Sequence
from urllib import request as urllib_request


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from focus_agent.observability.release_health import (  # noqa: E402
    FAIL,
    WARN,
    ReleaseHealthReport,
    ReleaseHealthSignal,
    evaluate_release_health,
)


DEFAULT_REPORT_JSON = Path("reports/release-gate/release-health.json")
DEFAULT_READY_URL = "http://127.0.0.1:8000/readyz"
DEFAULT_TRAJECTORY_STATS_URL = "http://127.0.0.1:8000/v1/observability/trajectory/stats"


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_optional_json(path: str | Path | None) -> Any:
    if not path:
        return None
    return _load_json(path)


def _http_get_json(url: str) -> Any:
    with urllib_request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _resolve_path(path: str | Path, root: Path) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    return target


def _self_check_runtime() -> dict[str, Any]:
    return {
        "ready": True,
        "status": "self-check",
        "checks": [{"name": "trajectory_recorder", "ready": True, "detail": "self-check"}],
    }


def _self_check_trajectory_stats() -> dict[str, Any]:
    return {
        "overview": {
            "turn_count": 20,
            "non_succeeded_count": 0,
            "total_tool_calls": 20,
            "total_fallback_uses": 0,
        }
    }


def _normalize_trajectory_stats(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    stats = payload.get("stats")
    return stats if isinstance(stats, dict) else payload


def _load_replay_comparisons(path: str | Path | None) -> list[dict[str, Any]] | None:
    if not path:
        return None
    payload = _load_json(path)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("comparisons", "results", "items", "data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        if {"case_id", "replay_passed"} <= set(payload):
            return [payload]
    raise ValueError(f"unsupported replay comparison payload: {path}")


def _eval_report_signals(paths: Iterable[str | Path], *, root: Path) -> list[ReleaseHealthSignal]:
    signals: list[ReleaseHealthSignal] = []
    for raw_path in paths:
        path = _resolve_path(raw_path, root)
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

        payload = _load_json(path)
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

        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        comparison = payload.get("comparison") if isinstance(payload.get("comparison"), dict) else {}
        failed = int(_number(summary.get("failed")))
        errors = int(_number(summary.get("errors")))
        regressions = list(comparison.get("regressions") or [])
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
                        "total": int(_number(summary.get("total"))),
                        "passed": int(_number(summary.get("passed"))),
                    },
                )
            )
    return signals


def build_release_health_report(
    *,
    runtime_status: Any,
    trajectory_stats: dict[str, Any] | None = None,
    baseline_trajectory_stats: dict[str, Any] | None = None,
    replay_comparisons: list[dict[str, Any]] | None = None,
    eval_report_paths: Sequence[str | Path] = (),
    extra_signals: Sequence[ReleaseHealthSignal] = (),
    root: Path | None = None,
) -> ReleaseHealthReport:
    root = root or REPO_ROOT
    report = evaluate_release_health(
        runtime_status=runtime_status,
        trajectory_stats=trajectory_stats,
        baseline_trajectory_stats=baseline_trajectory_stats,
        replay_comparisons=replay_comparisons,
    )
    eval_signals = _eval_report_signals(eval_report_paths, root=root)
    return ReleaseHealthReport(signals=(*report.signals, *extra_signals, *eval_signals))


def write_report(
    path: str | Path,
    *,
    report: ReleaseHealthReport,
    root: Path,
    inputs: dict[str, Any],
) -> Path:
    target = _resolve_path(path, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "passed" if report.passed else "failed",
        "passed": report.passed,
        "root": str(root),
        "inputs": inputs,
        "signals": [signal.to_dict() for signal in report.signals],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Use deterministic healthy runtime and trajectory samples. Intended for script tests, not production gates.",
    )
    parser.add_argument(
        "--allow-self-check-fallback",
        action="store_true",
        help="Fall back to deterministic healthy samples if live JSON inputs or HTTP probes are unavailable.",
    )
    parser.add_argument("--runtime-status-json", help="JSON payload from /readyz or an equivalent readiness probe.")
    parser.add_argument("--trajectory-stats-json", help="Trajectory stats JSON payload.")
    parser.add_argument("--baseline-trajectory-stats-json", help="Baseline trajectory stats JSON payload.")
    parser.add_argument("--replay-comparisons-json", help="Batch replay-compare JSON payload.")
    parser.add_argument("--ready-url", help="HTTP URL for the runtime readiness probe.")
    parser.add_argument("--trajectory-stats-url", help="HTTP URL for trajectory stats.")
    parser.add_argument(
        "--eval-report-json",
        action="append",
        default=[],
        help="Eval JSON report to include in the release-health decision. May be repeated.",
    )
    parser.add_argument(
        "--report-json",
        default=str(DEFAULT_REPORT_JSON),
        help="Path for the release-health JSON report.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = REPO_ROOT
    try:
        fallback_signals: list[ReleaseHealthSignal] = []
        runtime_status = _load_optional_json(args.runtime_status_json)
        trajectory_stats = _normalize_trajectory_stats(_load_optional_json(args.trajectory_stats_json))
        baseline_stats = _load_optional_json(args.baseline_trajectory_stats_json)
        replay_comparisons = _load_replay_comparisons(args.replay_comparisons_json)

        if runtime_status is None and args.ready_url:
            try:
                runtime_status = _http_get_json(args.ready_url)
            except (OSError, TimeoutError, json.JSONDecodeError):
                if not args.allow_self_check_fallback:
                    raise
        if trajectory_stats is None and args.trajectory_stats_url:
            try:
                trajectory_stats = _normalize_trajectory_stats(_http_get_json(args.trajectory_stats_url))
            except (OSError, TimeoutError, json.JSONDecodeError):
                if not args.allow_self_check_fallback:
                    raise

        if args.self_check:
            runtime_status = runtime_status or _self_check_runtime()
            trajectory_stats = trajectory_stats or _self_check_trajectory_stats()
        if runtime_status is None:
            if args.allow_self_check_fallback:
                runtime_status = _self_check_runtime()
                fallback_signals.append(_fallback_signal("runtime_status"))
            else:
                raise ValueError(
                    "--runtime-status-json or --ready-url is required unless --self-check "
                    "or --allow-self-check-fallback is used"
                )
        if trajectory_stats is None and args.allow_self_check_fallback:
            trajectory_stats = _self_check_trajectory_stats()
            fallback_signals.append(_fallback_signal("trajectory_stats"))

        report = build_release_health_report(
            runtime_status=runtime_status,
            trajectory_stats=trajectory_stats,
            baseline_trajectory_stats=baseline_stats,
            replay_comparisons=replay_comparisons,
            eval_report_paths=args.eval_report_json,
            extra_signals=fallback_signals,
            root=root,
        )
        report_path = write_report(
            args.report_json,
            report=report,
            root=root,
            inputs={
                "self_check": bool(args.self_check),
                "allow_self_check_fallback": bool(args.allow_self_check_fallback),
                "runtime_status_json": args.runtime_status_json,
                "trajectory_stats_json": args.trajectory_stats_json,
                "baseline_trajectory_stats_json": args.baseline_trajectory_stats_json,
                "replay_comparisons_json": args.replay_comparisons_json,
                "ready_url": args.ready_url,
                "trajectory_stats_url": args.trajectory_stats_url,
                "eval_report_json": list(args.eval_report_json),
            },
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[release-health] {exc}", file=sys.stderr)
        return 2

    print(json.dumps({"status": "passed" if report.passed else "failed", "report_json": str(report_path)}, indent=2))
    return 0 if report.passed else 1


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _fallback_signal(input_name: str) -> ReleaseHealthSignal:
    return ReleaseHealthSignal(
        key="release_health_self_check_fallback",
        status=WARN,
        summary="release-health used self-check fallback because live input was unavailable",
        detail=input_name,
    )


if __name__ == "__main__":
    raise SystemExit(main())
