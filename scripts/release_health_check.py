#!/usr/bin/env python3
"""Evaluate release-health signals and write a structured JSON report."""

from __future__ import annotations

import argparse
import json
import sys
import types
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from scripts._report_io import (  # noqa: E402
    load_json,
    print_json_stdout,
    resolve_path,
    write_json_report,
)


def _install_observability_import_stubs() -> list[str]:
    inserted: list[str] = []
    if "focus_agent" not in sys.modules:
        package = types.ModuleType("focus_agent")
        package.__path__ = [str(REPO_ROOT / "src" / "focus_agent")]  # type: ignore[attr-defined]
        sys.modules["focus_agent"] = package
        inserted.append("focus_agent")
    if "focus_agent.observability" not in sys.modules:
        observability = types.ModuleType("focus_agent.observability")
        observability.__path__ = [str(REPO_ROOT / "src" / "focus_agent" / "observability")]  # type: ignore[attr-defined]
        sys.modules["focus_agent.observability"] = observability
        inserted.append("focus_agent.observability")
    return inserted


def _restore_import_stubs(inserted: Sequence[str]) -> None:
    for name in reversed(inserted):
        sys.modules.pop(name, None)


_import_stubs = _install_observability_import_stubs()
try:
    from focus_agent.observability.release_health import (  # noqa: E402
        ReleaseHealthReport,
        ReleaseHealthSignal,
        evaluate_release_health,
    )
finally:
    _restore_import_stubs(_import_stubs)

from scripts.release_health_eval import (  # noqa: E402
    _baseline_eval_report_signals,
    _eval_report_signals,
    _fallback_signal,
    _required_input_signal,
)

DEFAULT_REPORT_JSON = Path("reports/release-gate/release-health.json")
DEFAULT_READY_URL = "http://127.0.0.1:8000/readyz"
DEFAULT_TRAJECTORY_STATS_URL = "http://127.0.0.1:8000/v1/observability/trajectory/stats"
LOCAL_MODE = "local"
LIVE_MODES = {"live", "production"}
PRODUCTION_REPORT_INPUTS = (
    ("production_smoke_report", "production_smoke_report_json"),
    ("postgres_ops_report", "postgres_ops_report_json"),
    ("otel_smoke_report", "otel_smoke_report_json"),
    ("governance_report", "governance_report_json"),
)


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
        return load_json(path), True
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
    payload = load_json(path)
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


def _report_is_dry_run(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    status = str(payload.get("status") or "").lower()
    if payload.get("dry_run") is True or status == "dry-run":
        return True
    for value in payload.values():
        if isinstance(value, dict) and _report_is_dry_run(value):
            return True
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and _report_is_dry_run(item):
                    return True
    return False


def build_release_health_report(
    *,
    runtime_status: Any,
    trajectory_stats: dict[str, Any] | None = None,
    baseline_trajectory_stats: dict[str, Any] | None = None,
    replay_comparisons: list[dict[str, Any]] | None = None,
    alert_report: dict[str, Any] | None = None,
    postgres_migration_report: dict[str, Any] | None = None,
    production_smoke_report: dict[str, Any] | None = None,
    postgres_ops_report: dict[str, Any] | None = None,
    otel_smoke_report: dict[str, Any] | None = None,
    governance_quality_report: dict[str, Any] | None = None,
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
        production_smoke_report=production_smoke_report,
        postgres_ops_report=postgres_ops_report,
        otel_smoke_report=otel_smoke_report,
        governance_quality_report=governance_quality_report,
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
    target = resolve_path(path, root)
    payload = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "passed" if report.passed else "failed",
        "passed": report.passed,
        "root": str(root),
        "inputs": inputs,
        "signals": [signal.to_dict() for signal in report.signals],
    }
    return write_json_report(target, payload)


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
    parser.add_argument(
        "--runtime-status-json", help="JSON payload from /readyz or an equivalent readiness probe."
    )
    parser.add_argument("--readyz-json", help="Alias for --runtime-status-json.")
    parser.add_argument("--trajectory-stats-json", help="Trajectory stats JSON payload.")
    parser.add_argument(
        "--baseline-trajectory-stats-json", help="Baseline trajectory stats JSON payload."
    )
    parser.add_argument(
        "--baseline-eval-report-json",
        action="append",
        default=[],
        help="Baseline eval JSON report to compare against current --eval-report-json. May be repeated.",
    )
    parser.add_argument("--replay-comparisons-json", help="Batch replay-compare JSON payload.")
    parser.add_argument("--alert-report-json", help="Executable alert rules report JSON.")
    parser.add_argument(
        "--postgres-migration-report-json", help="Postgres migration verification report JSON."
    )
    parser.add_argument("--production-smoke-report-json", help="Production smoke report JSON.")
    parser.add_argument("--postgres-ops-report-json", help="Postgres ops report JSON.")
    parser.add_argument("--otel-smoke-report-json", help="OpenTelemetry smoke report JSON.")
    parser.add_argument("--governance-report-json", help="Agent Governance quality report JSON.")
    parser.add_argument(
        "--allow-dry-run-reports",
        action="store_true",
        help="Allow dry-run optional reports. Intended only for deterministic local evidence packs.",
    )
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
        if live_mode and args.allow_dry_run_reports:
            raise ValueError("--allow-dry-run-reports is only valid with --mode local")

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
        production_smoke_report, production_smoke_report_loaded = _load_json_input(
            args.production_smoke_report_json,
            input_name="production_smoke_report",
            live_mode=live_mode,
            fail_closed_signals=fail_closed_signals,
        )
        postgres_ops_report, postgres_ops_report_loaded = _load_json_input(
            args.postgres_ops_report_json,
            input_name="postgres_ops_report",
            live_mode=live_mode,
            fail_closed_signals=fail_closed_signals,
        )
        otel_smoke_report, otel_smoke_report_loaded = _load_json_input(
            args.otel_smoke_report_json,
            input_name="otel_smoke_report",
            live_mode=live_mode,
            fail_closed_signals=fail_closed_signals,
        )
        governance_quality_report, governance_quality_report_loaded = _load_json_input(
            args.governance_report_json,
            input_name="governance_report",
            live_mode=live_mode,
            fail_closed_signals=fail_closed_signals,
        )
        trajectory_stats_url_loaded = False

        if runtime_status is None and args.ready_url:
            try:
                runtime_status = _http_get_json(args.ready_url)
            except (OSError, TimeoutError, json.JSONDecodeError):
                if live_mode:
                    fail_closed_signals.append(
                        _required_input_signal("readyz", "failed to load --ready-url")
                    )
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
                        _required_input_signal(
                            "trajectory_stats", "failed to load --trajectory-stats-url"
                        )
                    )
                elif not args.allow_self_check_fallback:
                    raise

        if args.self_check:
            runtime_status = runtime_status or _self_check_runtime()
            trajectory_stats = trajectory_stats or _self_check_trajectory_stats()
        if live_mode:
            if runtime_status_loaded and runtime_status is None:
                fail_closed_signals.append(_required_input_signal("readyz", "invalid readyz input"))
            if (
                trajectory_stats_loaded or trajectory_stats_url_loaded
            ) and not _trajectory_stats_has_schema(trajectory_stats):
                fail_closed_signals.append(
                    _required_input_signal("trajectory_stats", "invalid trajectory stats input")
                )
            if replay_comparisons_loaded and not replay_comparisons:
                fail_closed_signals.append(
                    _required_input_signal("replay_comparisons", "empty replay comparison input")
                )
            if alert_report_loaded and not isinstance(alert_report, dict):
                fail_closed_signals.append(
                    _required_input_signal("alert_report", "invalid alert report input")
                )
                alert_report = None
            if postgres_migration_report_loaded and not isinstance(postgres_migration_report, dict):
                fail_closed_signals.append(
                    _required_input_signal(
                        "postgres_migration_report", "invalid postgres migration report input"
                    )
                )
                postgres_migration_report = None
            if production_smoke_report_loaded and not isinstance(production_smoke_report, dict):
                fail_closed_signals.append(
                    _required_input_signal(
                        "production_smoke_report", "invalid production smoke report input"
                    )
                )
                production_smoke_report = None
            if postgres_ops_report_loaded and not isinstance(postgres_ops_report, dict):
                fail_closed_signals.append(
                    _required_input_signal(
                        "postgres_ops_report", "invalid postgres ops report input"
                    )
                )
                postgres_ops_report = None
            if otel_smoke_report_loaded and not isinstance(otel_smoke_report, dict):
                fail_closed_signals.append(
                    _required_input_signal("otel_smoke_report", "invalid otel smoke report input")
                )
                otel_smoke_report = None
            if governance_quality_report_loaded and not isinstance(governance_quality_report, dict):
                fail_closed_signals.append(
                    _required_input_signal("governance_report", "invalid governance report input")
                )
                governance_quality_report = None
            if runtime_status is None and not _input_present(runtime_status_path, args.ready_url):
                fail_closed_signals.append(_required_input_signal("readyz", "missing readyz input"))
            if trajectory_stats is None and not _input_present(
                args.trajectory_stats_json, args.trajectory_stats_url
            ):
                fail_closed_signals.append(
                    _required_input_signal("trajectory_stats", "missing trajectory stats input")
                )
            if replay_comparisons is None and not _input_present(args.replay_comparisons_json):
                fail_closed_signals.append(
                    _required_input_signal("replay_comparisons", "missing replay comparison input")
                )
            if not args.eval_report_json:
                fail_closed_signals.append(
                    _required_input_signal("eval_report", "missing eval report input")
                )
            for input_name, arg_name in PRODUCTION_REPORT_INPUTS:
                if not _input_present(getattr(args, arg_name)):
                    fail_closed_signals.append(
                        _required_input_signal(input_name, f"missing {input_name} input")
                    )
            if not args.allow_dry_run_reports:
                for input_name, report in (
                    ("production_smoke_report", production_smoke_report),
                    ("postgres_ops_report", postgres_ops_report),
                    ("otel_smoke_report", otel_smoke_report),
                    ("governance_report", governance_quality_report),
                ):
                    if _report_is_dry_run(report):
                        fail_closed_signals.append(
                            _required_input_signal(
                                input_name, f"{input_name} cannot be dry-run in production mode"
                            )
                        )
        if (
            governance_quality_report_loaded
            and governance_quality_report is not None
            and not isinstance(governance_quality_report, dict)
        ):
            raise ValueError("governance report input must be a JSON object")
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
            production_smoke_report=production_smoke_report
            if isinstance(production_smoke_report, dict)
            else None,
            postgres_ops_report=postgres_ops_report
            if isinstance(postgres_ops_report, dict)
            else None,
            otel_smoke_report=otel_smoke_report if isinstance(otel_smoke_report, dict) else None,
            governance_quality_report=governance_quality_report
            if isinstance(governance_quality_report, dict)
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
                "production_smoke_report_json": args.production_smoke_report_json,
                "postgres_ops_report_json": args.postgres_ops_report_json,
                "otel_smoke_report_json": args.otel_smoke_report_json,
                "governance_report_json": args.governance_report_json,
                "allow_dry_run_reports": bool(args.allow_dry_run_reports),
                "ready_url": args.ready_url,
                "trajectory_stats_url": args.trajectory_stats_url,
                "eval_report_json": list(args.eval_report_json),
            },
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[release-health] {exc}", file=sys.stderr)
        return 2

    print_json_stdout(
        {"status": "passed" if report.passed else "failed", "report_json": str(report_path)}
    )
    return 0 if report.passed else 1


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
