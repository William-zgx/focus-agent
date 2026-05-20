#!/usr/bin/env python3
"""Build a machine-readable production release evidence pack."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts._report_io import (  # noqa: E402
    print_json_stdout,
    resolve_optional_path,
    write_json_report,
)
from scripts.release_evidence_inputs import prepare_dry_run_inputs  # noqa: E402
from scripts.release_evidence_manifest import (  # noqa: E402
    REQUIRED_PRODUCTION_ARTIFACT_KEYS,
    _approval_metadata,
    _artifact_count,
    _artifact_storage_metadata,
    _artifact_summary,
    _ci_metadata,
    _command_record,
    _copy_pack_to_storage,
    _failure_summary,
    _format_utc,
    _load_release_health_summary,
    _manifest_artifacts,
    _missing_required_artifacts,
    _production_validation,
    _retention_metadata,
    _storage_metadata,
    _summary_payload,
    _sync_storage_manifest_files,
    _verify_storage_metadata,
)
from scripts.release_evidence_types import CommandOutcome, EvidenceInput  # noqa: E402

DEFAULT_OUTPUT_ROOT = Path("reports/release-gate")
TAIL_LINE_LIMIT = 80
TAIL_CHAR_LIMIT = 12_000
DEFAULT_RETENTION_DAYS = 90


Runner = Callable[[Sequence[str], Path], CommandOutcome]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
    return write_json_report(path, payload)


def _copy_or_reference_json(
    source: str | Path | None, target: Path, *, root: Path
) -> tuple[Path | None, Path | None]:
    source_path = resolve_optional_path(source, root)
    if source_path is None:
        return None, None
    if not source_path.exists():
        return source_path, source_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target)
    return target, source_path


def _prepare_dry_run_inputs(pack_dir: Path) -> dict[str, list[EvidenceInput] | EvidenceInput]:
    return prepare_dry_run_inputs(
        pack_dir,
        evidence_input=EvidenceInput,
        write_json=_write_json,
    )


def _prepare_provided_inputs(
    *,
    pack_dir: Path,
    root: Path,
    readyz_json: str | Path | None,
    trajectory_stats_json: str | Path | None,
    replay_comparisons_json: str | Path | None,
    alert_report_json: str | Path | None,
    postgres_migration_report_json: str | Path | None,
    production_smoke_report_json: str | Path | None,
    postgres_ops_report_json: str | Path | None,
    otel_smoke_report_json: str | Path | None,
    governance_report_json: str | Path | None,
    eval_report_json: Sequence[str | Path],
    baseline_eval_report_json: Sequence[str | Path],
) -> dict[str, list[EvidenceInput] | EvidenceInput]:
    inputs_dir = pack_dir / "inputs"
    readyz_path, readyz_source = _copy_or_reference_json(
        readyz_json, inputs_dir / "readyz.json", root=root
    )
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
    alert_path, alert_source = _copy_or_reference_json(
        alert_report_json,
        inputs_dir / "alert-report.json",
        root=root,
    )
    postgres_migration_path, postgres_migration_source = _copy_or_reference_json(
        postgres_migration_report_json,
        inputs_dir / "postgres-migration-report.json",
        root=root,
    )
    production_smoke_path, production_smoke_source = _copy_or_reference_json(
        production_smoke_report_json,
        inputs_dir / "production-smoke-report.json",
        root=root,
    )
    postgres_ops_path, postgres_ops_source = _copy_or_reference_json(
        postgres_ops_report_json,
        inputs_dir / "postgres-ops-report.json",
        root=root,
    )
    otel_smoke_path, otel_smoke_source = _copy_or_reference_json(
        otel_smoke_report_json,
        inputs_dir / "otel-smoke-report.json",
        root=root,
    )
    governance_path, governance_source = _copy_or_reference_json(
        governance_report_json,
        inputs_dir / "governance-report.json",
        root=root,
    )

    eval_reports: list[EvidenceInput] = []
    for index, raw_path in enumerate(eval_report_json, start=1):
        path, source_path = _copy_or_reference_json(
            raw_path, inputs_dir / f"eval-report-{index}.json", root=root
        )
        eval_reports.append(EvidenceInput("eval_report", path, source_path, True, "input"))

    baseline_eval_reports: list[EvidenceInput] = []
    for index, raw_path in enumerate(baseline_eval_report_json, start=1):
        path, source_path = _copy_or_reference_json(
            raw_path,
            inputs_dir / f"baseline-eval-report-{index}.json",
            root=root,
        )
        baseline_eval_reports.append(
            EvidenceInput("baseline_eval_report", path, source_path, True, "input")
        )

    return {
        "alert_report": EvidenceInput("alert_report", alert_path, alert_source, False, "input"),
        "production_smoke_report": EvidenceInput(
            "production_smoke_report",
            production_smoke_path,
            production_smoke_source,
            True,
            "input",
        ),
        "postgres_ops_report": EvidenceInput(
            "postgres_ops_report",
            postgres_ops_path,
            postgres_ops_source,
            True,
            "input",
        ),
        "otel_smoke_report": EvidenceInput(
            "otel_smoke_report",
            otel_smoke_path,
            otel_smoke_source,
            True,
            "input",
        ),
        "governance_report": EvidenceInput(
            "governance_report",
            governance_path,
            governance_source,
            True,
            "input",
        ),
        "readyz": EvidenceInput("readyz", readyz_path, readyz_source, True, "input"),
        "trajectory_stats": EvidenceInput(
            "trajectory_stats", stats_path, stats_source, True, "input"
        ),
        "replay_comparisons": EvidenceInput(
            "replay_comparisons", replay_path, replay_source, True, "input"
        ),
        "eval_reports": eval_reports,
        "baseline_eval_reports": baseline_eval_reports,
        "postgres_migration_report": EvidenceInput(
            "postgres_migration_report",
            postgres_migration_path,
            postgres_migration_source,
            False,
            "input",
        ),
    }


def _release_health_command(
    *,
    allow_dry_run_reports: bool = False,
    artifacts: dict[str, list[EvidenceInput] | EvidenceInput],
    mode: str = "production",
    report_json: Path,
    root: Path,
) -> tuple[str, ...]:
    command: list[str] = [
        sys.executable,
        str(root / "scripts" / "release_health_check.py"),
        "--mode",
        mode,
    ]
    readyz = artifacts["readyz"]
    trajectory_stats = artifacts["trajectory_stats"]
    replay_comparisons = artifacts["replay_comparisons"]
    alert_report = artifacts.get("alert_report")
    postgres_migration_report = artifacts.get("postgres_migration_report")
    production_smoke_report = artifacts.get("production_smoke_report")
    postgres_ops_report = artifacts.get("postgres_ops_report")
    otel_smoke_report = artifacts.get("otel_smoke_report")
    governance_report = artifacts.get("governance_report")
    if isinstance(readyz, EvidenceInput) and readyz.path is not None:
        command.extend(("--readyz-json", str(readyz.path)))
    if isinstance(trajectory_stats, EvidenceInput) and trajectory_stats.path is not None:
        command.extend(("--trajectory-stats-json", str(trajectory_stats.path)))
    if isinstance(replay_comparisons, EvidenceInput) and replay_comparisons.path is not None:
        command.extend(("--replay-comparisons-json", str(replay_comparisons.path)))
    if isinstance(alert_report, EvidenceInput) and alert_report.path is not None:
        command.extend(("--alert-report-json", str(alert_report.path)))
    if (
        isinstance(postgres_migration_report, EvidenceInput)
        and postgres_migration_report.path is not None
    ):
        command.extend(("--postgres-migration-report-json", str(postgres_migration_report.path)))
    if (
        isinstance(production_smoke_report, EvidenceInput)
        and production_smoke_report.path is not None
    ):
        command.extend(("--production-smoke-report-json", str(production_smoke_report.path)))
    if isinstance(postgres_ops_report, EvidenceInput) and postgres_ops_report.path is not None:
        command.extend(("--postgres-ops-report-json", str(postgres_ops_report.path)))
    if isinstance(otel_smoke_report, EvidenceInput) and otel_smoke_report.path is not None:
        command.extend(("--otel-smoke-report-json", str(otel_smoke_report.path)))
    if isinstance(governance_report, EvidenceInput) and governance_report.path is not None:
        command.extend(("--governance-report-json", str(governance_report.path)))
    eval_reports = artifacts["eval_reports"]
    baseline_eval_reports = artifacts["baseline_eval_reports"]
    for artifact in eval_reports if isinstance(eval_reports, list) else []:
        if artifact.path is not None:
            command.extend(("--eval-report-json", str(artifact.path)))
    for artifact in baseline_eval_reports if isinstance(baseline_eval_reports, list) else []:
        if artifact.path is not None:
            command.extend(("--baseline-eval-report-json", str(artifact.path)))
    if allow_dry_run_reports:
        command.append("--allow-dry-run-reports")
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
    alert_report_json: str | Path | None = None,
    postgres_migration_report_json: str | Path | None = None,
    production_smoke_report_json: str | Path | None = None,
    postgres_ops_report_json: str | Path | None = None,
    otel_smoke_report_json: str | Path | None = None,
    governance_report_json: str | Path | None = None,
    eval_report_json: Sequence[str | Path] = (),
    baseline_eval_report_json: Sequence[str | Path] = (),
    release_health_report_json: str | Path | None = None,
    storage_dir: str | Path | None = None,
    approval_id: str | None = None,
    approval_status: str | None = None,
    approval_url: str | None = None,
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
    pack_dir = resolve_optional_path(output_dir, root) if output_dir is not None else None
    if pack_dir is None:
        output_base = resolve_optional_path(output_root, root)
        if output_base is None:
            raise ValueError("output root could not be resolved")
        pack_dir = output_base / resolved_release_id
    pack_dir.mkdir(parents=True, exist_ok=True)

    report_json = (
        resolve_optional_path(release_health_report_json, root)
        if release_health_report_json
        else None
    )
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
            alert_report_json=alert_report_json,
            postgres_migration_report_json=postgres_migration_report_json,
            production_smoke_report_json=production_smoke_report_json,
            postgres_ops_report_json=postgres_ops_report_json,
            otel_smoke_report_json=otel_smoke_report_json,
            governance_report_json=governance_report_json,
            eval_report_json=eval_report_json,
            baseline_eval_report_json=baseline_eval_report_json,
        )
    )

    command = _release_health_command(
        allow_dry_run_reports=dry_run,
        artifacts=prepared_inputs,
        mode="local" if dry_run else "production",
        report_json=report_json,
        root=root,
    )
    selected_runner = runner or _subprocess_runner
    started_at = time.perf_counter()
    outcome = selected_runner(command, root)
    duration_seconds = time.perf_counter() - started_at

    commands = [
        _command_record(command=command, outcome=outcome, duration_seconds=duration_seconds)
    ]
    artifacts = _manifest_artifacts(prepared_inputs, release_health_report_json=report_json)
    release_health = _load_release_health_summary(report_json)
    failed_commands = [
        command_record["label"]
        for command_record in commands
        if command_record["status"] == "failed"
    ]
    missing_required_artifacts = _missing_required_artifacts(artifacts)
    generated_at = datetime.now(UTC)
    retention = _retention_metadata(generated_at=generated_at, retention_days=retention_days)
    manifest_json = pack_dir / "manifest.json"
    summary_json = pack_dir / "summary.json"
    ci = _ci_metadata()
    approval = _approval_metadata(
        approval_id=approval_id,
        approval_status=approval_status,
        approval_url=approval_url,
        dry_run=dry_run,
    )
    storage = _storage_metadata(
        artifact_name=ci.get("artifact_name") if isinstance(ci.get("artifact_name"), str) else None,
        manifest_json=manifest_json,
        pack_dir=pack_dir,
        release_id=resolved_release_id,
        root=root,
        storage_dir=storage_dir,
        summary_json=summary_json,
    )
    production_validation = _production_validation(
        approval=approval,
        artifacts=artifacts,
        missing_required_artifacts=missing_required_artifacts,
        release_health=release_health,
        storage=storage,
    )
    failed = (
        bool(failed_commands)
        or not bool(release_health["passed"])
        or bool(missing_required_artifacts)
        or not bool(production_validation["passed"])
    )
    status = "failed" if failed else "passed"
    artifact_summary = _artifact_summary(artifacts)
    failure_summary = _failure_summary(
        approval=approval,
        commands=commands,
        missing_required_artifacts=missing_required_artifacts,
        release_health=release_health,
        storage=storage,
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
        "approval": approval,
        "artifact_summary": artifact_summary,
        "artifact_storage": {},
        "artifacts": artifacts,
        "ci": ci,
        "commands": commands,
        "failure_summary": failure_summary,
        "meta": {
            "ci": ci,
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
    manifest["artifact_storage"] = _artifact_storage_metadata(
        ci=ci,
        manifest=manifest,
        retention=retention,
        storage=storage,
    )
    _write_json(manifest_json, manifest)
    _write_json(
        summary_json,
        _summary_payload(
            approval=approval,
            artifact_summary=artifact_summary,
            artifact_storage=manifest["artifact_storage"],
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
    storage["verification"] = _verify_storage_metadata(storage=storage)
    manifest["storage"] = storage
    manifest["production_validation"] = _production_validation(
        approval=approval,
        artifacts=artifacts,
        missing_required_artifacts=missing_required_artifacts,
        release_health=release_health,
        storage=storage,
    )
    final_failed = (
        bool(failed_commands)
        or not bool(release_health["passed"])
        or bool(missing_required_artifacts)
        or not bool(manifest["production_validation"]["passed"])
    )
    summary["status"] = "failed" if final_failed else "passed"
    manifest["summary"] = summary
    manifest["failure_summary"] = _failure_summary(
        approval=approval,
        commands=commands,
        missing_required_artifacts=missing_required_artifacts,
        release_health=release_health,
        storage=storage,
    )
    manifest["artifact_storage"] = _artifact_storage_metadata(
        ci=ci,
        manifest=manifest,
        retention=retention,
        storage=storage,
    )
    _write_json(manifest_json, manifest)
    _write_json(
        summary_json,
        _summary_payload(
            approval=approval,
            artifact_summary=artifact_summary,
            artifact_storage=manifest["artifact_storage"],
            failure_summary=manifest["failure_summary"],
            manifest_json=manifest_json,
            release_health=release_health,
            release_id=resolved_release_id,
            retention=retention,
            storage=storage,
            summary=summary,
        ),
    )
    _sync_storage_manifest_files(storage=storage)
    manifest["manifest_json"] = str(manifest_json)
    return manifest


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Use deterministic sample artifacts."
    )
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
    parser.add_argument("--alert-report-json", help="Executable alert rules report JSON.")
    parser.add_argument(
        "--postgres-migration-report-json", help="Postgres migration verification report JSON."
    )
    parser.add_argument("--production-smoke-report-json", help="Production smoke report JSON.")
    parser.add_argument("--postgres-ops-report-json", help="Postgres ops report JSON.")
    parser.add_argument("--otel-smoke-report-json", help="OpenTelemetry smoke report JSON.")
    parser.add_argument("--governance-report-json", help="Agent governance quality report JSON.")
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
    parser.add_argument(
        "--approval-id", help="Release approval identifier from the deployment platform."
    )
    parser.add_argument(
        "--approval-status",
        choices=("approved", "pending", "rejected", "missing"),
        help="Release approval status. Production evidence passes only when this is approved.",
    )
    parser.add_argument("--approval-url", help="Optional URL for the approval record.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = run_release_evidence(
            alert_report_json=args.alert_report_json,
            approval_id=args.approval_id,
            approval_status=args.approval_status,
            approval_url=args.approval_url,
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
            postgres_migration_report_json=args.postgres_migration_report_json,
            production_smoke_report_json=args.production_smoke_report_json,
            postgres_ops_report_json=args.postgres_ops_report_json,
            otel_smoke_report_json=args.otel_smoke_report_json,
            governance_report_json=args.governance_report_json,
            storage_dir=args.storage_dir,
            trajectory_stats_json=args.trajectory_stats_json,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[release-evidence] {exc}", file=sys.stderr)
        return 2

    print_json_stdout(
        {
            "manifest_json": manifest["manifest_json"],
            "release_health_report_json": manifest["release_health"]["report_json"],
            "status": manifest["summary"]["status"],
        },
        sort_keys=True,
    )
    return 1 if manifest["summary"]["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
