"""Attach release identity metadata to locally generated evidence reports."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

RELEASE_IDENTITY_ENV = {
    "commit_sha": "RELEASE_COMMIT_SHA",
    "deployment_id": "RELEASE_DEPLOYMENT_ID",
    "deployment_version": "RELEASE_DEPLOYMENT_VERSION",
    "environment": "RELEASE_ENVIRONMENT",
}


def _non_empty(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _timezone_aware_timestamp(value: Any) -> str:
    text = _non_empty(value)
    if text is None:
        raise ValueError("generated_at must be a non-empty ISO-8601 timestamp")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("generated_at must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("generated_at must include a timezone")
    return text


def _existing_generated_at(report: Mapping[str, Any]) -> Any:
    if report.get("generated_at") is not None:
        return report["generated_at"]
    meta = report.get("meta")
    if isinstance(meta, Mapping):
        return meta.get("generated_at")
    return None


def attest_release_report(
    report: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return a report carrying a complete environment-derived release identity."""

    resolved_env = os.environ if env is None else env
    resolved_values = {
        field: _non_empty(resolved_env.get(env_name))
        for field, env_name in RELEASE_IDENTITY_ENV.items()
    }
    configured = {field for field, value in resolved_values.items() if value is not None}
    missing = [
        env_name
        for field, env_name in RELEASE_IDENTITY_ENV.items()
        if resolved_values[field] is None
    ]
    dry_run = bool(report.get("dry_run"))

    if not dry_run and missing and configured:
        raise ValueError(
            "release identity is incomplete; missing environment variables: " + ", ".join(missing)
        )

    attested = dict(report)
    attested.pop("release_binding", None)
    meta = attested.get("meta")
    if isinstance(meta, Mapping) and "release_binding" in meta:
        cleaned_meta = dict(meta)
        cleaned_meta.pop("release_binding", None)
        attested["meta"] = cleaned_meta
    existing_timestamp = _existing_generated_at(attested)
    attested["generated_at"] = (
        _timezone_aware_timestamp(existing_timestamp) if existing_timestamp is not None else _now()
    )

    if not missing:
        environment = str(resolved_values["environment"])
        attested["release_binding"] = {
            "commit_sha": resolved_values["commit_sha"],
            "deployment_id": resolved_values["deployment_id"],
            "deployment_version": resolved_values["deployment_version"],
            "environment": "production" if environment.lower() == "prod" else environment,
        }
    return attested
