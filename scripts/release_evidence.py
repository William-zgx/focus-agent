#!/usr/bin/env python3
"""Build a machine-readable production release evidence pack."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = Path("reports/release-gate")
TAIL_LINE_LIMIT = 80
TAIL_CHAR_LIMIT = 12_000
DEFAULT_RETENTION_DAYS = 90
REQUIRED_PRODUCTION_ARTIFACT_KEYS = (
    "readyz",
    "trajectory_stats",
    "replay_comparisons",
    "eval_reports",
    "baseline_eval_reports",
    "release_health_report",
)


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


def _format_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


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


def _default_release_id_with_source(root: Path) -> tuple[str, str]:
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
        return _normalize_release_id(completed.stdout.strip()), "git"
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"), "timestamp"


def _default_release_id(root: Path) -> str:
    release_id, _source = _default_release_id_with_source(root)
    return release_id


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


def _ci_metadata(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = env or os.environ
    github_actions = env.get("GITHUB_ACTIONS") == "true"
    buildkite = bool(env.get("BUILDKITE"))
    generic_ci = bool(env.get("CI"))
    provider = None
    if github_actions:
        provider = "github_actions"
    elif buildkite:
        provider = "buildkite"
    elif generic_ci:
        provider = "generic"

    return {
        "branch": env.get("GITHUB_REF_NAME") or env.get("BUILDKITE_BRANCH") or env.get("CI_COMMIT_BRANCH"),
        "commit_sha": env.get("GITHUB_SHA") or env.get("BUILDKITE_COMMIT") or env.get("CI_COMMIT_SHA"),
        "is_ci": bool(provider),
        "job": env.get("GITHUB_JOB") or env.get("BUILDKITE_LABEL") or env.get("CI_JOB_NAME"),
        "provider": provider,
        "ref": env.get("GITHUB_REF") or env.get("BUILDKITE_BRANCH") or env.get("CI_COMMIT_REF_NAME"),
        "repository": env.get("GITHUB_REPOSITORY") or env.get("BUILDKITE_PROJECT_SLUG") or env.get("CI_PROJECT_PATH"),
        "run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
        "run_id": env.get("GITHUB_RUN_ID") or env.get("BUILDKITE_BUILD_ID") or env.get("CI_PIPELINE_ID"),
        "run_number": env.get("GITHUB_RUN_NUMBER")
        or env.get("BUILDKITE_BUILD_NUMBER")
        or env.get("CI_PIPELINE_IID"),
        "workflow": env.get("GITHUB_WORKFLOW") or env.get("BUILDKITE_PIPELINE_NAME") or env.get("CI_PIPELINE_SOURCE"),
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


def _iter_artifact_records(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for value in artifacts.values():
        if isinstance(value, list):
            records.extend(record for record in value if isinstance(record, dict))
        elif isinstance(value, dict):
            records.append(value)
    return records


def _artifact_summary(artifacts: dict[str, Any]) -> dict[str, Any]:
    records = _iter_artifact_records(artifacts)
    by_kind: dict[str, dict[str, int]] = {}
    for record in records:
        kind = str(record.get("kind") or "unknown")
        kind_summary = by_kind.setdefault(
            kind,
            {"bytes": 0, "missing": 0, "present": 0, "required": 0, "total": 0},
        )
        exists = bool(record.get("exists"))
        required = bool(record.get("required"))
        kind_summary["bytes"] += int(record.get("bytes") or 0)
        kind_summary["missing"] += 0 if exists else 1
        kind_summary["present"] += 1 if exists else 0
        kind_summary["required"] += 1 if required else 0
        kind_summary["total"] += 1

    present = sum(1 for record in records if record.get("exists"))
    required = sum(1 for record in records if record.get("required"))
    missing = len(records) - present
    total_bytes = sum(int(record.get("bytes") or 0) for record in records)
    return {
        "by_kind": by_kind,
        "missing": missing,
        "present": present,
        "required": required,
        "total": len(records),
        "total_bytes": total_bytes,
    }


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


def _retention_metadata(*, generated_at: datetime, retention_days: int) -> dict[str, Any]:
    if retention_days < 1:
        raise ValueError("--retention-days must be at least 1")
    retain_until = generated_at + timedelta(days=retention_days)
    return {
        "days": retention_days,
        "generated_at": _format_utc(generated_at),
        "policy": "retain-evidence-pack",
        "retain_until": _format_utc(retain_until),
    }


def _storage_metadata(
    *,
    manifest_json: Path,
    pack_dir: Path,
    release_id: str,
    root: Path,
    storage_dir: str | Path | None,
    summary_json: Path,
) -> dict[str, Any]:
    if storage_dir is None:
        return {
            "enabled": False,
            "manifest_json": str(manifest_json),
            "status": "disabled",
            "storage_dir": None,
            "stored_manifest_json": None,
            "stored_pack_dir": None,
            "stored_summary_json": None,
            "summary_json": str(summary_json),
        }

    storage_base = _resolve_path(storage_dir, root)
    if storage_base is None:
        raise ValueError("storage directory could not be resolved")
    stored_pack_dir = storage_base / release_id
    return {
        "enabled": True,
        "manifest_json": str(manifest_json),
        "status": "stored",
        "storage_dir": str(storage_base),
        "stored_manifest_json": str(stored_pack_dir / manifest_json.name),
        "stored_pack_dir": str(stored_pack_dir),
        "stored_summary_json": str(stored_pack_dir / summary_json.name),
        "summary_json": str(summary_json),
    }


def _copy_pack_to_storage(*, pack_dir: Path, storage: dict[str, Any]) -> None:
    if not storage.get("enabled"):
        return

    stored_pack_dir = Path(str(storage["stored_pack_dir"]))
    pack_dir_resolved = pack_dir.resolve()
    stored_pack_dir_resolved = stored_pack_dir.resolve()
    if stored_pack_dir_resolved == pack_dir_resolved:
        return
    if stored_pack_dir_resolved.is_relative_to(pack_dir_resolved):
        raise ValueError("--storage-dir cannot resolve inside the evidence pack directory")
    if stored_pack_dir.exists():
        raise FileExistsError(f"evidence storage target already exists: {stored_pack_dir}")
    stored_pack_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(pack_dir, stored_pack_dir)


def _production_validation(
    *,
    artifacts: dict[str, Any],
    missing_required_artifacts: Sequence[str],
    release_health: dict[str, Any],
) -> dict[str, Any]:
    report = artifacts.get("release_health_report") if isinstance(artifacts.get("release_health_report"), dict) else {}
    report_exists = bool(report.get("exists")) if isinstance(report, dict) else False
    report_status = str(release_health.get("status") or "unknown")
    report_passed = bool(release_health.get("passed"))
    return {
        "missing_required_artifacts": list(missing_required_artifacts),
        "passed": not missing_required_artifacts and report_exists and report_passed and report_status == "passed",
        "release_health_passed": report_passed,
        "release_health_report_exists": report_exists,
        "release_health_status": report_status,
        "required_artifacts": list(REQUIRED_PRODUCTION_ARTIFACT_KEYS),
    }


def _failure_summary(
    *,
    commands: Sequence[dict[str, Any]],
    missing_required_artifacts: Sequence[str],
    release_health: dict[str, Any],
) -> dict[str, Any]:
    failed_commands = [str(command["label"]) for command in commands if command.get("status") == "failed"]
    failed_signals = [
        {
            "detail": signal.get("detail"),
            "key": signal.get("key"),
            "status": signal.get("status"),
            "summary": signal.get("summary"),
        }
        for signal in release_health.get("failed_signals", [])
        if isinstance(signal, dict)
    ]
    reasons: list[dict[str, Any]] = []
    if failed_commands:
        reasons.append({"detail": failed_commands, "kind": "failed_commands"})
    if missing_required_artifacts:
        reasons.append({"detail": list(missing_required_artifacts), "kind": "missing_required_artifacts"})
    if not bool(release_health.get("passed")):
        reasons.append(
            {
                "detail": {
                    "failed_signal_count": len(failed_signals),
                    "status": release_health.get("status"),
                },
                "kind": "release_health_failed",
            }
        )
    return {
        "failed": bool(reasons),
        "failed_commands": failed_commands,
        "failed_signal_count": len(failed_signals),
        "failed_signals": failed_signals,
        "missing_required_artifacts": list(missing_required_artifacts),
        "reason_count": len(reasons),
        "reasons": reasons,
        "release_health_status": release_health.get("status"),
    }


def _summary_payload(
    *,
    artifact_summary: dict[str, Any],
    failure_summary: dict[str, Any],
    manifest_json: Path,
    release_health: dict[str, Any],
    retention: dict[str, Any],
    storage: dict[str, Any],
    summary: dict[str, Any],
    release_id: str,
) -> dict[str, Any]:
    return {
        "artifact_summary": artifact_summary,
        "failure_summary": failure_summary,
        "manifest_json": str(manifest_json),
        "release_health": {
            "failed_signal_count": len(release_health.get("failed_signals", [])),
            "passed": bool(release_health.get("passed")),
            "report_json": release_health.get("report_json"),
            "status": release_health.get("status"),
        },
        "release_id": release_id,
        "retention": retention,
        "status": summary["status"],
        "storage": {
            "enabled": bool(storage.get("enabled")),
            "status": storage.get("status"),
            "stored_pack_dir": storage.get("stored_pack_dir"),
        },
        "summary": summary,
    }


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
    retention_days: int = DEFAULT_RETENTION_DAYS,
    readyz_json: str | Path | None = None,
    trajectory_stats_json: str | Path | None = None,
    replay_comparisons_json: str | Path | None = None,
    eval_report_json: Sequence[str | Path] = (),
    baseline_eval_report_json: Sequence[str | Path] = (),
    release_health_report_json: str | Path | None = None,
    storage_dir: str | Path | None = None,
    root: Path | None = None,
    runner: Runner | None = None,
) -> dict[str, Any]:
    root = root or REPO_ROOT
    if not dry_run and not release_id:
        raise ValueError("--release-id is required for production evidence packs")
    if release_id:
        resolved_release_id = _normalize_release_id(release_id)
        release_id_source = "explicit"
    else:
        resolved_release_id, release_id_source = _default_release_id_with_source(root)
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
    production_validation = _production_validation(
        artifacts=artifacts,
        missing_required_artifacts=missing_required_artifacts,
        release_health=release_health,
    )
    failed = (
        bool(failed_commands)
        or not bool(release_health["passed"])
        or bool(missing_required_artifacts)
        or not bool(production_validation["passed"])
    )
    status = "failed" if failed else "passed"
    generated_at = datetime.now(UTC)
    retention = _retention_metadata(generated_at=generated_at, retention_days=retention_days)
    manifest_json = pack_dir / "manifest.json"
    summary_json = pack_dir / "summary.json"
    storage = _storage_metadata(
        manifest_json=manifest_json,
        pack_dir=pack_dir,
        release_id=resolved_release_id,
        root=root,
        storage_dir=storage_dir,
        summary_json=summary_json,
    )
    artifact_summary = _artifact_summary(artifacts)
    failure_summary = _failure_summary(
        commands=commands,
        missing_required_artifacts=missing_required_artifacts,
        release_health=release_health,
    )
    summary = {
        "artifact_count": _artifact_count(artifacts),
        "baseline_eval_report_count": len(artifacts["baseline_eval_reports"]),
        "eval_report_count": len(artifacts["eval_reports"]),
        "failed_commands": failed_commands,
        "missing_required_artifacts": missing_required_artifacts,
        "required_artifact_count": len(REQUIRED_PRODUCTION_ARTIFACT_KEYS),
        "status": status,
        "summary_json": str(summary_json),
    }
    manifest = {
        "artifact_summary": artifact_summary,
        "artifacts": artifacts,
        "commands": commands,
        "failure_summary": failure_summary,
        "meta": {
            "ci": _ci_metadata(),
            "dry_run": dry_run,
            "generated_at": _format_utc(generated_at),
            "output_dir": str(pack_dir),
            "release_id_source": release_id_source,
            "release_id": resolved_release_id,
            "root": str(root),
            "schema_version": 1,
        },
        "production_validation": production_validation,
        "release_health": release_health,
        "retention": retention,
        "storage": storage,
        "summary": summary,
    }
    _write_json(manifest_json, manifest)
    _write_json(
        summary_json,
        _summary_payload(
            artifact_summary=artifact_summary,
            failure_summary=failure_summary,
            manifest_json=manifest_json,
            release_health=release_health,
            release_id=resolved_release_id,
            retention=retention,
            storage=storage,
            summary=summary,
        ),
    )
    _copy_pack_to_storage(pack_dir=pack_dir, storage=storage)
    manifest["manifest_json"] = str(manifest_json)
    return manifest


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Use deterministic sample artifacts.")
    parser.add_argument(
        "--release-id",
        help="Release identifier. Required for production packs; dry-runs default to git short SHA or UTC timestamp.",
    )
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
    parser.add_argument(
        "--retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help="Retention window to record in manifest metadata. Defaults to 90 days.",
    )
    parser.add_argument(
        "--storage-dir",
        help="Optional artifact storage directory. The evidence pack is copied to <storage-dir>/<release-id>.",
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
            retention_days=args.retention_days,
            replay_comparisons_json=args.replay_comparisons_json,
            storage_dir=args.storage_dir,
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
