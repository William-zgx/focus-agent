"""Release identity and input freshness validation for evidence packs."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts._report_io import load_json
from scripts.release_evidence_types import EvidenceInput

DEFAULT_MAX_EVIDENCE_AGE_SECONDS = 6 * 60 * 60
FUTURE_TIMESTAMP_TOLERANCE_SECONDS = 5 * 60

_TIMESTAMP_PATHS = (
    ("generated_at",),
    ("meta", "generated_at"),
    ("checked_at",),
    ("completed_at",),
    ("finished_at",),
    ("timestamp",),
)
_BINDING_PATHS = (
    ("release_binding",),
    ("meta", "release_binding"),
)
_BINDING_ALIASES = {
    "commit_sha": ("commit_sha", "git_sha", "revision", "sha"),
    "deployment_id": ("deployment_id", "deployment", "deployment_name"),
    "deployment_version": ("deployment_version", "app_version"),
    "environment": ("environment", "environment_name"),
}
_COMMIT_SHA_PATTERN = re.compile(r"[0-9a-fA-F]{7,64}")
_RELEASE_BINDING_ERROR_CODES = {
    "release_binding_missing",
    "release_binding_source_mismatch",
    "release_commit_invalid",
    "release_commit_not_current",
    "release_environment_invalid",
}


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _non_empty(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _canonical_environment(value: str) -> str:
    normalized = value.strip().lower()
    return "production" if normalized == "prod" else normalized


def _nested_value(payload: Any, path: tuple[str, ...]) -> Any:
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _parse_timestamp(value: Any) -> datetime:
    text = _non_empty(value)
    if text is None:
        raise ValueError("timestamp is empty")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _current_commit_sha(root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _resolve_commit_sha(root: Path, value: str) -> str | None:
    try:
        completed = subprocess.run(
            ("git", "rev-parse", "--verify", f"{value}^{{commit}}"),
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def _candidate(
    *values: tuple[str, Any],
    canonicalize: bool = False,
) -> tuple[str | None, str | None, list[dict[str, str]]]:
    candidates: list[dict[str, str]] = []
    for source, raw_value in values:
        value = _non_empty(raw_value)
        if value is None:
            continue
        if canonicalize:
            value = _canonical_environment(value)
        candidates.append({"source": source, "value": value})
    if not candidates:
        return None, None, []
    return candidates[0]["value"], candidates[0]["source"], candidates


def _candidate_conflict(field: str, candidates: list[dict[str, str]]) -> dict[str, Any] | None:
    distinct = sorted({candidate["value"] for candidate in candidates})
    if len(distinct) <= 1:
        return None
    return {
        "code": "release_binding_source_mismatch",
        "detail": f"{field} has conflicting explicit sources",
        "field": field,
        "sources": candidates,
    }


def _commit_candidate_conflict(
    root: Path, candidates: list[dict[str, str]]
) -> dict[str, Any] | None:
    canonical_candidates = [
        {
            "source": candidate["source"],
            "value": _resolve_commit_sha(root, candidate["value"]) or candidate["value"],
        }
        for candidate in candidates
    ]
    return _candidate_conflict("commit_sha", canonical_candidates)


def _binding_from_payload(payload: Any) -> dict[str, str]:
    for path in _BINDING_PATHS:
        binding = _nested_value(payload, path)
        if isinstance(binding, dict):
            return _binding_fields(binding)
    if isinstance(payload, dict):
        return _binding_fields(payload)
    return {}


def _binding_fields(payload: Mapping[str, Any]) -> dict[str, str]:
    binding: dict[str, str] = {}
    for field, aliases in _BINDING_ALIASES.items():
        for alias in aliases:
            value = _non_empty(payload.get(alias))
            if value is not None:
                binding[field] = _canonical_environment(value) if field == "environment" else value
                break
    return binding


def _readyz_binding(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    return _binding_fields(
        {
            "deployment_id": payload.get("deployment"),
            "deployment_version": payload.get("app_version"),
            "environment": payload.get("environment"),
        }
    )


def _timestamp_from_payload(payload: Any) -> tuple[datetime | None, str | None, str | None]:
    for path in _TIMESTAMP_PATHS:
        value = _nested_value(payload, path)
        if value is None:
            continue
        source = ".".join(path)
        try:
            return _parse_timestamp(value), source, None
        except (TypeError, ValueError) as exc:
            return None, source, str(exc)
    return None, None, None


def _iter_inputs(
    prepared_inputs: Mapping[str, list[EvidenceInput] | EvidenceInput],
) -> list[tuple[str, EvidenceInput]]:
    inputs: list[tuple[str, EvidenceInput]] = []
    for key, value in prepared_inputs.items():
        if isinstance(value, list):
            inputs.extend(
                (f"{key}[{index}]", artifact)
                for index, artifact in enumerate(value)
                if isinstance(artifact, EvidenceInput)
            )
        elif isinstance(value, EvidenceInput):
            inputs.append((key, value))
    return inputs


def _artifact_validation(
    *,
    artifact_name: str,
    input_artifact: EvidenceInput,
    expected_binding: Mapping[str, str | None],
    generated_at: datetime,
    max_age_seconds: int,
    require_readyz_identity: bool,
    root: Path,
) -> dict[str, Any]:
    path = input_artifact.path
    errors: list[dict[str, Any]] = []
    payload: Any = None
    if path is None or not path.exists():
        return {
            "artifact": artifact_name,
            "errors": [],
            "exists": False,
            "required": input_artifact.required,
            "status": "missing",
        }
    try:
        payload = load_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(
            {
                "code": "evidence_input_invalid_json",
                "detail": str(exc),
                "field": artifact_name,
            }
        )

    timestamp, timestamp_source, timestamp_error = _timestamp_from_payload(payload)
    if timestamp_error is not None:
        errors.append(
            {
                "code": "evidence_input_timestamp_invalid",
                "detail": timestamp_error,
                "field": artifact_name,
                "source": timestamp_source,
            }
        )
    if timestamp is None and timestamp_error is None:
        errors.append(
            {
                "code": "evidence_input_timestamp_missing",
                "detail": f"{artifact_name} must declare an evidence timestamp",
                "field": artifact_name,
            }
        )

    age_seconds: float | None = None
    if timestamp is not None:
        age_seconds = (generated_at - timestamp).total_seconds()
        if age_seconds > max_age_seconds:
            errors.append(
                {
                    "age_seconds": round(age_seconds, 3),
                    "code": "evidence_input_stale",
                    "detail": f"{artifact_name} exceeds the maximum evidence age",
                    "field": artifact_name,
                    "max_age_seconds": max_age_seconds,
                }
            )
        if age_seconds < -FUTURE_TIMESTAMP_TOLERANCE_SECONDS:
            errors.append(
                {
                    "age_seconds": round(age_seconds, 3),
                    "code": "evidence_input_from_future",
                    "detail": f"{artifact_name} timestamp is too far in the future",
                    "field": artifact_name,
                }
            )

    declared_binding = _binding_from_payload(payload)
    if artifact_name == "readyz":
        readyz_binding = _readyz_binding(payload)
        declared_binding = {**declared_binding, **readyz_binding}
        if require_readyz_identity:
            for field in ("deployment_id", "deployment_version", "environment"):
                if field not in readyz_binding:
                    errors.append(
                        {
                            "code": "readyz_release_identity_missing",
                            "detail": f"readyz must declare {field}",
                            "field": field,
                        }
                    )
    for field in ("commit_sha", "deployment_id", "deployment_version", "environment"):
        if field not in declared_binding:
            errors.append(
                {
                    "code": "evidence_input_binding_missing",
                    "detail": f"{artifact_name} must declare {field}",
                    "field": field,
                }
            )
    for field, actual in declared_binding.items():
        expected = expected_binding.get(field)
        normalized_actual = _canonical_environment(actual) if field == "environment" else actual
        if field == "commit_sha":
            normalized_actual = _resolve_commit_sha(root, normalized_actual) or normalized_actual
        normalized_expected = (
            _canonical_environment(expected) if field == "environment" and expected else expected
        )
        if normalized_expected and normalized_actual != normalized_expected:
            errors.append(
                {
                    "actual": normalized_actual,
                    "code": "evidence_input_binding_mismatch",
                    "detail": f"{artifact_name} {field} does not match the release binding",
                    "expected": normalized_expected,
                    "field": field,
                }
            )

    return {
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "artifact": artifact_name,
        "declared_binding": declared_binding,
        "errors": errors,
        "exists": True,
        "path": str(path),
        "required": input_artifact.required,
        "status": "passed" if not errors else "failed",
        "timestamp": _format_utc(timestamp) if timestamp is not None else None,
        "timestamp_source": timestamp_source,
    }


def build_release_evidence_validation(
    *,
    ci: Mapping[str, Any],
    commit_sha: str | None,
    deployment_id: str | None,
    deployment_version: str | None,
    dry_run: bool,
    environment: str | None,
    generated_at: datetime,
    max_age_seconds: int,
    prepared_inputs: Mapping[str, list[EvidenceInput] | EvidenceInput],
    release_id: str,
    root: Path,
    env: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if max_age_seconds < 1:
        raise ValueError("--max-evidence-age-seconds must be at least 1")
    if dry_run:
        binding = {
            "commit_sha": "dry-run-commit",
            "deployment_id": "dry-run-deployment",
            "deployment_version": "dry-run-version",
            "environment": "dry-run",
            "release_id": release_id,
            "required": False,
            "sources": {"mode": "deterministic_sample"},
            "status": "sample",
        }
        return binding, {
            "artifact_records": [],
            "error_count": 0,
            "errors": [],
            "max_age_seconds": max_age_seconds,
            "passed": True,
            "status": "sample",
        }

    env = env or os.environ
    resolved_commit, commit_source, commit_candidates = _candidate(
        ("argument", commit_sha),
        ("RELEASE_COMMIT_SHA", env.get("RELEASE_COMMIT_SHA")),
        ("ci.commit_sha", ci.get("commit_sha")),
    )
    resolved_deployment_id, deployment_id_source, deployment_id_candidates = _candidate(
        ("argument", deployment_id),
        ("RELEASE_DEPLOYMENT_ID", env.get("RELEASE_DEPLOYMENT_ID")),
        ("DEPLOYMENT_ID", env.get("DEPLOYMENT_ID")),
        ("DEPLOYMENT_NAME", env.get("DEPLOYMENT_NAME")),
    )
    resolved_version, version_source, version_candidates = _candidate(
        ("argument", deployment_version),
        ("RELEASE_DEPLOYMENT_VERSION", env.get("RELEASE_DEPLOYMENT_VERSION")),
        ("DEPLOYMENT_VERSION", env.get("DEPLOYMENT_VERSION")),
        ("APP_VERSION", env.get("APP_VERSION")),
    )
    resolved_environment, environment_source, environment_candidates = _candidate(
        ("argument", environment),
        ("RELEASE_ENVIRONMENT", env.get("RELEASE_ENVIRONMENT")),
        ("ci.environment_name", ci.get("environment_name")),
        canonicalize=True,
    )
    sources = {
        "commit_sha": commit_source,
        "deployment_id": deployment_id_source,
        "deployment_version": version_source,
        "environment": environment_source,
    }
    errors: list[dict[str, Any]] = []
    for field, value in (
        ("commit_sha", resolved_commit),
        ("deployment_id", resolved_deployment_id),
        ("deployment_version", resolved_version),
        ("environment", resolved_environment),
    ):
        if value is None:
            errors.append(
                {
                    "code": "release_binding_missing",
                    "detail": f"production evidence requires explicit {field}",
                    "field": field,
                }
            )
    commit_conflict = _commit_candidate_conflict(root, commit_candidates)
    if commit_conflict is not None:
        errors.append(commit_conflict)
    for field, candidates in (
        ("deployment_id", deployment_id_candidates),
        ("deployment_version", version_candidates),
        ("environment", environment_candidates),
    ):
        conflict = _candidate_conflict(field, candidates)
        if conflict is not None:
            errors.append(conflict)

    current_commit = _current_commit_sha(root)
    commit_has_sha_shape = bool(resolved_commit and _COMMIT_SHA_PATTERN.fullmatch(resolved_commit))
    canonical_commit = (
        _resolve_commit_sha(root, resolved_commit)
        if resolved_commit and commit_has_sha_shape
        else None
    )
    if resolved_commit and (not commit_has_sha_shape or canonical_commit is None):
        errors.append(
            {
                "code": "release_commit_invalid",
                "detail": "commit_sha must be a hexadecimal SHA that resolves to a repository commit",
                "field": "commit_sha",
                "value": resolved_commit,
            }
        )
    elif canonical_commit and current_commit and canonical_commit != current_commit:
        errors.append(
            {
                "actual": canonical_commit,
                "code": "release_commit_not_current",
                "detail": "commit_sha does not match the checked-out HEAD",
                "expected": current_commit,
                "field": "commit_sha",
            }
        )
    if resolved_environment and resolved_environment != "production":
        errors.append(
            {
                "actual": resolved_environment,
                "code": "release_environment_invalid",
                "detail": "production evidence must bind environment=production",
                "expected": "production",
                "field": "environment",
            }
        )

    expected_binding = {
        "commit_sha": canonical_commit or resolved_commit,
        "deployment_id": resolved_deployment_id,
        "deployment_version": resolved_version,
        "environment": resolved_environment,
    }
    artifact_records = [
        _artifact_validation(
            artifact_name=artifact_name,
            input_artifact=input_artifact,
            expected_binding=expected_binding,
            generated_at=generated_at,
            max_age_seconds=max_age_seconds,
            require_readyz_identity=True,
            root=root,
        )
        for artifact_name, input_artifact in _iter_inputs(prepared_inputs)
    ]
    artifact_errors = [
        error
        for record in artifact_records
        for error in record.get("errors", [])
        if isinstance(error, dict)
    ]
    timestamps = [
        _parse_timestamp(record["timestamp"])
        for record in artifact_records
        if record.get("timestamp") and record.get("required")
    ]
    if timestamps:
        timestamp_span = (max(timestamps) - min(timestamps)).total_seconds()
        if timestamp_span > max_age_seconds:
            artifact_errors.append(
                {
                    "code": "evidence_input_window_inconsistent",
                    "detail": "required evidence timestamps exceed the allowed collection window",
                    "max_age_seconds": max_age_seconds,
                    "timestamp_span_seconds": round(timestamp_span, 3),
                }
            )
    else:
        timestamp_span = None
    all_errors = [*errors, *artifact_errors]
    binding = {
        **expected_binding,
        "current_commit_sha": current_commit,
        "release_id": release_id,
        "required": True,
        "sources": sources,
        "status": "passed" if not errors else "failed",
        "supplied_commit_sha": resolved_commit,
    }
    validation = {
        "artifact_records": artifact_records,
        "error_count": len(all_errors),
        "errors": all_errors,
        "max_age_seconds": max_age_seconds,
        "passed": not all_errors,
        "status": "passed" if not all_errors else "failed",
        "timestamp_span_seconds": round(timestamp_span, 3) if timestamp_span is not None else None,
    }
    return binding, validation


def extend_production_validation(
    production_validation: dict[str, Any],
    *,
    binding: Mapping[str, Any],
    evidence_validation: Mapping[str, Any],
) -> dict[str, Any]:
    updated = dict(production_validation)
    evidence_passed = bool(evidence_validation.get("passed"))
    binding_passed = not binding.get("required") or binding.get("status") == "passed"
    updated.update(
        {
            "evidence_inputs_passed": evidence_passed,
            "release_binding_passed": binding_passed,
            "release_binding_required": bool(binding.get("required")),
        }
    )
    updated["passed"] = bool(updated.get("passed")) and evidence_passed and binding_passed
    return updated


def extend_failure_summary(
    failure_summary: dict[str, Any],
    *,
    binding: Mapping[str, Any],
    evidence_validation: Mapping[str, Any],
) -> dict[str, Any]:
    updated = dict(failure_summary)
    reasons = list(updated.get("reasons") or [])
    errors = [error for error in evidence_validation.get("errors", []) if isinstance(error, dict)]
    binding_errors = [
        error for error in errors if str(error.get("code") or "") in _RELEASE_BINDING_ERROR_CODES
    ]
    evidence_errors = [error for error in errors if error not in binding_errors]
    if binding.get("required") and binding.get("status") != "passed":
        reasons.append({"detail": binding_errors, "kind": "release_binding_invalid"})
    if evidence_errors:
        reasons.append({"detail": evidence_errors, "kind": "evidence_inputs_invalid"})
    updated["failed"] = bool(reasons)
    updated["reason_count"] = len(reasons)
    updated["reasons"] = reasons
    return updated


def extend_summary_payload(
    summary_payload: dict[str, Any],
    *,
    binding: Mapping[str, Any],
    evidence_validation: Mapping[str, Any],
) -> dict[str, Any]:
    updated = dict(summary_payload)
    updated["evidence_validation"] = {
        "error_count": int(evidence_validation.get("error_count") or 0),
        "max_age_seconds": evidence_validation.get("max_age_seconds"),
        "passed": bool(evidence_validation.get("passed")),
        "status": evidence_validation.get("status"),
        "timestamp_span_seconds": evidence_validation.get("timestamp_span_seconds"),
    }
    updated["release_binding"] = dict(binding)
    return updated
