"""Manifest, storage, and summary helpers for release evidence packs."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from scripts._report_io import load_json, resolve_optional_path
from scripts.release_evidence_types import CommandOutcome, EvidenceInput

TAIL_LINE_LIMIT = 80
TAIL_CHAR_LIMIT = 12_000
REQUIRED_PRODUCTION_ARTIFACT_KEYS = (
    "readyz",
    "trajectory_stats",
    "replay_comparisons",
    "production_smoke_report",
    "postgres_ops_report",
    "otel_smoke_report",
    "governance_report",
    "eval_reports",
    "baseline_eval_reports",
    "release_health_report",
)

def _format_utc(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

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
        "source_path": str(input_artifact.source_path)
        if input_artifact.source_path is not None
        else None,
    }

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

    run_id = env.get("GITHUB_RUN_ID") or env.get("BUILDKITE_BUILD_ID") or env.get("CI_PIPELINE_ID")
    artifact_name = env.get("RELEASE_GATE_ARTIFACT_NAME") or (
        f"release-gate-reports-{run_id}" if github_actions and run_id else None
    )
    return {
        "artifact_name": artifact_name,
        "branch": env.get("GITHUB_REF_NAME")
        or env.get("BUILDKITE_BRANCH")
        or env.get("CI_COMMIT_BRANCH"),
        "commit_sha": env.get("GITHUB_SHA")
        or env.get("BUILDKITE_COMMIT")
        or env.get("CI_COMMIT_SHA"),
        "environment_name": env.get("ENVIRONMENT_NAME"),
        "is_ci": bool(provider),
        "job": env.get("GITHUB_JOB") or env.get("BUILDKITE_LABEL") or env.get("CI_JOB_NAME"),
        "provider": provider,
        "ref": env.get("GITHUB_REF")
        or env.get("BUILDKITE_BRANCH")
        or env.get("CI_COMMIT_REF_NAME"),
        "repository": env.get("GITHUB_REPOSITORY")
        or env.get("BUILDKITE_PROJECT_SLUG")
        or env.get("CI_PROJECT_PATH"),
        "run_attempt": env.get("GITHUB_RUN_ATTEMPT"),
        "run_id": run_id,
        "run_number": env.get("GITHUB_RUN_NUMBER")
        or env.get("BUILDKITE_BUILD_NUMBER")
        or env.get("CI_PIPELINE_IID"),
        "workflow": env.get("GITHUB_WORKFLOW")
        or env.get("BUILDKITE_PIPELINE_NAME")
        or env.get("CI_PIPELINE_SOURCE"),
        "workflow_ref": env.get("GITHUB_WORKFLOW_REF"),
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
        payload = load_json(report_json)
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
    artifact_name: str | None,
    manifest_json: Path,
    pack_dir: Path,
    release_id: str,
    root: Path,
    storage_dir: str | Path | None,
    summary_json: Path,
) -> dict[str, Any]:
    if storage_dir is None:
        return {
            "artifact_name": artifact_name,
            "enabled": False,
            "manifest_json": str(manifest_json),
            "status": "disabled",
            "storage_dir": None,
            "stored_manifest_json": None,
            "stored_pack_dir": None,
            "stored_summary_json": None,
            "summary_json": str(summary_json),
        }

    storage_base = resolve_optional_path(storage_dir, root)
    if storage_base is None:
        raise ValueError("storage directory could not be resolved")
    stored_pack_dir = storage_base / release_id
    return {
        "artifact_name": artifact_name,
        "enabled": True,
        "manifest_json": str(manifest_json),
        "status": "stored",
        "storage_dir": str(storage_base),
        "stored_manifest_json": str(stored_pack_dir / manifest_json.name),
        "stored_pack_dir": str(stored_pack_dir),
        "stored_summary_json": str(stored_pack_dir / summary_json.name),
        "summary_json": str(summary_json),
    }

def _verify_storage_metadata(*, storage: dict[str, Any]) -> dict[str, Any]:
    if not storage.get("enabled"):
        return {
            "checked": False,
            "manifest_matches": False,
            "status": "disabled",
            "summary_matches": False,
        }

    manifest_json = Path(str(storage["manifest_json"]))
    summary_json = Path(str(storage["summary_json"]))
    stored_manifest_json = Path(str(storage["stored_manifest_json"]))
    stored_summary_json = Path(str(storage["stored_summary_json"]))
    manifest_matches = (
        manifest_json.exists()
        and stored_manifest_json.exists()
        and _sha256(manifest_json) == _sha256(stored_manifest_json)
    )
    summary_matches = (
        summary_json.exists()
        and stored_summary_json.exists()
        and _sha256(summary_json) == _sha256(stored_summary_json)
    )
    return {
        "checked": True,
        "manifest_matches": manifest_matches,
        "status": "verified" if manifest_matches and summary_matches else "failed",
        "summary_matches": summary_matches,
    }

def _manifest_hash_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _manifest_hash_payload(item)
            for key, item in value.items()
            if key
            not in {
                "manifest_normalized_sha256",
                "stored_manifest_normalized_sha256",
            }
        }
    if isinstance(value, list):
        return [_manifest_hash_payload(item) for item in value]
    return value

def _normalized_manifest_sha256(manifest: dict[str, Any]) -> str:
    payload = json.dumps(
        _manifest_hash_payload(manifest),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def _artifact_storage_metadata(
    *,
    ci: dict[str, Any],
    manifest: dict[str, Any],
    retention: dict[str, Any],
    storage: dict[str, Any],
) -> dict[str, Any]:
    manifest_hash = _normalized_manifest_sha256(manifest)
    return {
        "artifact_name": storage.get("artifact_name") or ci.get("artifact_name"),
        "enabled": bool(storage.get("enabled")),
        "manifest_json": storage.get("manifest_json"),
        "manifest_normalized_sha256": manifest_hash,
        "retention": retention,
        "retention_days": retention.get("days"),
        "status": storage.get("status"),
        "storage_dir": storage.get("storage_dir"),
        "stored_manifest_json": storage.get("stored_manifest_json"),
        "stored_manifest_normalized_sha256": manifest_hash
        if storage.get("stored_manifest_json")
        else None,
        "stored_pack_dir": storage.get("stored_pack_dir"),
        "stored_summary_json": storage.get("stored_summary_json"),
        "verification": storage.get("verification"),
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

def _sync_storage_manifest_files(*, storage: dict[str, Any]) -> None:
    if not storage.get("enabled"):
        return
    shutil.copy2(Path(str(storage["manifest_json"])), Path(str(storage["stored_manifest_json"])))
    shutil.copy2(Path(str(storage["summary_json"])), Path(str(storage["stored_summary_json"])))

def _approval_metadata(
    *,
    approval_id: str | None,
    approval_status: str | None,
    approval_url: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    status = approval_status or ("approved" if dry_run else "missing")
    approved = status == "approved" and bool(approval_id or dry_run)
    return {
        "approval_id": approval_id,
        "approval_url": approval_url,
        "approved": approved,
        "provider": "github_actions",
        "required": not dry_run,
        "status": status,
    }

def _production_validation(
    *,
    approval: dict[str, Any],
    artifacts: dict[str, Any],
    missing_required_artifacts: Sequence[str],
    release_health: dict[str, Any],
    storage: dict[str, Any],
) -> dict[str, Any]:
    report = (
        artifacts.get("release_health_report")
        if isinstance(artifacts.get("release_health_report"), dict)
        else {}
    )
    report_exists = bool(report.get("exists")) if isinstance(report, dict) else False
    report_status = str(release_health.get("status") or "unknown")
    report_passed = bool(release_health.get("passed"))
    storage_verification = (
        storage.get("verification") if isinstance(storage.get("verification"), dict) else {}
    )
    storage_required = bool(approval.get("required"))
    storage_enabled = bool(storage.get("enabled"))
    storage_ok = (
        storage_enabled and storage_verification.get("status") == "verified"
        if storage_required
        else (
            not storage_enabled
            or not storage_verification
            or storage_verification.get("status") == "verified"
        )
    )
    approval_ok = bool(approval.get("approved")) if approval.get("required") else True
    approval_url_present = bool(approval.get("approval_url")) if approval.get("required") else True
    return {
        "approval_approved": approval_ok,
        "approval_url_present": approval_url_present,
        "missing_required_artifacts": list(missing_required_artifacts),
        "passed": (
            not missing_required_artifacts
            and report_exists
            and report_passed
            and report_status == "passed"
            and storage_ok
            and approval_ok
            and approval_url_present
        ),
        "release_health_passed": report_passed,
        "release_health_report_exists": report_exists,
        "release_health_status": report_status,
        "required_artifacts": list(REQUIRED_PRODUCTION_ARTIFACT_KEYS),
        "storage_enabled": storage_enabled,
        "storage_required": storage_required,
        "storage_verified": storage_ok,
    }

def _failure_summary(
    *,
    approval: dict[str, Any],
    commands: Sequence[dict[str, Any]],
    missing_required_artifacts: Sequence[str],
    release_health: dict[str, Any],
    storage: dict[str, Any],
) -> dict[str, Any]:
    failed_commands = [
        str(command["label"]) for command in commands if command.get("status") == "failed"
    ]
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
        reasons.append(
            {"detail": list(missing_required_artifacts), "kind": "missing_required_artifacts"}
        )
    if approval.get("required") and not approval.get("approved"):
        reasons.append({"detail": approval, "kind": "release_approval_missing"})
    if approval.get("required") and not approval.get("approval_url"):
        reasons.append({"detail": approval, "kind": "release_approval_url_missing"})
    storage_verification = (
        storage.get("verification") if isinstance(storage.get("verification"), dict) else {}
    )
    if approval.get("required") and not storage.get("enabled"):
        reasons.append({"detail": storage, "kind": "artifact_storage_missing"})
    elif storage.get("enabled") and storage_verification.get("status") != "verified":
        reasons.append(
            {"detail": storage_verification, "kind": "artifact_storage_verification_failed"}
        )
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
    approval: dict[str, Any],
    artifact_summary: dict[str, Any],
    artifact_storage: dict[str, Any],
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
        "artifact_storage": artifact_storage,
        "approval": approval,
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
            "verification": storage.get("verification"),
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
    alert_report = prepared_inputs.get("alert_report")
    postgres_migration_report = prepared_inputs.get("postgres_migration_report")
    production_smoke_report = prepared_inputs.get("production_smoke_report")
    postgres_ops_report = prepared_inputs.get("postgres_ops_report")
    otel_smoke_report = prepared_inputs.get("otel_smoke_report")
    governance_report = prepared_inputs.get("governance_report")
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
            _artifact_record(artifact)
            for artifact in baseline_eval_reports
            if isinstance(artifact, EvidenceInput)
        ],
        "eval_reports": [
            _artifact_record(artifact)
            for artifact in eval_reports
            if isinstance(artifact, EvidenceInput)
        ],
        "alert_report": _artifact_record(alert_report)
        if isinstance(alert_report, EvidenceInput)
        else _artifact_record(EvidenceInput("alert_report", None, None, False, "input")),
        "postgres_migration_report": _artifact_record(postgres_migration_report)
        if isinstance(postgres_migration_report, EvidenceInput)
        else _artifact_record(
            EvidenceInput("postgres_migration_report", None, None, False, "input")
        ),
        "production_smoke_report": _artifact_record(production_smoke_report)
        if isinstance(production_smoke_report, EvidenceInput)
        else _artifact_record(EvidenceInput("production_smoke_report", None, None, True, "input")),
        "postgres_ops_report": _artifact_record(postgres_ops_report)
        if isinstance(postgres_ops_report, EvidenceInput)
        else _artifact_record(EvidenceInput("postgres_ops_report", None, None, True, "input")),
        "otel_smoke_report": _artifact_record(otel_smoke_report)
        if isinstance(otel_smoke_report, EvidenceInput)
        else _artifact_record(EvidenceInput("otel_smoke_report", None, None, True, "input")),
        "governance_report": _artifact_record(governance_report)
        if isinstance(governance_report, EvidenceInput)
        else _artifact_record(EvidenceInput("governance_report", None, None, True, "input")),
        "readyz": _artifact_record(readyz),
        "release_health_report": _artifact_record(
            EvidenceInput(
                "release_health_report", release_health_report_json, None, True, "generated"
            )
        ),
        "replay_comparisons": _artifact_record(replay_comparisons),
        "trajectory_stats": _artifact_record(trajectory_stats),
    }
