"""Report section helpers for postgres_ops."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_POSTGRES_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "src/focus_agent/repositories/postgres_schema.py"
)


_FALLBACK_SCHEMA_VERSION = 11


_FALLBACK_SCHEMA_MIGRATION_LOCK_ID = 7612044473148256129


def _postgres_schema_source() -> str:
    try:
        return _POSTGRES_SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def _expected_schema_version() -> int:
    match = re.search(r"^SCHEMA_VERSION\s*=\s*(\d+)", _postgres_schema_source(), flags=re.MULTILINE)
    if match:
        return int(match.group(1))
    return _FALLBACK_SCHEMA_VERSION


def _expected_migration_versions() -> list[int]:
    source = _postgres_schema_source()
    versions = [
        int(match.group(1))
        for match in re.finditer(
            r"^\s*\((\d+),\s*_run_migration_v\d+\)", source, flags=re.MULTILINE
        )
    ]
    if versions:
        return versions
    return list(range(1, _expected_schema_version() + 1))


def _schema_migration_lock_id() -> int:
    match = re.search(
        r"^_SCHEMA_MIGRATION_LOCK_ID\s*=\s*(\d+)", _postgres_schema_source(), flags=re.MULTILINE
    )
    if match:
        return int(match.group(1))
    return _FALLBACK_SCHEMA_MIGRATION_LOCK_ID

def _operation_by_name(operations: Sequence[Mapping[str, Any]], name: str) -> Mapping[str, Any]:
    for operation in operations:
        if operation.get("name") == name:
            return operation
    return {}

def _report_sections(operations: Sequence[Mapping[str, Any]], *, dry_run: bool) -> dict[str, Any]:
    schema_version = _operation_by_name(operations, "schema_version")
    migration_state = _operation_by_name(operations, "migration_state")
    advisory_lock = _operation_by_name(operations, "advisory_lock")
    pgvector = _operation_by_name(operations, "pgvector_readiness")
    return {
        "schema": {
            "advisory_lock": {
                "lock_id": advisory_lock.get("lock_id", _schema_migration_lock_id()),
                "passed": bool(advisory_lock.get("passed", dry_run)),
                "status": advisory_lock.get("status", "dry-run" if dry_run else "missing"),
            },
            "applied_migrations": migration_state.get("applied_versions", []),
            "current_schema_version": schema_version.get("max_applied_version"),
            "expected_migrations": migration_state.get(
                "expected_versions", _expected_migration_versions()
            ),
            "expected_schema_version": schema_version.get(
                "expected_schema_version",
                _expected_schema_version(),
            ),
            "future_migrations": migration_state.get("future_versions", []),
            "missing_migrations": migration_state.get("missing_versions", []),
            "passed": bool(
                schema_version.get("passed", dry_run) and migration_state.get("passed", dry_run)
            ),
            "status": "dry-run"
            if dry_run
            else ("passed" if schema_version.get("passed") else "failed"),
        },
        "pgvector": {
            "available": pgvector.get("available"),
            "embeddings_table_exists": pgvector.get("embeddings_table_exists"),
            "extension_version": pgvector.get("extension_version"),
            "installed": pgvector.get("installed"),
            "passed": bool(pgvector.get("passed", dry_run)),
            "status": pgvector.get("status", "dry-run" if dry_run else "missing"),
        },
        "pool": {
            "configured": bool(
                os.environ.get("POSTGRES_POOL_MIN_SIZE") or os.environ.get("POSTGRES_POOL_MAX_SIZE")
            ),
            "max_size": os.environ.get("POSTGRES_POOL_MAX_SIZE"),
            "min_size": os.environ.get("POSTGRES_POOL_MIN_SIZE"),
            "snapshot_error": None,
            "status": "dry-run" if dry_run else "not-collected",
        },
        "slow_query": {
            "configured": bool(os.environ.get("POSTGRES_SLOW_QUERY_MS")),
            "threshold_ms": os.environ.get("POSTGRES_SLOW_QUERY_MS"),
            "warning_count": 0,
            "status": "dry-run" if dry_run else "not-collected",
        },
    }
