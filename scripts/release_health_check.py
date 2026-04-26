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
LOCAL_MODE = "local"
LIVE_MODES = {"live", "production"}


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_json_input(
    path: str | Path | None,
    *,
    input_name: str,
    live_mode: bool,
    fail_closed_signals: list[ReleaseHealthSignal],
) -> tuple[Any, bool]:
    if not path:
        return None, False
    try:
        return _load_json(path), True
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if not live_mode:
            raise
        fail_closed_signals.append(
            _required_input_signal(input_name, f"failed to load {path}: {exc}")
        )
        return None, False


def _load_replay_comparisons_input(
    path: str | Path | None,
    *,
    live_mode: bool,
    fail_closed_signals: list[ReleaseHealthSignal],
) -> tuple[list[dict[str, Any]] | None, bool]:
    if not path:
        return None, False
    try:
        return _load_replay_comparisons(path), True
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if not live_mode:
            raise
        fail_closed_signals.append(
            _required_input_signal("replay_comparisons", f"failed to load {path}: {exc}")
        )
        return None, False


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


def _input_present(*values: str | Path | None) -> bool:
    return any(bool(value) for value in values)


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

        try:
            payload = _load_json(path)
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
        comparison = payload.get("comparison") if isinstance(payload.get("comparison"), dict) else {}
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
        baseline_path = _resolve_path(raw_baseline_path, root)
        current_path = _resolve_path(raw_current_path, root)
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
            baseline_payload = _load_json(baseline_path)
            current_payload = _load_json(current_path)
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


def build_release_health_report(
    *,
    runtime_status: Any,
    trajectory_stats: dict[str, Any] | None = None,
    baseline_trajectory_stats: dict[str, Any] | None = None,
    replay_comparisons: list[dict[str, Any]] | None = None,
    alert_report: dict[str, Any] | None = None,
    postgres_migration_report: dict[str, Any] | None = None,
    eval_report_paths: Sequence[str | Path] = (),
    baseline_eval_report_paths: Sequence[str | Path] = (),
    extra_signals: Sequence[ReleaseHealthSignal] = (),
    root: Path | None = None,
) -> ReleaseHealthReport:
    root = root or REPO_ROOT
    report = evaluate_release_health(
        runtime_status=runtime_status,
        trajectory_stats=trajectory_stats,
        baseline_trajectory_stats=baseline_trajectory_stats,
        replay_comparisons=replay_comparisons,
        alert_report=alert_report,
        postgres_migration_report=postgres_migration_report,
    )
    eval_signals = _eval_report_signals(eval_report_paths, root=root)
    baseline_eval_signals = _baseline_eval_report_signals(
        eval_report_paths,
        baseline_eval_report_paths,
        root=root,
    )
    return ReleaseHealthReport(
        signals=(*report.signals, *extra_signals, *eval_signals, *baseline_eval_signals)
    )


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
        "--mode",
        choices=(LOCAL_MODE, "live", "production"),
        default=LOCAL_MODE,
        help=(
            "Signal policy to apply. local may use explicit self-check fallback; "
            "live/production fail closed when deployment inputs are missing."
        ),
    )
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
    parser.add_argument("--readyz-json", help="Alias for --runtime-status-json.")
    parser.add_argument("--trajectory-stats-json", help="Trajectory stats JSON payload.")
    parser.add_argument("--baseline-trajectory-stats-json", help="Baseline trajectory stats JSON payload.")
    parser.add_argument(
        "--baseline-eval-report-json",
        action="append",
        default=[],
        help="Baseline eval JSON report to compare against current --eval-report-json. May be repeated.",
    )
    parser.add_argument("--replay-comparisons-json", help="Batch replay-compare JSON payload.")
    parser.add_argument("--alert-report-json", help="Executable alert rules report JSON.")
    parser.add_argument("--postgres-migration-report-json", help="Postgres migration verification report JSON.")
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
        live_mode = args.mode in LIVE_MODES
        if live_mode and args.self_check:
            raise ValueError("--self-check is only valid with --mode local")
        if live_mode and args.allow_self_check_fallback:
            raise ValueError("--allow-self-check-fallback is only valid with --mode local")

        fallback_signals: list[ReleaseHealthSignal] = []
        fail_closed_signals: list[ReleaseHealthSignal] = []
        runtime_status_path = args.runtime_status_json or args.readyz_json
        runtime_status, runtime_status_loaded = _load_json_input(
            runtime_status_path,
            input_name="readyz",
            live_mode=live_mode,
            fail_closed_signals=fail_closed_signals,
        )
        trajectory_stats_payload, trajectory_stats_loaded = _load_json_input(
            args.trajectory_stats_json,
            input_name="trajectory_stats",
            live_mode=live_mode,
            fail_closed_signals=fail_closed_signals,
        )
        trajectory_stats = _normalize_trajectory_stats(trajectory_stats_payload)
        baseline_stats, _baseline_stats_loaded = _load_json_input(
            args.baseline_trajectory_stats_json,
            input_name="baseline_trajectory_stats",
            live_mode=live_mode,
            fail_closed_signals=fail_closed_signals,
        )
        replay_comparisons, replay_comparisons_loaded = _load_replay_comparisons_input(
            args.replay_comparisons_json,
            live_mode=live_mode,
            fail_closed_signals=fail_closed_signals,
        )
        alert_report, alert_report_loaded = _load_json_input(
            args.alert_report_json,
            input_name="alert_report",
            live_mode=live_mode,
            fail_closed_signals=fail_closed_signals,
        )
        postgres_migration_report, postgres_migration_report_loaded = _load_json_input(
            args.postgres_migration_report_json,
            input_name="postgres_migration_report",
            live_mode=live_mode,
            fail_closed_signals=fail_closed_signals,
        )
        trajectory_stats_url_loaded = False

        if runtime_status is None and args.ready_url:
            try:
                runtime_status = _http_get_json(args.ready_url)
            except (OSError, TimeoutError, json.JSONDecodeError):
                if live_mode:
                    fail_closed_signals.append(_required_input_signal("readyz", "failed to load --ready-url"))
                elif not args.allow_self_check_fallback:
                    raise
        if trajectory_stats is None and args.trajectory_stats_url:
            try:
                trajectory_stats_payload = _http_get_json(args.trajectory_stats_url)
                trajectory_stats_url_loaded = True
                trajectory_stats = _normalize_trajectory_stats(trajectory_stats_payload)
            except (OSError, TimeoutError, json.JSONDecodeError):
                if live_mode:
                    fail_closed_signals.append(
                        _required_input_signal("trajectory_stats", "failed to load --trajectory-stats-url")
                    )
                elif not args.allow_self_check_fallback:
                    raise

        if args.self_check:
            runtime_status = runtime_status or _self_check_runtime()
            trajectory_stats = trajectory_stats or _self_check_trajectory_stats()
        if live_mode:
            if runtime_status_loaded and runtime_status is None:
                fail_closed_signals.append(_required_input_signal("readyz", "invalid readyz input"))
            if (trajectory_stats_loaded or trajectory_stats_url_loaded) and not _trajectory_stats_has_schema(
                trajectory_stats
            ):
                fail_closed_signals.append(
                    _required_input_signal("trajectory_stats", "invalid trajectory stats input")
                )
            if replay_comparisons_loaded and not replay_comparisons:
                fail_closed_signals.append(
                    _required_input_signal("replay_comparisons", "empty replay comparison input")
                )
            if alert_report_loaded and not isinstance(alert_report, dict):
                fail_closed_signals.append(_required_input_signal("alert_report", "invalid alert report input"))
                alert_report = None
            if postgres_migration_report_loaded and not isinstance(postgres_migration_report, dict):
                fail_closed_signals.append(
                    _required_input_signal("postgres_migration_report", "invalid postgres migration report input")
                )
                postgres_migration_report = None
            if runtime_status is None and not _input_present(runtime_status_path, args.ready_url):
                fail_closed_signals.append(_required_input_signal("readyz", "missing readyz input"))
            if trajectory_stats is None and not _input_present(args.trajectory_stats_json, args.trajectory_stats_url):
                fail_closed_signals.append(
                    _required_input_signal("trajectory_stats", "missing trajectory stats input")
                )
            if replay_comparisons is None and not _input_present(args.replay_comparisons_json):
                fail_closed_signals.append(
                    _required_input_signal("replay_comparisons", "missing replay comparison input")
                )
            if not args.eval_report_json:
                fail_closed_signals.append(_required_input_signal("eval_report", "missing eval report input"))
        if runtime_status is None:
            if args.allow_self_check_fallback:
                runtime_status = _self_check_runtime()
                fallback_signals.append(_fallback_signal("runtime_status"))
            elif live_mode:
                runtime_status = _missing_runtime_status()
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
            alert_report=alert_report if isinstance(alert_report, dict) else None,
            postgres_migration_report=postgres_migration_report
            if isinstance(postgres_migration_report, dict)
            else None,
            eval_report_paths=args.eval_report_json,
            baseline_eval_report_paths=args.baseline_eval_report_json,
            extra_signals=(*fallback_signals, *fail_closed_signals),
            root=root,
        )
        report_path = write_report(
            args.report_json,
            report=report,
            root=root,
            inputs={
                "self_check": bool(args.self_check),
                "allow_self_check_fallback": bool(args.allow_self_check_fallback),
                "mode": args.mode,
                "runtime_status_json": runtime_status_path,
                "trajectory_stats_json": args.trajectory_stats_json,
                "baseline_trajectory_stats_json": args.baseline_trajectory_stats_json,
                "baseline_eval_report_json": list(args.baseline_eval_report_json),
                "replay_comparisons_json": args.replay_comparisons_json,
                "alert_report_json": args.alert_report_json,
                "postgres_migration_report_json": args.postgres_migration_report_json,
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


def _trajectory_stats_has_schema(stats: Any) -> bool:
    if not isinstance(stats, dict):
        return False
    overview = stats.get("overview") if isinstance(stats.get("overview"), dict) else stats
    return any(
        key in overview
        for key in (
            "turn_count",
            "non_succeeded_count",
            "total_tool_calls",
            "total_fallback_uses",
        )
    )


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
    if current.get("forbidden_tool_violation_rate", 0.0) > baseline.get(
        "forbidden_tool_violation_rate", 0.0
    ) + 1e-9:
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


def _missing_runtime_status() -> dict[str, Any]:
    return {
        "ready": False,
        "status": "missing live readiness input",
        "checks": [
            {
                "name": "trajectory_recorder",
                "ready": False,
                "detail": "missing live readiness input",
            }
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
