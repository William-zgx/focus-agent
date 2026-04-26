#!/usr/bin/env python3
"""Build a machine-readable production release evidence pack."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = Path("reports/release-gate")
TAIL_LINE_LIMIT = 80
TAIL_CHAR_LIMIT = 12_000


@dataclass(frozen=True)
class CommandOutcome:
    exit_code: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[Sequence[str], Path], CommandOutcome]


@dataclass(frozen=True)
class EvidenceInput:
    kind: str
    path: Path | None
    source_path: Path | None
    required: bool
    source: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _resolve_path(path: str | Path | None, root: Path) -> Path | None:
    if path is None:
        return None
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    return target


def _normalize_release_id(release_id: str) -> str:
    normalized = "".join(char if char.isalnum() or char in "._-" else "-" for char in release_id)
    normalized = normalized.strip(".-_")
    if not normalized:
        raise ValueError("--release-id must contain at least one path-safe character")
    return normalized


def _default_release_id(root: Path) -> str:
    try:
        completed = subprocess.run(
            ("git", "rev-parse", "--short", "HEAD"),
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        completed = None
    if completed is not None and completed.returncode == 0 and completed.stdout.strip():
        return _normalize_release_id(completed.stdout.strip())
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_or_reference_json(source: str | Path | None, target: Path, *, root: Path) -> tuple[Path | None, Path | None]:
    source_path = _resolve_path(source, root)
    if source_path is None:
        return None, None
    if not source_path.exists():
        return source_path, source_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target)
    return target, source_path


def _sample_readyz() -> dict[str, Any]:
    return {
        "checks": [{"detail": "dry-run sample", "name": "trajectory_recorder", "ready": True}],
        "ready": True,
        "status": "ok",
    }


def _sample_trajectory_stats() -> dict[str, Any]:
    return {
        "overview": {
            "non_succeeded_count": 0,
            "total_fallback_uses": 0,
            "total_tool_calls": 40,
            "turn_count": 40,
        }
    }


def _sample_replay_comparisons() -> list[dict[str, Any]]:
    return [
        {
            "case_id": "dry-run-trajectory",
            "replay_passed": True,
            "tool_path_changed": False,
        }
    ]


def _sample_eval_report() -> dict[str, Any]:
    return {
        "comparison": {"regressions": []},
        "results": [],
        "summary": {
            "avg_cost_usd": 0.01,
            "avg_input_tokens": 1200,
            "avg_llm_calls": 1,
            "avg_output_tokens": 240,
            "avg_tool_calls": 2,
            "errors": 0,
            "failed": 0,
            "forbidden_tool_violation_rate": 0.0,
            "passed": 2,
            "p95_latency_ms": 800,
            "task_success": 1.0,
            "total": 2,
        },
    }


def _prepare_dry_run_inputs(pack_dir: Path) -> dict[str, list[EvidenceInput] | EvidenceInput]:
    inputs_dir = pack_dir / "inputs"
    readyz = _write_json(inputs_dir / "readyz.json", _sample_readyz())
    trajectory_stats = _write_json(inputs_dir / "trajectory-stats.json", _sample_trajectory_stats())
    replay_comparisons = _write_json(inputs_dir / "replay-comparisons.json", _sample_replay_comparisons())
    eval_report = _write_json(inputs_dir / "eval-sample.json", _sample_eval_report())
    baseline_eval_report = _write_json(inputs_dir / "baseline-eval-sample.json", _sample_eval_report())
    return {
        "readyz": EvidenceInput("readyz", readyz, None, True, "generated"),
        "trajectory_stats": EvidenceInput("trajectory_stats", trajectory_stats, None, True, "generated"),
        "replay_comparisons": EvidenceInput("replay_comparisons", replay_comparisons, None, True, "generated"),
        "eval_reports": [EvidenceInput("eval_report", eval_report, None, True, "generated")],
        "baseline_eval_reports": [
            EvidenceInput("baseline_eval_report", baseline_eval_report, None, True, "generated")
        ],
    }


def _prepare_provided_inputs(
    *,
    pack_dir: Path,
    root: Path,
    readyz_json: str | Path | None,
    trajectory_stats_json: str | Path | None,
    replay_comparisons_json: str | Path | None,
    eval_report_json: Sequence[str | Path],
    baseline_eval_report_json: Sequence[str | Path],
) -> dict[str, list[EvidenceInput] | EvidenceInput]:
    inputs_dir = pack_dir / "inputs"
    readyz_path, readyz_source = _copy_or_reference_json(readyz_json, inputs_dir / "readyz.json", root=root)
    stats_path, stats_source = _copy_or_reference_json(
        trajectory_stats_json,
        inputs_dir / "trajectory-stats.json",
        root=root,
    )
    replay_path, replay_source = _copy_or_reference_json(
        replay_comparisons_json,
        inputs_dir / "replay-comparisons.json",
        root=root,
    )

    eval_reports: list[EvidenceInput] = []
    for index, raw_path in enumerate(eval_report_json, start=1):
        path, source_path = _copy_or_reference_json(raw_path, inputs_dir / f"eval-report-{index}.json", root=root)
        eval_reports.append(EvidenceInput("eval_report", path, source_path, True, "input"))

    baseline_eval_reports: list[EvidenceInput] = []
    for index, raw_path in enumerate(baseline_eval_report_json, start=1):
        path, source_path = _copy_or_reference_json(
            raw_path,
            inputs_dir / f"baseline-eval-report-{index}.json",
            root=root,
        )
        baseline_eval_reports.append(EvidenceInput("baseline_eval_report", path, source_path, True, "input"))

    return {
        "readyz": EvidenceInput("readyz", readyz_path, readyz_source, True, "input"),
        "trajectory_stats": EvidenceInput("trajectory_stats", stats_path, stats_source, True, "input"),
        "replay_comparisons": EvidenceInput("replay_comparisons", replay_path, replay_source, True, "input"),
        "eval_reports": eval_reports,
        "baseline_eval_reports": baseline_eval_reports,
    }


def _artifact_record(input_artifact: EvidenceInput) -> dict[str, Any]:
    path = input_artifact.path
    exists = bool(path and path.exists())
    return {
        "bytes": path.stat().st_size if exists and path is not None else 0,
        "exists": exists,
        "kind": input_artifact.kind,
        "path": str(path) if path is not None else None,
        "required": input_artifact.required,
        "sha256": _sha256(path) if exists and path is not None else None,
        "source": input_artifact.source,
        "source_path": str(input_artifact.source_path) if input_artifact.source_path is not None else None,
    }


def _release_health_command(
    *,
    artifacts: dict[str, list[EvidenceInput] | EvidenceInput],
    report_json: Path,
    root: Path,
) -> tuple[str, ...]:
    command: list[str] = [
        sys.executable,
        str(root / "scripts" / "release_health_check.py"),
        "--mode",
        "production",
    ]
    readyz = artifacts["readyz"]
    trajectory_stats = artifacts["trajectory_stats"]
    replay_comparisons = artifacts["replay_comparisons"]
    if isinstance(readyz, EvidenceInput) and readyz.path is not None:
        command.extend(("--readyz-json", str(readyz.path)))
    if isinstance(trajectory_stats, EvidenceInput) and trajectory_stats.path is not None:
        command.extend(("--trajectory-stats-json", str(trajectory_stats.path)))
    if isinstance(replay_comparisons, EvidenceInput) and replay_comparisons.path is not None:
        command.extend(("--replay-comparisons-json", str(replay_comparisons.path)))
    eval_reports = artifacts["eval_reports"]
    baseline_eval_reports = artifacts["baseline_eval_reports"]
    for artifact in eval_reports if isinstance(eval_reports, list) else []:
        if artifact.path is not None:
            command.extend(("--eval-report-json", str(artifact.path)))
    for artifact in baseline_eval_reports if isinstance(baseline_eval_reports, list) else []:
        if artifact.path is not None:
            command.extend(("--baseline-eval-report-json", str(artifact.path)))
    command.extend(("--report-json", str(report_json)))
    return tuple(command)


def _subprocess_runner(command: Sequence[str], root: Path) -> CommandOutcome:
    completed = subprocess.run(
        command,
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return CommandOutcome(
        exit_code=int(completed.returncode),
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _tail_output(output: str) -> str:
    if not output:
        return ""
    lines = output.splitlines()
    tail = "\n".join(lines[-TAIL_LINE_LIMIT:])
    if len(tail) > TAIL_CHAR_LIMIT:
        tail = tail[-TAIL_CHAR_LIMIT:]
    return tail


def _stream_summary(output: str) -> dict[str, int | bool]:
    tail = _tail_output(output)
    return {
        "char_count": len(output),
        "line_count": len(output.splitlines()),
        "truncated": tail != output,
    }


def _command_record(
    *,
    command: Sequence[str],
    outcome: CommandOutcome,
    duration_seconds: float,
) -> dict[str, Any]:
    return {
        "command": shlex.join(command),
        "duration_seconds": round(duration_seconds, 3),
        "exit_code": outcome.exit_code,
        "label": "release-health",
        "status": "passed" if outcome.exit_code == 0 else "failed",
        "stderr_summary": _stream_summary(outcome.stderr),
        "stderr_tail": _tail_output(outcome.stderr),
        "stdout_summary": _stream_summary(outcome.stdout),
        "stdout_tail": _tail_output(outcome.stdout),
    }


def _load_release_health_summary(report_json: Path) -> dict[str, Any]:
    if not report_json.exists():
        return {
            "failed_signals": [],
            "passed": False,
            "report_json": str(report_json),
            "signal_count": 0,
            "signals_summary": {},
            "status": "missing",
        }

    try:
        payload = json.loads(report_json.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "error": str(exc),
            "failed_signals": [],
            "passed": False,
            "report_json": str(report_json),
            "signal_count": 0,
            "signals_summary": {},
            "status": "invalid",
        }

    signals = payload.get("signals") if isinstance(payload.get("signals"), list) else []
    summary: dict[str, int] = {}
    failed_signals: list[dict[str, Any]] = []
    for signal in signals:
        if not isinstance(signal, dict):
            continue
        status = str(signal.get("status") or "unknown")
        summary[status] = summary.get(status, 0) + 1
        if status == "fail":
            failed_signals.append(signal)
    return {
        "failed_signals": failed_signals,
        "inputs": payload.get("inputs", {}),
        "passed": bool(payload.get("passed")),
        "report_json": str(report_json),
        "signal_count": len(signals),
        "signals_summary": summary,
        "status": str(payload.get("status") or "unknown"),
    }


def _artifact_count(artifacts: dict[str, Any]) -> int:
    count = 0
    for value in artifacts.values():
        if isinstance(value, list):
            count += len(value)
        else:
            count += 1
    return count


def _missing_required_artifacts(artifacts: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key, value in artifacts.items():
        records = value if isinstance(value, list) else [value]
        if not records and key in {"baseline_eval_reports", "eval_reports"}:
            missing.append(key)
        for record in records:
            if record.get("required") and not record.get("exists"):
                missing.append(key)
                break
    return missing


def _manifest_artifacts(
    prepared_inputs: dict[str, list[EvidenceInput] | EvidenceInput],
    *,
    release_health_report_json: Path,
) -> dict[str, Any]:
    readyz = prepared_inputs["readyz"]
    trajectory_stats = prepared_inputs["trajectory_stats"]
    replay_comparisons = prepared_inputs["replay_comparisons"]
    eval_reports = prepared_inputs["eval_reports"]
    baseline_eval_reports = prepared_inputs["baseline_eval_reports"]
    if not isinstance(readyz, EvidenceInput):
        raise TypeError("readyz artifact must be singular")
    if not isinstance(trajectory_stats, EvidenceInput):
        raise TypeError("trajectory_stats artifact must be singular")
    if not isinstance(replay_comparisons, EvidenceInput):
        raise TypeError("replay_comparisons artifact must be singular")
    return {
        "baseline_eval_reports": [
            _artifact_record(artifact) for artifact in baseline_eval_reports if isinstance(artifact, EvidenceInput)
        ],
        "eval_reports": [_artifact_record(artifact) for artifact in eval_reports if isinstance(artifact, EvidenceInput)],
        "readyz": _artifact_record(readyz),
        "release_health_report": _artifact_record(
            EvidenceInput("release_health_report", release_health_report_json, None, True, "generated")
        ),
        "replay_comparisons": _artifact_record(replay_comparisons),
        "trajectory_stats": _artifact_record(trajectory_stats),
    }


def run_release_evidence(
    *,
    dry_run: bool = False,
    release_id: str | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    output_dir: str | Path | None = None,
    readyz_json: str | Path | None = None,
    trajectory_stats_json: str | Path | None = None,
    replay_comparisons_json: str | Path | None = None,
    eval_report_json: Sequence[str | Path] = (),
    baseline_eval_report_json: Sequence[str | Path] = (),
    release_health_report_json: str | Path | None = None,
    root: Path | None = None,
    runner: Runner | None = None,
) -> dict[str, Any]:
    root = root or REPO_ROOT
    resolved_release_id = _normalize_release_id(release_id) if release_id else _default_release_id(root)
    pack_dir = _resolve_path(output_dir, root) if output_dir is not None else None
    if pack_dir is None:
        output_base = _resolve_path(output_root, root)
        if output_base is None:
            raise ValueError("output root could not be resolved")
        pack_dir = output_base / resolved_release_id
    pack_dir.mkdir(parents=True, exist_ok=True)

    report_json = _resolve_path(release_health_report_json, root) if release_health_report_json else None
    if report_json is None:
        report_json = pack_dir / "release-health.json"

    prepared_inputs = (
        _prepare_dry_run_inputs(pack_dir)
        if dry_run
        else _prepare_provided_inputs(
            pack_dir=pack_dir,
            root=root,
            readyz_json=readyz_json,
            trajectory_stats_json=trajectory_stats_json,
            replay_comparisons_json=replay_comparisons_json,
            eval_report_json=eval_report_json,
            baseline_eval_report_json=baseline_eval_report_json,
        )
    )

    command = _release_health_command(artifacts=prepared_inputs, report_json=report_json, root=root)
    selected_runner = runner or _subprocess_runner
    started_at = time.perf_counter()
    outcome = selected_runner(command, root)
    duration_seconds = time.perf_counter() - started_at

    commands = [_command_record(command=command, outcome=outcome, duration_seconds=duration_seconds)]
    artifacts = _manifest_artifacts(prepared_inputs, release_health_report_json=report_json)
    release_health = _load_release_health_summary(report_json)
    failed_commands = [command_record["label"] for command_record in commands if command_record["status"] == "failed"]
    missing_required_artifacts = _missing_required_artifacts(artifacts)
    failed = bool(failed_commands) or not bool(release_health["passed"]) or bool(missing_required_artifacts)
    status = "failed" if failed else "passed"
    manifest = {
        "artifacts": artifacts,
        "commands": commands,
        "meta": {
            "dry_run": dry_run,
            "generated_at": _utc_now(),
            "output_dir": str(pack_dir),
            "release_id": resolved_release_id,
            "root": str(root),
            "schema_version": 1,
        },
        "release_health": release_health,
        "summary": {
            "artifact_count": _artifact_count(artifacts),
            "baseline_eval_report_count": len(artifacts["baseline_eval_reports"]),
            "eval_report_count": len(artifacts["eval_reports"]),
            "failed_commands": failed_commands,
            "missing_required_artifacts": missing_required_artifacts,
            "status": status,
        },
    }
    manifest_json = pack_dir / "manifest.json"
    _write_json(manifest_json, manifest)
    manifest["manifest_json"] = str(manifest_json)
    return manifest


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Use deterministic sample artifacts.")
    parser.add_argument("--release-id", help="Release identifier. Defaults to git short SHA or UTC timestamp.")
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Evidence output root. Defaults to reports/release-gate.",
    )
    parser.add_argument(
        "--output-dir",
        help="Exact evidence pack directory. Overrides --output-root and --release-id path composition.",
    )
    parser.add_argument("--readyz-json", help="JSON payload from /readyz.")
    parser.add_argument("--trajectory-stats-json", help="Trajectory stats JSON payload.")
    parser.add_argument("--replay-comparisons-json", help="Replay comparison JSON payload.")
    parser.add_argument(
        "--eval-report-json",
        action="append",
        default=[],
        help="Eval report JSON. May be repeated.",
    )
    parser.add_argument(
        "--baseline-eval-report-json",
        action="append",
        default=[],
        help="Baseline eval report JSON. May be repeated.",
    )
    parser.add_argument(
        "--release-health-report-json",
        help="Path for the generated release-health JSON report.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = run_release_evidence(
            baseline_eval_report_json=args.baseline_eval_report_json,
            dry_run=bool(args.dry_run),
            eval_report_json=args.eval_report_json,
            output_dir=args.output_dir,
            output_root=args.output_root,
            readyz_json=args.readyz_json,
            release_health_report_json=args.release_health_report_json,
            release_id=args.release_id,
            replay_comparisons_json=args.replay_comparisons_json,
            trajectory_stats_json=args.trajectory_stats_json,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[release-evidence] {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "manifest_json": manifest["manifest_json"],
                "release_health_report_json": manifest["release_health"]["report_json"],
                "status": manifest["summary"]["status"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if manifest["summary"]["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
