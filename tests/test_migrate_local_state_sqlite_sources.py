from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from langgraph.checkpoint.base import empty_checkpoint

from focus_agent.engine.local_persistence import PersistentSQLiteSaver, PersistentSQLiteStore
from focus_agent.migrate_local_state import parse_args, run_migration
from focus_agent.migrations.local.loader import (
    AppStateSinkDiscovery,
    load_local_checkpoints,
    load_local_store_items,
    resolve_source_layout,
)


def _write_sqlite_store(path: Path) -> None:
    store = PersistentSQLiteStore(path)
    try:
        store.put(
            ("conversation", "root-1", "main"),
            "memory-1",
            {"summary": "sqlite conclusion", "type": "imported_conclusion"},
        )
    finally:
        store.close()


def _write_sqlite_checkpoints(path: Path) -> None:
    saver = PersistentSQLiteSaver(path)
    try:
        base_config = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}
        first_checkpoint = empty_checkpoint()
        first_checkpoint["id"] = "checkpoint-1"
        first_checkpoint["channel_values"] = {"answer": "stable"}
        first_checkpoint["channel_versions"] = {"answer": "1"}
        first_config = saver.put(
            base_config,
            first_checkpoint,
            {"source": "loop", "step": 0},
            {"answer": "1"},
        )

        second_checkpoint = empty_checkpoint()
        second_checkpoint["id"] = "checkpoint-2"
        second_checkpoint["channel_values"] = {"answer": "pending"}
        second_checkpoint["channel_versions"] = {"answer": "2"}
        second_config = saver.put(
            first_config,
            second_checkpoint,
            {"source": "loop", "step": 1},
            {"answer": "2"},
        )
        saver.put_writes(
            second_config,
            [("tasks", {"pending": True})],
            task_id="task-1",
        )
    finally:
        saver.close()


def test_resolve_source_layout_detects_default_sqlite_sources(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / ".focus_agent"
    state_dir.mkdir()
    store_path = state_dir / "langgraph-store.sqlite3"
    checkpoint_path = state_dir / "langgraph-checkpoints.sqlite3"
    _write_sqlite_store(store_path)
    _write_sqlite_checkpoints(checkpoint_path)
    monkeypatch.delenv("LOCAL_STORE_PATH", raising=False)
    monkeypatch.delenv("LOCAL_CHECKPOINT_PATH", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_BACKEND", raising=False)

    layout = resolve_source_layout(tmp_path)

    assert layout.store_path == store_path
    assert layout.checkpoint_path == checkpoint_path


def test_resolve_source_layout_honors_explicit_sqlite_paths(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / ".focus_agent"
    state_dir.mkdir()
    store_path = tmp_path / "configured" / "custom-store.db"
    checkpoint_path = tmp_path / "configured" / "custom-checkpoints.sqlite"
    _write_sqlite_store(store_path)
    _write_sqlite_checkpoints(checkpoint_path)
    monkeypatch.setenv("LOCAL_STORE_PATH", str(store_path))
    monkeypatch.setenv("LOCAL_CHECKPOINT_PATH", str(checkpoint_path))
    monkeypatch.setenv("FOCUS_AGENT_CHECKPOINT_BACKEND", "sqlite")

    layout = resolve_source_layout(state_dir)

    assert layout.store_path == store_path
    assert layout.checkpoint_path == checkpoint_path


def test_resolve_source_layout_rejects_ambiguous_default_sources(
    tmp_path: Path, monkeypatch
) -> None:
    state_dir = tmp_path / ".focus_agent"
    state_dir.mkdir()
    (state_dir / "langgraph-store.pkl").touch()
    (state_dir / "langgraph-store.sqlite3").touch()
    monkeypatch.delenv("LOCAL_STORE_PATH", raising=False)
    monkeypatch.delenv("LOCAL_CHECKPOINT_PATH", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_BACKEND", raising=False)

    with pytest.raises(ValueError, match="Ambiguous local store sources"):
        resolve_source_layout(tmp_path)


def test_resolve_source_layout_rejects_missing_explicit_source(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / ".focus_agent"
    state_dir.mkdir()
    missing_store = tmp_path / "missing" / "store.sqlite3"
    monkeypatch.setenv("LOCAL_STORE_PATH", str(missing_store))
    monkeypatch.setenv("FOCUS_AGENT_CHECKPOINT_BACKEND", "sqlite")

    with pytest.raises(FileNotFoundError, match="Configured local store source"):
        resolve_source_layout(state_dir)


def test_resolve_source_layout_rejects_backend_that_would_ignore_existing_source(
    tmp_path: Path, monkeypatch
) -> None:
    state_dir = tmp_path / ".focus_agent"
    state_dir.mkdir()
    _write_sqlite_store(state_dir / "langgraph-store.sqlite3")
    monkeypatch.delenv("LOCAL_STORE_PATH", raising=False)
    monkeypatch.delenv("LOCAL_CHECKPOINT_PATH", raising=False)
    monkeypatch.setenv("FOCUS_AGENT_CHECKPOINT_BACKEND", "pickle")

    with pytest.raises(ValueError, match="would ignore existing SQLite store source"):
        resolve_source_layout(tmp_path)


def test_load_local_sqlite_state_reads_store_checkpoints_and_pending_writes(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "langgraph-store.sqlite3"
    checkpoint_path = tmp_path / "langgraph-checkpoints.sqlite3"
    _write_sqlite_store(store_path)
    _write_sqlite_checkpoints(checkpoint_path)
    source_bytes = {
        store_path: store_path.read_bytes(),
        checkpoint_path: checkpoint_path.read_bytes(),
    }
    directory_entries = {path.name for path in tmp_path.iterdir()}

    store_records = load_local_store_items(store_path)
    checkpoint_records = load_local_checkpoints(checkpoint_path)

    assert {path.name for path in tmp_path.iterdir()} == directory_entries
    assert {path: path.read_bytes() for path in source_bytes} == source_bytes
    assert len(store_records) == 1
    assert store_records[0].namespace == ("conversation", "root-1", "main")
    assert store_records[0].key == "memory-1"
    assert store_records[0].value["summary"] == "sqlite conclusion"
    assert store_records[0].created_at is not None
    assert store_records[0].updated_at is not None

    assert [record.checkpoint_id for record in checkpoint_records] == [
        "checkpoint-2",
        "checkpoint-1",
    ]
    latest, oldest = checkpoint_records
    assert latest.checkpoint["channel_values"]["answer"] == "pending"
    assert latest.metadata == {"source": "loop", "step": 1}
    assert latest.parent_checkpoint_id == "checkpoint-1"
    assert latest.pending_write_count == 1
    assert oldest.checkpoint["channel_values"]["answer"] == "stable"
    assert oldest.parent_checkpoint_id is None
    assert oldest.pending_write_count == 0


def test_run_migration_dry_run_counts_default_sqlite_state(tmp_path: Path, monkeypatch) -> None:
    state_dir = tmp_path / ".focus_agent"
    state_dir.mkdir()
    store_path = state_dir / "langgraph-store.sqlite3"
    checkpoint_path = state_dir / "langgraph-checkpoints.sqlite3"
    _write_sqlite_store(store_path)
    _write_sqlite_checkpoints(checkpoint_path)
    monkeypatch.delenv("LOCAL_STORE_PATH", raising=False)
    monkeypatch.delenv("LOCAL_CHECKPOINT_PATH", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_BACKEND", raising=False)
    args = parse_args(
        [
            "--source-dir",
            str(tmp_path),
            "--database-uri",
            "postgresql://example/focus-agent",
            "--dry-run",
            "--report-path",
            str(tmp_path / "report.json"),
        ]
    )

    report = run_migration(
        args,
        sink_discovery=AppStateSinkDiscovery(
            sink=None,
            description=None,
            attempts=["test fixture"],
        ),
    )

    assert report["source"]["store_path"] == str(store_path)
    assert report["source"]["checkpoint_path"] == str(checkpoint_path)
    assert report["summary"]["store_item_count"] == 1
    assert report["summary"]["checkpoint_count"] == 2
    assert report["steps"][2]["details"]["migrated_item_count"] == 0
    assert report["steps"][2]["details"]["source_item_count"] == 1
    assert report["steps"][4]["details"]["selected_checkpoint_count"] == 1
    assert report["steps"][4]["details"]["skipped_due_to_pending_writes"] == 1


@pytest.mark.parametrize(
    ("filename", "loader"),
    [
        pytest.param("langgraph-store.sqlite3", load_local_store_items, id="store"),
        pytest.param(
            "langgraph-checkpoints.sqlite3",
            load_local_checkpoints,
            id="checkpoints",
        ),
    ],
)
def test_load_local_sqlite_state_rejects_unrecognized_canonical_schema(
    tmp_path: Path,
    filename: str,
    loader,
) -> None:
    path = tmp_path / filename
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE unrelated (value TEXT)")

    with pytest.raises(ValueError, match="Unrecognized canonical SQLite"):
        loader(path)


def test_load_local_sqlite_checkpoints_rejects_missing_channel_blob(tmp_path: Path) -> None:
    path = tmp_path / "langgraph-checkpoints.sqlite3"
    _write_sqlite_checkpoints(path)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute(
            """
            DELETE FROM checkpoint_blobs
            WHERE thread_id = ? AND checkpoint_ns = ? AND channel = ?
            """,
            ("thread-1", "", "answer"),
        )

    with pytest.raises(ValueError, match="checkpoint blob is missing"):
        load_local_checkpoints(path)


def test_load_local_sqlite_store_rejects_active_wal(tmp_path: Path) -> None:
    path = tmp_path / "langgraph-store.sqlite3"
    _write_sqlite_store(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            INSERT INTO store_items (
                namespace, key, value_type, value, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ('["conversation","root-2"]', "memory-2", "msgpack", b"invalid", "now", "now"),
        )
        connection.commit()
        assert path.with_name(path.name + "-wal").exists()

        with pytest.raises(ValueError, match="active WAL sidecars"):
            load_local_store_items(path)
    finally:
        connection.close()
