from __future__ import annotations

import importlib.util
from pathlib import Path

from langgraph.checkpoint.base import empty_checkpoint

from focus_agent.engine.local_persistence import PersistentInMemorySaver, PersistentSQLiteSaver

_HMAC_KEY = "sqlite-migration-test-key-32-chars"
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / (
    "migrate_checkpoint_pickle_to_sqlite.py"
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location("migrate_checkpoint_pickle_to_sqlite", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _checkpoint(checkpoint_id: str = "checkpoint-1"):
    checkpoint = empty_checkpoint()
    checkpoint["id"] = checkpoint_id
    checkpoint["channel_values"] = {"answer": "HELLO"}
    checkpoint["channel_versions"] = {"answer": "1"}
    return checkpoint


def test_migrate_checkpoint_pickle_to_sqlite_preserves_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", _HMAC_KEY)
    source = tmp_path / "langgraph-checkpoints.pkl"
    target = tmp_path / "langgraph-checkpoints.sqlite3"
    saver = PersistentInMemorySaver(source)
    try:
        saver.put(
            {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}},
            _checkpoint(),
            {"source": "test"},
            {"answer": "1"},
        )
    finally:
        saver.close()

    module = _load_script_module()
    report = module.migrate(source, target, dry_run=False, force=False)

    restored = PersistentSQLiteSaver(target)
    try:
        checkpoint_tuple = restored.get_tuple({"configurable": {"thread_id": "thread-1"}})
    finally:
        restored.close()

    assert report["status"] == "completed"
    assert report["source_checkpoint_count"] == 1
    assert report["migrated_checkpoint_count"] == 1
    assert checkpoint_tuple is not None
    assert checkpoint_tuple.checkpoint["channel_values"]["answer"] == "HELLO"


def test_migrate_checkpoint_pickle_to_sqlite_preserves_parent_lineage(tmp_path, monkeypatch):
    monkeypatch.setenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", _HMAC_KEY)
    source = tmp_path / "langgraph-checkpoints.pkl"
    target = tmp_path / "langgraph-checkpoints.sqlite3"
    saver = PersistentInMemorySaver(source)
    try:
        config = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}
        first_config = saver.put(
            config,
            _checkpoint("checkpoint-1"),
            {"source": "test", "step": 1},
            {"answer": "1"},
        )
        saver.put(
            first_config,
            _checkpoint("checkpoint-2"),
            {"source": "test", "step": 2},
            {"answer": "2"},
        )
    finally:
        saver.close()

    module = _load_script_module()
    module.migrate(source, target, dry_run=False, force=False)

    restored = PersistentSQLiteSaver(target)
    try:
        migrated = {
            item.checkpoint["id"]: item
            for item in restored.list({"configurable": {"thread_id": "thread-1"}})
        }
    finally:
        restored.close()

    assert migrated["checkpoint-1"].parent_config is None
    assert migrated["checkpoint-2"].parent_config is not None
    assert (
        migrated["checkpoint-2"].parent_config["configurable"]["checkpoint_id"]
        == "checkpoint-1"
    )
