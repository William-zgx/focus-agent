from __future__ import annotations

import json
import pickle
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ...engine.local_persistence import _focus_agent_checkpoint_serde

_SQLITE_HEADER = b"SQLite format 3\x00"
_STORE_SCHEMA = {
    "store_items": {
        "namespace",
        "key",
        "value_type",
        "value",
        "created_at",
        "updated_at",
    },
    "store_vectors": {"namespace", "key", "path", "vector"},
}
_CHECKPOINT_SCHEMA = {
    "checkpoint_storage": {
        "thread_id",
        "checkpoint_ns",
        "checkpoint_id",
        "checkpoint_type",
        "checkpoint",
        "metadata_type",
        "metadata",
        "parent_checkpoint_id",
    },
    "checkpoint_blobs": {
        "thread_id",
        "checkpoint_ns",
        "channel",
        "version",
        "value_type",
        "value",
    },
    "checkpoint_writes": {
        "thread_id",
        "checkpoint_ns",
        "checkpoint_id",
        "task_id",
        "write_idx",
        "channel",
        "value_type",
        "value",
        "task_path",
    },
}


def has_sqlite_header(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(_SQLITE_HEADER)) == _SQLITE_HEADER
    except OSError:
        return False


@contextmanager
def _open_readonly_sqlite(
    path: Path,
    *,
    source_name: str,
    required_schema: Mapping[str, set[str]],
) -> Iterator[sqlite3.Connection]:
    if not has_sqlite_header(path):
        raise ValueError(f"Unrecognized canonical SQLite {source_name} file: {path}")
    _require_checkpointed_sqlite(path, source_name=source_name)

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"{path.resolve().as_uri()}?mode=ro&immutable=1",
            uri=True,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        _validate_schema(
            connection,
            path=path,
            source_name=source_name,
            required_schema=required_schema,
        )
    except sqlite3.DatabaseError as exc:
        if connection is not None:
            connection.close()
        raise ValueError(f"Unrecognized canonical SQLite {source_name} file: {path}") from exc
    except Exception:
        if connection is not None:
            connection.close()
        raise

    assert connection is not None
    try:
        yield connection
    finally:
        connection.close()


def _require_checkpointed_sqlite(path: Path, *, source_name: str) -> None:
    resolved_path = path.resolve()
    sidecars = [
        resolved_path.with_name(resolved_path.name + suffix)
        for suffix in ("-wal", "-shm")
        if resolved_path.with_name(resolved_path.name + suffix).exists()
    ]
    if sidecars:
        raise ValueError(
            f"Canonical SQLite {source_name} file has active WAL sidecars: "
            f"{', '.join(str(sidecar) for sidecar in sidecars)}. "
            "Stop the local runtime and checkpoint the database before migrating."
        )


def _validate_schema(
    connection: sqlite3.Connection,
    *,
    path: Path,
    source_name: str,
    required_schema: Mapping[str, set[str]],
) -> None:
    table_rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    table_names = {str(row["name"]) for row in table_rows}
    missing_tables = set(required_schema) - table_names
    missing_columns: dict[str, list[str]] = {}
    for table_name, expected_columns in required_schema.items():
        if table_name not in table_names:
            continue
        column_rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
        actual_columns = {str(row["name"]) for row in column_rows}
        missing = sorted(expected_columns - actual_columns)
        if missing:
            missing_columns[table_name] = missing

    if missing_tables or missing_columns:
        details: list[str] = []
        if missing_tables:
            details.append(f"missing tables: {', '.join(sorted(missing_tables))}")
        if missing_columns:
            details.append(
                "missing columns: "
                + "; ".join(
                    f"{table}({', '.join(columns)})"
                    for table, columns in sorted(missing_columns.items())
                )
            )
        raise ValueError(
            f"Unrecognized canonical SQLite {source_name} file: {path} ({'; '.join(details)})"
        )


def read_store_items(path: Path) -> list[dict[str, Any]]:
    serde = _focus_agent_checkpoint_serde()
    try:
        with _open_readonly_sqlite(
            path,
            source_name="store",
            required_schema=_STORE_SCHEMA,
        ) as connection:
            rows = connection.execute(
                """
                SELECT namespace, key, value_type, value, created_at, updated_at
                FROM store_items
                ORDER BY namespace, key
                """
            ).fetchall()
            return [
                {
                    "namespace": _decode_namespace(str(row["namespace"])),
                    "key": str(row["key"]),
                    "value": serde.loads_typed((str(row["value_type"]), bytes(row["value"]))),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                }
                for row in rows
            ]
    except (json.JSONDecodeError, TypeError, UnicodeError, sqlite3.DatabaseError) as exc:
        raise ValueError(f"Invalid canonical SQLite store data: {path}") from exc


def _decode_namespace(value: str) -> tuple[str, ...]:
    decoded = json.loads(value)
    if not isinstance(decoded, list) or not all(isinstance(part, str) for part in decoded):
        raise ValueError("store namespace must be a JSON string array")
    return tuple(decoded)


def read_checkpoints(path: Path) -> list[dict[str, Any]]:
    serde = _focus_agent_checkpoint_serde()
    try:
        with _open_readonly_sqlite(
            path,
            source_name="checkpoints",
            required_schema=_CHECKPOINT_SCHEMA,
        ) as connection:
            blobs = _load_checkpoint_blobs(connection)
            pending_write_counts = _load_pending_write_counts(connection)
            rows = connection.execute(
                """
                SELECT thread_id, checkpoint_ns, checkpoint_id, checkpoint_type, checkpoint,
                       metadata_type, metadata, parent_checkpoint_id
                FROM checkpoint_storage
                ORDER BY thread_id, checkpoint_ns, checkpoint_id DESC
                """
            ).fetchall()

            records: list[dict[str, Any]] = []
            for row in rows:
                thread_id = str(row["thread_id"])
                checkpoint_ns = str(row["checkpoint_ns"])
                checkpoint_id = str(row["checkpoint_id"])
                checkpoint = serde.loads_typed(
                    (str(row["checkpoint_type"]), bytes(row["checkpoint"]))
                )
                if not isinstance(checkpoint, dict):
                    raise ValueError("checkpoint payload must decode to a mapping")
                metadata = serde.loads_typed((str(row["metadata_type"]), bytes(row["metadata"])))
                if not isinstance(metadata, dict):
                    raise ValueError("checkpoint metadata must decode to a mapping")
                checkpoint["channel_values"] = _load_channel_values(
                    serde,
                    blobs,
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    channel_versions=checkpoint.get("channel_versions", {}),
                )
                records.append(
                    {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                        "checkpoint": checkpoint,
                        "metadata": metadata,
                        "parent_checkpoint_id": (
                            str(row["parent_checkpoint_id"])
                            if row["parent_checkpoint_id"] is not None
                            else None
                        ),
                        "pending_write_count": pending_write_counts.get(
                            (thread_id, checkpoint_ns, checkpoint_id),
                            0,
                        ),
                    }
                )
            return records
    except (TypeError, UnicodeError, sqlite3.DatabaseError) as exc:
        raise ValueError(f"Invalid canonical SQLite checkpoint data: {path}") from exc


def _load_checkpoint_blobs(
    connection: sqlite3.Connection,
) -> dict[tuple[str, str, str, bytes], tuple[str, bytes]]:
    rows = connection.execute(
        """
        SELECT thread_id, checkpoint_ns, channel, version, value_type, value
        FROM checkpoint_blobs
        """
    ).fetchall()
    return {
        (
            str(row["thread_id"]),
            str(row["checkpoint_ns"]),
            str(row["channel"]),
            bytes(row["version"]),
        ): (str(row["value_type"]), bytes(row["value"]))
        for row in rows
    }


def _load_pending_write_counts(
    connection: sqlite3.Connection,
) -> dict[tuple[str, str, str], int]:
    rows = connection.execute(
        """
        SELECT thread_id, checkpoint_ns, checkpoint_id, COUNT(*) AS pending_write_count
        FROM checkpoint_writes
        GROUP BY thread_id, checkpoint_ns, checkpoint_id
        """
    ).fetchall()
    return {
        (
            str(row["thread_id"]),
            str(row["checkpoint_ns"]),
            str(row["checkpoint_id"]),
        ): int(row["pending_write_count"])
        for row in rows
    }


def _load_channel_values(
    serde: Any,
    blobs: Mapping[tuple[str, str, str, bytes], tuple[str, bytes]],
    *,
    thread_id: str,
    checkpoint_ns: str,
    channel_versions: object,
) -> dict[str, Any]:
    if not isinstance(channel_versions, dict):
        raise ValueError("checkpoint channel_versions must decode to a mapping")

    channel_values: dict[str, Any] = {}
    for channel, version in channel_versions.items():
        if not isinstance(channel, str):
            raise ValueError("checkpoint channel names must be strings")
        encoded_version = pickle.dumps(version, protocol=pickle.HIGHEST_PROTOCOL)
        value = blobs.get((thread_id, checkpoint_ns, channel, encoded_version))
        if value is None:
            raise ValueError(
                "checkpoint blob is missing for "
                f"thread={thread_id!r}, namespace={checkpoint_ns!r}, channel={channel!r}"
            )
        if value[0] != "empty":
            channel_values[channel] = serde.loads_typed(value)
    return channel_values
