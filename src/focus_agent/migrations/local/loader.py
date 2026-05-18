from __future__ import annotations

import argparse
import importlib
import json
import os
import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from psycopg import Connection
from psycopg.rows import dict_row

from ...core.repo_call import has_repo_method
from ...engine.local_persistence import (
    PersistentInMemorySaver,
    PersistentInMemoryStore,
    _focus_agent_checkpoint_serde,
)
from ...memory.embedding_service import MemoryEmbeddingService
from ...repositories.memory_repository import MemoryListQuery
from ...repositories.postgres_trajectory_repository import PostgresTrajectoryRepository


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
    sink: AppStateSink | None
    description: str | None
    attempts: list[str]


class AppStateSink(Protocol):
    def setup(self) -> None: ...

    def upsert_thread_access_rows(self, rows: Sequence[dict[str, Any]]) -> int | None: ...

    def upsert_conversation_rows(self, rows: Sequence[dict[str, Any]]) -> int | None: ...

    def upsert_branch_rows(self, rows: Sequence[dict[str, Any]]) -> int | None: ...


class FocusMemorySink(Protocol):
    def setup(self) -> None: ...

    def upsert_record(self, record) -> str: ...

    def list_records(self, query: MemoryListQuery) -> list: ...


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


def create_memory_repository(database_uri: str) -> FocusMemorySink:
    from ...repositories.postgres_memory_repository import PostgresMemoryRepository

    return PostgresMemoryRepository(database_uri)


def create_memory_embedding_service(database_uri: str) -> MemoryEmbeddingService | None:
    candidates: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
        (
            "focus_agent.repositories.postgres_memory_embedding_repository",
            (
                "create_memory_embedding_service",
                "create_postgres_memory_embedding_service",
                "create_memory_embedding_repository",
            ),
            (
                "PostgresMemoryEmbeddingRepository",
                "PostgresMemoryEmbeddingsRepository",
            ),
        ),
    )
    for module_name, factory_names, class_names in candidates:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue

        for factory_name in factory_names:
            factory = getattr(module, factory_name, None)
            if callable(factory):
                service = _coerce_memory_embedding_service(factory(database_uri))
                if service is not None:
                    return service

        for class_name in class_names:
            repository_class = getattr(module, class_name, None)
            if repository_class is None:
                continue
            service = _coerce_memory_embedding_service(repository_class(database_uri))
            if service is not None:
                return service

    from ...memory.embedding import create_memory_embedding_service as create_configured_service

    return create_configured_service(
        _migration_memory_embedding_settings(),
        repository=create_memory_repository(database_uri),
    )


def _coerce_memory_embedding_service(candidate: object | None) -> MemoryEmbeddingService | None:
    if candidate is None:
        return None
    if has_repo_method(candidate, "ensure_embedding"):
        return candidate  # type: ignore[return-value]
    return MemoryEmbeddingService.from_repository(candidate)


def _migration_memory_embedding_settings() -> object:
    from types import SimpleNamespace

    return SimpleNamespace(
        agent_memory_embedding_enabled=True,
        agent_memory_embedding_backend=(
            os.environ.get("AGENT_MEMORY_EMBEDDING_BACKEND")
            or os.environ.get("AGENT_MEMORY_EMBEDDING_PROVIDER")
            or "auto"
        ),
        agent_memory_embedding_provider=(
            os.environ.get("AGENT_MEMORY_EMBEDDING_PROVIDER") or "openai_compatible"
        ),
        agent_memory_embedding_model=(
            os.environ.get("AGENT_MEMORY_EMBEDDING_MODEL") or "embeddinggemma"
        ),
        agent_memory_embedding_dimensions=int(
            os.environ.get("AGENT_MEMORY_EMBEDDING_DIMENSIONS") or "768"
        ),
        agent_memory_embedding_base_url=os.environ.get("AGENT_MEMORY_EMBEDDING_BASE_URL"),
        agent_memory_embedding_api_key_env=(
            os.environ.get("AGENT_MEMORY_EMBEDDING_API_KEY_ENV") or "OPENAI_API_KEY"
        ),
        agent_memory_embedding_api_key=os.environ.get("AGENT_MEMORY_EMBEDDING_API_KEY"),
        agent_memory_embedding_batch_size=int(
            os.environ.get("AGENT_MEMORY_EMBEDDING_BATCH_SIZE") or "32"
        ),
        agent_memory_embedding_timeout_seconds=float(
            os.environ.get("AGENT_MEMORY_EMBEDDING_TIMEOUT_SECONDS") or "30.0"
        ),
        resolved_env=dict(os.environ),
    )


def _redact_database_uri(database_uri: str) -> str:
    try:
        parsed = urlsplit(database_uri)
    except ValueError:
        return "<redacted>"
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    netloc = f"***@{host}" if parsed.username or parsed.password else host
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


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
        "--backfill-memory-embeddings",
        action="store_true",
        help="Idempotently write missing embeddings for active focus memories after migration.",
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
    if (
        not (resolved_dir / "branches.sqlite3").exists()
        and (resolved_dir / ".focus_agent").is_dir()
    ):
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
                    value=_store_item_value_to_dict(value),
                    created_at=created_at.isoformat()
                    if hasattr(created_at, "isoformat")
                    else created_at,
                    updated_at=updated_at.isoformat()
                    if hasattr(updated_at, "isoformat")
                    else updated_at,
                )
            )
    records.sort(key=lambda item: (".".join(item.namespace), item.key))
    return records


def _store_item_value_to_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if has_repo_method(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    if value is None:
        return {}
    return {"value": str(value)}


def load_local_checkpoints(checkpoint_path: Path) -> list[LocalCheckpointRecord]:
    if not checkpoint_path.exists():
        return []

    saver = PersistentInMemorySaver(checkpoint_path)
    records: list[LocalCheckpointRecord] = []
    for checkpoint_tuple in saver.list(None):
        configurable = checkpoint_tuple.config["configurable"]
        parent_config = (
            checkpoint_tuple.parent_config["configurable"] if checkpoint_tuple.parent_config else {}
        )
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
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            }
        )
    return results
