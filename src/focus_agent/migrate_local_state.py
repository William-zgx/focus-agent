from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Protocol, Sequence

from psycopg import Connection
from psycopg.rows import dict_row

from .engine.local_persistence import (
    PersistentInMemorySaver,
    PersistentInMemoryStore,
    _focus_agent_checkpoint_serde,
)
from .repositories.artifact_metadata_repository import ArtifactMetadataRepository
from .repositories.postgres_trajectory_repository import PostgresTrajectoryRepository


@dataclass(frozen=True, slots=True)
class SourceLayout:
    requested_dir: Path
    resolved_dir: Path
    branch_db_path: Path
    store_path: Path
    checkpoint_path: Path
    artifact_dir: Path


@dataclass(frozen=True, slots=True)
class LocalStoreItemRecord:
    namespace: tuple[str, ...]
    key: str
    value: dict[str, Any]
    created_at: str | None
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class LocalCheckpointRecord:
    thread_id: str
    checkpoint_ns: str
    checkpoint_id: str
    checkpoint: dict[str, Any]
    metadata: dict[str, Any]
    parent_checkpoint_id: str | None
    pending_write_count: int


@dataclass(frozen=True, slots=True)
class AppStateSnapshot:
    thread_access_rows: list[dict[str, Any]]
    conversation_rows: list[dict[str, Any]]
    branch_rows: list[dict[str, Any]]
    missing_tables: list[str]


@dataclass(frozen=True, slots=True)
class AppStateSinkDiscovery:
    sink: "AppStateSink | None"
    description: str | None
    attempts: list[str]


class AppStateSink(Protocol):
    def setup(self) -> None:
        ...

    def upsert_thread_access_rows(self, rows: Sequence[dict[str, Any]]) -> int | None:
        ...

    def upsert_conversation_rows(self, rows: Sequence[dict[str, Any]]) -> int | None:
        ...

    def upsert_branch_rows(self, rows: Sequence[dict[str, Any]]) -> int | None:
        ...


@contextmanager
def open_postgres_saver(database_uri: str):
    from langgraph.checkpoint.postgres import PostgresSaver

    with Connection.connect(
        database_uri,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    ) as conn:
        yield PostgresSaver(conn, serde=_focus_agent_checkpoint_serde())


@contextmanager
def open_postgres_store(database_uri: str):
    from langgraph.store.postgres import PostgresStore

    with Connection.connect(
        database_uri,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    ) as conn:
        yield PostgresStore(conn)


def setup_trajectory_schema(database_uri: str) -> None:
    PostgresTrajectoryRepository(database_uri).setup()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="focus-agent-migrate-local-state",
        description="Import local focus-agent state into a Postgres-backed deployment.",
    )
    parser.add_argument(
        "--source-dir",
        required=True,
        help="Directory containing branches.sqlite3, langgraph-store.pkl, langgraph-checkpoints.pkl, and artifacts/.",
    )
    parser.add_argument(
        "--database-uri",
        required=True,
        help="Target Postgres connection string.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect local state and generate a report without writing to Postgres.",
    )
    parser.add_argument(
        "--checkpoint-mode",
        default="latest-stable",
        choices=("latest-stable",),
        help="Checkpoint selection policy.",
    )
    parser.add_argument(
        "--artifact-scan",
        action="store_true",
        help="Scan the local artifacts directory and include the results in the report.",
    )
    parser.add_argument(
        "--report-path",
        required=True,
        help="Where to write the JSON migration report.",
    )
    return parser.parse_args(argv)


def resolve_source_layout(source_dir: str | Path) -> SourceLayout:
    requested_dir = Path(source_dir).expanduser().resolve()
    resolved_dir = requested_dir
    if not (resolved_dir / "branches.sqlite3").exists() and (resolved_dir / ".focus_agent").is_dir():
        resolved_dir = (resolved_dir / ".focus_agent").resolve()

    return SourceLayout(
        requested_dir=requested_dir,
        resolved_dir=resolved_dir,
        branch_db_path=resolved_dir / "branches.sqlite3",
        store_path=resolved_dir / "langgraph-store.pkl",
        checkpoint_path=resolved_dir / "langgraph-checkpoints.pkl",
        artifact_dir=resolved_dir / "artifacts",
    )


def _sqlite_connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _sqlite_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _load_thread_access_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT thread_id, root_thread_id, owner_user_id, created_at
        FROM thread_access
        ORDER BY created_at, thread_id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _load_conversation_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT root_thread_id, owner_user_id, title, title_pending_ai, is_archived,
               archived_at, created_at, updated_at
        FROM conversations
        ORDER BY created_at, root_thread_id
        """
    ).fetchall()
    normalized: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        payload["title_pending_ai"] = bool(payload["title_pending_ai"])
        payload["is_archived"] = bool(payload["is_archived"])
        normalized.append(payload)
    return normalized


def _load_branch_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT branch_id, root_thread_id, parent_thread_id, child_thread_id, return_thread_id,
               owner_user_id, branch_name, branch_role, branch_depth, branch_status,
               is_archived, archived_at, fork_checkpoint_id, fork_strategy,
               merge_proposal_json, merge_decision_json
        FROM branches
        ORDER BY root_thread_id, branch_depth, child_thread_id
        """
    ).fetchall()
    normalized: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row)
        payload["is_archived"] = bool(payload["is_archived"])
        payload["merge_proposal"] = (
            json.loads(payload.pop("merge_proposal_json"))
            if payload.get("merge_proposal_json")
            else None
        )
        payload["merge_decision"] = (
            json.loads(payload.pop("merge_decision_json"))
            if payload.get("merge_decision_json")
            else None
        )
        normalized.append(payload)
    return normalized


def load_sqlite_app_state(db_path: Path) -> AppStateSnapshot:
    if not db_path.exists():
        return AppStateSnapshot(
            thread_access_rows=[],
            conversation_rows=[],
            branch_rows=[],
            missing_tables=["branches", "conversations", "thread_access"],
        )

    with _sqlite_connect(db_path) as conn:
        missing_tables: list[str] = []

        if _sqlite_table_exists(conn, "thread_access"):
            thread_access_rows = _load_thread_access_rows(conn)
        else:
            thread_access_rows = []
            missing_tables.append("thread_access")

        if _sqlite_table_exists(conn, "conversations"):
            conversation_rows = _load_conversation_rows(conn)
        else:
            conversation_rows = []
            missing_tables.append("conversations")

        if _sqlite_table_exists(conn, "branches"):
            branch_rows = _load_branch_rows(conn)
        else:
            branch_rows = []
            missing_tables.append("branches")

    return AppStateSnapshot(
        thread_access_rows=thread_access_rows,
        conversation_rows=conversation_rows,
        branch_rows=branch_rows,
        missing_tables=missing_tables,
    )


def load_local_store_items(store_path: Path) -> list[LocalStoreItemRecord]:
    if not store_path.exists():
        return []

    store = PersistentInMemoryStore(store_path)
    records: list[LocalStoreItemRecord] = []
    for namespace, items in store._data.items():
        for key, item in items.items():
            value = item.value if hasattr(item, "value") else item
            created_at = getattr(item, "created_at", None)
            updated_at = getattr(item, "updated_at", None)
            records.append(
                LocalStoreItemRecord(
                    namespace=tuple(namespace),
                    key=str(key),
                    value=dict(value),
                    created_at=created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
                    updated_at=updated_at.isoformat() if hasattr(updated_at, "isoformat") else updated_at,
                )
            )
    records.sort(key=lambda item: (".".join(item.namespace), item.key))
    return records


def load_local_checkpoints(checkpoint_path: Path) -> list[LocalCheckpointRecord]:
    if not checkpoint_path.exists():
        return []

    saver = PersistentInMemorySaver(checkpoint_path)
    records: list[LocalCheckpointRecord] = []
    for checkpoint_tuple in saver.list(None):
        configurable = checkpoint_tuple.config["configurable"]
        parent_config = checkpoint_tuple.parent_config["configurable"] if checkpoint_tuple.parent_config else {}
        records.append(
            LocalCheckpointRecord(
                thread_id=str(configurable["thread_id"]),
                checkpoint_ns=str(configurable.get("checkpoint_ns", "")),
                checkpoint_id=str(configurable["checkpoint_id"]),
                checkpoint=dict(checkpoint_tuple.checkpoint),
                metadata=dict(checkpoint_tuple.metadata),
                parent_checkpoint_id=(
                    str(parent_config["checkpoint_id"])
                    if parent_config.get("checkpoint_id") is not None
                    else None
                ),
                pending_write_count=len(checkpoint_tuple.pending_writes),
            )
        )
    return records


def select_latest_stable_checkpoints(
    checkpoints: Sequence[LocalCheckpointRecord],
) -> tuple[list[LocalCheckpointRecord], list[LocalCheckpointRecord]]:
    selected: list[LocalCheckpointRecord] = []
    skipped: list[LocalCheckpointRecord] = []
    seen_namespaces: set[tuple[str, str]] = set()

    for record in checkpoints:
        namespace_key = (record.thread_id, record.checkpoint_ns)
        if namespace_key in seen_namespaces:
            skipped.append(record)
            continue
        if record.pending_write_count > 0:
            skipped.append(record)
            continue
        selected.append(record)
        seen_namespaces.add(namespace_key)

    return selected, skipped


def scan_artifacts(artifact_dir: Path) -> list[dict[str, Any]]:
    if not artifact_dir.exists():
        return []

    results: list[dict[str, Any]] = []
    for path in sorted(artifact_dir.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        results.append(
            {
                "path": str(path.relative_to(artifact_dir)),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return results


def _migrate_artifacts(
    database_uri: str,
    artifact_dir: Path,
    artifacts: Sequence[dict[str, Any]],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return {
            "artifact_count": len(artifacts),
            "artifacts": list(artifacts),
        }

    repo = ArtifactMetadataRepository(database_uri)
    repo.setup()
    migrated_count = 0
    for artifact in artifacts:
        relative_path = str(artifact["path"])
        repo.upsert_from_file(
            thread_id=None,
            artifact_id=relative_path,
            path=artifact_dir / relative_path,
            title=Path(relative_path).stem.replace("-", " ").strip().title() or Path(relative_path).name,
        )
        migrated_count += 1
    return {
        "artifact_count": len(artifacts),
        "migrated_artifact_count": migrated_count,
        "artifacts": list(artifacts),
    }


def _supports_app_state_sink(candidate: object) -> bool:
    required_methods = (
        "setup",
        "upsert_thread_access_rows",
        "upsert_conversation_rows",
        "upsert_branch_rows",
    )
    return all(callable(getattr(candidate, method_name, None)) for method_name in required_methods)


def discover_app_state_sink(database_uri: str) -> AppStateSinkDiscovery:
    candidates: tuple[tuple[str, str | None, str | None], ...] = (
        (
            "focus_agent.repositories.postgres_branch_repository",
            "create_local_state_migration_sink",
            None,
        ),
        (
            "focus_agent.repositories.postgres_state_repository",
            "create_local_state_migration_sink",
            None,
        ),
        (
            "focus_agent.repositories.postgres_branch_repository",
            None,
            "PostgresAppStateSink",
        ),
        (
            "focus_agent.repositories.postgres_state_repository",
            None,
            "PostgresAppStateSink",
        ),
    )

    attempts: list[str] = []
    for module_name, factory_name, class_name in candidates:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            attempts.append(f"{module_name}: module not available")
            continue

        sink_candidate: object | None = None
        if factory_name and hasattr(module, factory_name):
            sink_candidate = getattr(module, factory_name)(database_uri)
            attempts.append(f"{module_name}.{factory_name}: discovered")
        elif class_name and hasattr(module, class_name):
            sink_candidate = getattr(module, class_name)(database_uri)
            attempts.append(f"{module_name}.{class_name}: discovered")
        else:
            attempts.append(f"{module_name}: no compatible sink factory or class")
            continue

        if _supports_app_state_sink(sink_candidate):
            description = getattr(sink_candidate, "description", None)
            if description is None and hasattr(sink_candidate, "describe") and callable(sink_candidate.describe):
                description = str(sink_candidate.describe())
            return AppStateSinkDiscovery(
                sink=sink_candidate,
                description=description,
                attempts=attempts,
            )

        attempts.append(f"{module_name}: discovered object did not match AppStateSink protocol")

    return AppStateSinkDiscovery(sink=None, description=None, attempts=attempts)


def _migrate_app_state(
    sink: AppStateSink | None,
    snapshot: AppStateSnapshot,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    counts = {
        "thread_access_rows": len(snapshot.thread_access_rows),
        "conversation_rows": len(snapshot.conversation_rows),
        "branch_rows": len(snapshot.branch_rows),
        "missing_tables": list(snapshot.missing_tables),
    }

    if sink is None:
        return {
            "status": "skipped",
            "reason": "No app-state sink was discovered. Worker 1 can attach a Postgres app-state sink via the AppStateSink seam in focus_agent.migrate_local_state.",
            **counts,
        }

    if dry_run:
        return {
            "status": "dry-run",
            **counts,
        }

    thread_access_migrated = sink.upsert_thread_access_rows(snapshot.thread_access_rows)
    conversation_migrated = sink.upsert_conversation_rows(snapshot.conversation_rows)
    branch_migrated = sink.upsert_branch_rows(snapshot.branch_rows)
    return {
        "status": "completed",
        "thread_access_rows": len(snapshot.thread_access_rows),
        "conversation_rows": len(snapshot.conversation_rows),
        "branch_rows": len(snapshot.branch_rows),
        "thread_access_migrated": len(snapshot.thread_access_rows) if thread_access_migrated is None else thread_access_migrated,
        "conversation_migrated": len(snapshot.conversation_rows) if conversation_migrated is None else conversation_migrated,
        "branch_migrated": len(snapshot.branch_rows) if branch_migrated is None else branch_migrated,
        "missing_tables": list(snapshot.missing_tables),
    }


def _migrate_store_items(
    database_uri: str,
    items: Sequence[LocalStoreItemRecord],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return {
            "status": "dry-run",
            "source_item_count": len(items),
            "migrated_item_count": 0,
        }

    with open_postgres_store(database_uri) as store:
        for item in items:
            store.put(item.namespace, item.key, item.value)
    return {
        "status": "completed",
        "source_item_count": len(items),
        "migrated_item_count": len(items),
    }


def _migrate_checkpoints(
    database_uri: str,
    checkpoints: Sequence[LocalCheckpointRecord],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    selected, skipped = select_latest_stable_checkpoints(checkpoints)
    skipped_due_to_pending = sum(1 for item in skipped if item.pending_write_count > 0)

    if dry_run:
        return {
            "status": "dry-run",
            "source_checkpoint_count": len(checkpoints),
            "selected_checkpoint_count": len(selected),
            "skipped_checkpoint_count": len(skipped),
            "skipped_due_to_pending_writes": skipped_due_to_pending,
        }

    with open_postgres_saver(database_uri) as saver:
        for record in selected:
            config = {
                "configurable": {
                    "thread_id": record.thread_id,
                    "checkpoint_ns": record.checkpoint_ns,
                }
            }
            if record.parent_checkpoint_id:
                config["configurable"]["checkpoint_id"] = record.parent_checkpoint_id
            saver.put(
                config,
                record.checkpoint,
                record.metadata,
                record.checkpoint.get("channel_versions", {}),
            )
    return {
        "status": "completed",
        "source_checkpoint_count": len(checkpoints),
        "selected_checkpoint_count": len(selected),
        "migrated_checkpoint_count": len(selected),
        "skipped_checkpoint_count": len(skipped),
        "skipped_due_to_pending_writes": skipped_due_to_pending,
    }


def run_migration(
    args: argparse.Namespace,
    *,
    sink_discovery: AppStateSinkDiscovery | None = None,
) -> dict[str, Any]:
    layout = resolve_source_layout(args.source_dir)
    sqlite_snapshot = load_sqlite_app_state(layout.branch_db_path)
    store_items = load_local_store_items(layout.store_path)
    checkpoint_records = load_local_checkpoints(layout.checkpoint_path)
    sink_info = sink_discovery or discover_app_state_sink(args.database_uri)

    setup_step: dict[str, Any]
    if args.dry_run:
        setup_step = {
            "name": "setup",
            "status": "dry-run",
            "details": {
                "app_state_sink_available": sink_info.sink is not None,
                "app_state_sink_description": sink_info.description,
                "trajectory_backfill": "disabled",
            },
        }
    else:
        if sink_info.sink is not None:
            sink_info.sink.setup()
        with open_postgres_store(args.database_uri) as store:
            store.setup()
        with open_postgres_saver(args.database_uri) as saver:
            saver.setup()
        setup_trajectory_schema(args.database_uri)
        setup_step = {
            "name": "setup",
            "status": "completed",
            "details": {
                "app_state_sink_available": sink_info.sink is not None,
                "app_state_sink_description": sink_info.description,
                "trajectory_backfill": "disabled",
            },
        }

    sqlite_step = {
        "name": "sqlite-app-state",
        "status": "pending",
        "details": _migrate_app_state(
            sink_info.sink,
            sqlite_snapshot,
            dry_run=args.dry_run,
        ),
    }
    sqlite_step["status"] = sqlite_step["details"]["status"]

    store_step = {
        "name": "langgraph-store",
        "status": "pending",
        "details": _migrate_store_items(
            args.database_uri,
            store_items,
            dry_run=args.dry_run,
        ),
    }
    store_step["status"] = store_step["details"]["status"]

    checkpoint_step = {
        "name": "langgraph-checkpoints",
        "status": "pending",
        "details": _migrate_checkpoints(
            args.database_uri,
            checkpoint_records,
            dry_run=args.dry_run,
        ),
    }
    checkpoint_step["status"] = checkpoint_step["details"]["status"]

    if args.artifact_scan:
        artifacts = scan_artifacts(layout.artifact_dir)
        artifact_step = {
            "name": "artifact-scan",
            "status": "completed" if not args.dry_run else "dry-run",
            "details": _migrate_artifacts(
                args.database_uri,
                layout.artifact_dir,
                artifacts,
                dry_run=args.dry_run,
            ),
        }
    else:
        artifact_step = {
            "name": "artifact-scan",
            "status": "skipped",
            "details": {
                "artifact_count": 0,
                "reason": "--artifact-scan was not provided",
            },
        }

    integration_notes: list[str] = []
    if sink_info.sink is None:
        integration_notes.append(
            "App-state migration uses the AppStateSink protocol in focus_agent.migrate_local_state. "
            "Worker 1 can attach a Postgres implementation by exposing setup/upsert_thread_access_rows/"
            "upsert_conversation_rows/upsert_branch_rows from a discovered repository module."
        )
    integration_notes.append(
        "Trajectory schema setup is allowed, but this CLI intentionally does not synthesize historical trajectory rows."
    )
    integration_notes.append(
        "Checkpoint mode latest-stable selects the newest checkpoint per (thread_id, checkpoint_ns) with no pending writes."
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "requested_dir": str(layout.requested_dir),
            "resolved_dir": str(layout.resolved_dir),
            "branch_db_path": str(layout.branch_db_path),
            "store_path": str(layout.store_path),
            "checkpoint_path": str(layout.checkpoint_path),
            "artifact_dir": str(layout.artifact_dir),
        },
        "target": {
            "database_uri": args.database_uri,
            "dry_run": bool(args.dry_run),
            "checkpoint_mode": args.checkpoint_mode,
        },
        "steps": [
            setup_step,
            sqlite_step,
            store_step,
            checkpoint_step,
            artifact_step,
        ],
        "summary": {
            "sqlite_thread_access_rows": len(sqlite_snapshot.thread_access_rows),
            "sqlite_conversation_rows": len(sqlite_snapshot.conversation_rows),
            "sqlite_branch_rows": len(sqlite_snapshot.branch_rows),
            "store_item_count": len(store_items),
            "checkpoint_count": len(checkpoint_records),
            "artifact_scan_enabled": bool(args.artifact_scan),
        },
        "sink_discovery_attempts": sink_info.attempts,
        "integration_notes": integration_notes,
    }


def write_report(report_path: str | Path, report: dict[str, Any]) -> None:
    path = Path(report_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = run_migration(args)
    except Exception as exc:  # noqa: BLE001
        failure_report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed",
            "error": str(exc),
        }
        write_report(args.report_path, failure_report)
        print(f"focus-agent-migrate-local-state failed: {exc}", file=sys.stderr)
        return 1

    write_report(args.report_path, report)
    print(
        "focus-agent-migrate-local-state completed "
        f"({'dry-run' if args.dry_run else 'applied'}) -> {args.report_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
