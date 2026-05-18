from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...core.repo_call import has_repo_method
from ...memory.models import MemoryStatus
from ...repositories.memory_repository import MemoryListQuery
from .loader import (
    AppStateSink,
    AppStateSinkDiscovery,
    AppStateSnapshot,
    LocalCheckpointRecord,
    LocalStoreItemRecord,
    _redact_database_uri,
    create_memory_embedding_service,
    create_memory_repository,
    load_local_checkpoints,
    load_local_store_items,
    load_sqlite_app_state,
    open_postgres_saver,
    open_postgres_store,
    parse_args,
    resolve_source_layout,
    scan_artifacts,
    select_latest_stable_checkpoints,
    setup_trajectory_schema,
)
from .transformer import _summarize_skip_reasons, build_focus_memory_records


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

    from ...repositories.artifact_metadata_repository import ArtifactMetadataRepository

    repo = ArtifactMetadataRepository(database_uri)
    repo.setup()
    migrated_count = 0
    for artifact in artifacts:
        relative_path = str(artifact["path"])
        repo.upsert_from_file(
            thread_id=None,
            artifact_id=relative_path,
            path=artifact_dir / relative_path,
            title=Path(relative_path).stem.replace("-", " ").strip().title()
            or Path(relative_path).name,
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
    return all(has_repo_method(candidate, method_name) for method_name in required_methods)


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
            module = __import__(module_name, fromlist=[None])
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
            if description is None and has_repo_method(sink_candidate, "describe"):
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
            "reason": "No app-state sink was discovered. A Postgres app-state sink can be attached via the AppStateSink protocol in focus_agent.migrate_local_state.",
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
        "thread_access_migrated": len(snapshot.thread_access_rows)
        if thread_access_migrated is None
        else thread_access_migrated,
        "conversation_migrated": len(snapshot.conversation_rows)
        if conversation_migrated is None
        else conversation_migrated,
        "branch_migrated": len(snapshot.branch_rows)
        if branch_migrated is None
        else branch_migrated,
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


def _migrate_focus_memories(
    database_uri: str,
    items: Sequence[LocalStoreItemRecord],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    records, skipped = build_focus_memory_records(items)
    details = {
        "source_item_count": len(items),
        "eligible_memory_count": len(records),
        "skipped_item_count": len(skipped),
        "skipped_reasons": _summarize_skip_reasons(skipped),
    }

    if dry_run:
        return {
            "status": "dry-run",
            "migrated_memory_count": 0,
            **details,
        }

    repository = create_memory_repository(database_uri)
    migrated_count = 0
    for record in records:
        repository.upsert_record(record)
        migrated_count += 1
    return {
        "status": "completed",
        "migrated_memory_count": migrated_count,
        **details,
    }


def _backfill_memory_embeddings(
    database_uri: str,
    *,
    enabled: bool,
    dry_run: bool,
    batch_size: int = 500,
) -> dict[str, Any]:
    if not enabled:
        return {
            "status": "skipped",
            "reason": "--backfill-memory-embeddings was not provided",
            "scanned_memory_count": 0,
            "written_embedding_count": 0,
            "skipped_embedding_count": 0,
            "failed_embedding_count": 0,
        }

    if dry_run:
        return {
            "status": "dry-run",
            "scanned_memory_count": 0,
            "written_embedding_count": 0,
            "skipped_embedding_count": 0,
            "failed_embedding_count": 0,
        }

    repository = create_memory_repository(database_uri)
    if not has_repo_method(repository, "list_records"):
        return {
            "status": "skipped",
            "reason": "memory_repository_does_not_support_list_records",
            "scanned_memory_count": 0,
            "written_embedding_count": 0,
            "skipped_embedding_count": 0,
            "failed_embedding_count": 0,
        }

    try:
        embedding_service = create_memory_embedding_service(database_uri)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "skipped",
            "reason": f"memory_embedding_service_unavailable: {exc}",
            "scanned_memory_count": 0,
            "written_embedding_count": 0,
            "skipped_embedding_count": 0,
            "failed_embedding_count": 0,
        }
    if embedding_service is None:
        return {
            "status": "skipped",
            "reason": "memory_embedding_service_unavailable",
            "scanned_memory_count": 0,
            "written_embedding_count": 0,
            "skipped_embedding_count": 0,
            "failed_embedding_count": 0,
        }

    _setup_memory_embedding_service(embedding_service)
    scanned_count = 0
    written_count = 0
    skipped_count = 0
    failed_count = 0
    failures: list[dict[str, str]] = []
    offset = 0

    while True:
        records = repository.list_records(
            MemoryListQuery(
                status=MemoryStatus.ACTIVE.value,
                limit=batch_size,
                offset=offset,
            )
        )
        if not records:
            break

        for record in records:
            scanned_count += 1
            try:
                result = embedding_service.ensure_embedding(record)
            except Exception as exc:  # noqa: BLE001
                failed_count += 1
                if len(failures) < 10:
                    failures.append({"memory_id": record.memory_id, "reason": str(exc)})
                continue

            status = _memory_embedding_result_status(result)
            if status in {"written", "updated", "created", "upserted"}:
                written_count += 1
            elif status == "skipped":
                skipped_count += 1
            else:
                skipped_count += 1

        if len(records) < batch_size:
            break
        offset += batch_size

    return {
        "status": "completed" if failed_count == 0 else "completed_with_errors",
        "scanned_memory_count": scanned_count,
        "written_embedding_count": written_count,
        "skipped_embedding_count": skipped_count,
        "failed_embedding_count": failed_count,
        "failures": failures,
    }


def _setup_memory_embedding_service(embedding_service: object) -> None:
    repository = getattr(embedding_service, "embedding_repository", embedding_service)
    if has_repo_method(repository, "setup"):
        provider = getattr(embedding_service, "provider", None)
        dimensions = int(getattr(provider, "dimensions", 1536) or 1536)
        try:
            repository.setup(memory_embeddings_enabled=True, dimensions=dimensions)
        except TypeError:
            repository.setup()


def _memory_embedding_result_status(result: object) -> str:
    if isinstance(result, dict):
        return str(result.get("status") or "")
    return str(getattr(result, "status", "") or "")


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
                "focus_memories_backfill": "dry-run",
                "memory_embeddings_backfill": (
                    "dry-run" if args.backfill_memory_embeddings else "disabled"
                ),
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
        create_memory_repository(args.database_uri).setup()
        setup_trajectory_schema(args.database_uri)
        setup_step = {
            "name": "setup",
            "status": "completed",
            "details": {
                "app_state_sink_available": sink_info.sink is not None,
                "app_state_sink_description": sink_info.description,
                "focus_memories_backfill": "enabled",
                "memory_embeddings_backfill": (
                    "enabled" if args.backfill_memory_embeddings else "disabled"
                ),
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

    focus_memories_step = {
        "name": "focus-memories",
        "status": "pending",
        "details": _migrate_focus_memories(
            args.database_uri,
            store_items,
            dry_run=args.dry_run,
        ),
    }
    focus_memories_step["status"] = focus_memories_step["details"]["status"]

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

    memory_embedding_step = {
        "name": "memory-embeddings",
        "status": "pending",
        "details": _backfill_memory_embeddings(
            args.database_uri,
            enabled=bool(args.backfill_memory_embeddings),
            dry_run=args.dry_run,
        ),
    }
    memory_embedding_step["status"] = memory_embedding_step["details"]["status"]

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
            "A Postgres implementation can be attached by exposing setup/upsert_thread_access_rows/"
            "upsert_conversation_rows/upsert_branch_rows from a discovered repository module."
        )
    integration_notes.append(
        "Trajectory schema setup is allowed, but this CLI intentionally does not synthesize historical trajectory rows."
    )
    integration_notes.append(
        "Checkpoint mode latest-stable selects the newest checkpoint per (thread_id, checkpoint_ns) with no pending writes."
    )
    if args.backfill_memory_embeddings:
        integration_notes.append(
            "Memory embedding backfill scans active canonical memories and skips rows with matching content_hash."
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": {
            "requested_dir": str(layout.requested_dir),
            "resolved_dir": str(layout.resolved_dir),
            "branch_db_path": str(layout.branch_db_path),
            "store_path": str(layout.store_path),
            "checkpoint_path": str(layout.checkpoint_path),
            "artifact_dir": str(layout.artifact_dir),
        },
        "target": {
            "database_uri": _redact_database_uri(args.database_uri),
            "dry_run": bool(args.dry_run),
            "checkpoint_mode": args.checkpoint_mode,
        },
        "steps": [
            setup_step,
            sqlite_step,
            store_step,
            focus_memories_step,
            checkpoint_step,
            memory_embedding_step,
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
            "generated_at": datetime.now(UTC).isoformat(),
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
