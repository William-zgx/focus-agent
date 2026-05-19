from __future__ import annotations

import asyncio
from pathlib import Path

from langgraph.checkpoint.base import empty_checkpoint
from langgraph.store.base import PutOp

from focus_agent.engine.local_persistence import PersistentInMemorySaver, PersistentInMemoryStore

_HMAC_KEY = "checkpoint-debounce-test-key-32-chars"


def _checkpoint(checkpoint_id: str = "checkpoint-1"):
    checkpoint = empty_checkpoint()
    checkpoint["id"] = checkpoint_id
    checkpoint["channel_values"] = {"answer": "HELLO"}
    checkpoint["channel_versions"] = {"answer": "1"}
    return checkpoint


def _config():
    return {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}


def test_saver_debounces_writes_until_close(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_INCREMENTAL", raising=False)
    monkeypatch.setenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", _HMAC_KEY)
    path = tmp_path / "checkpoints.pkl"
    saver = PersistentInMemorySaver(path)
    saver._flush_interval_ms = 10_000

    try:
        saved_config = saver.put(_config(), _checkpoint(), {}, {"answer": "1"})
        timer = saver._flush_timer

        saver.put_writes(saved_config, [("answer", "pending")], "task-1")

        assert saver._dirty is True
        assert saver._flush_timer is timer
        assert timer is not None
        assert not path.exists()
    finally:
        saver.close()

    restored = PersistentInMemorySaver(path)
    try:
        checkpoints = list(restored.list({"configurable": {"thread_id": "thread-1"}}))
    finally:
        restored.close()

    assert len(checkpoints) == 1


def test_store_debounces_batch_until_close(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_INCREMENTAL", raising=False)
    monkeypatch.setenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", _HMAC_KEY)
    path = tmp_path / "store.pkl"
    namespace = ("conversation", "root-1")
    store = PersistentInMemoryStore(path)
    store._flush_interval_ms = 10_000

    try:
        store.put(namespace, "memory-1", {"summary": "coalesced"})

        assert store._dirty is True
        assert store._flush_timer is not None
        assert not path.exists()
    finally:
        store.close()

    restored = PersistentInMemoryStore(path)
    try:
        item = restored.get(namespace, "memory-1")
    finally:
        restored.close()

    assert item is not None
    assert item.value["summary"] == "coalesced"


def test_async_paths_share_debounced_flush(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_INCREMENTAL", raising=False)
    monkeypatch.setenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", _HMAC_KEY)
    checkpoint_path = tmp_path / "async-checkpoints.pkl"
    store_path = tmp_path / "async-store.pkl"

    async def scenario() -> None:
        saver = PersistentInMemorySaver(checkpoint_path)
        saver._flush_interval_ms = 10_000
        store = PersistentInMemoryStore(store_path)
        store._flush_interval_ms = 10_000
        try:
            saved_config = await saver.aput(_config(), _checkpoint(), {}, {"answer": "1"})
            await saver.aput_writes(saved_config, [("answer", "pending")], "task-1")
            await store.abatch(
                [PutOp(("conversation", "root-1"), "memory-1", {"summary": "async"})]
            )

            assert saver._dirty is True
            assert saver._flush_timer is not None
            assert store._dirty is True
            assert store._flush_timer is not None
            assert not checkpoint_path.exists()
            assert not store_path.exists()
        finally:
            saver.close()
            store.close()

    asyncio.run(scenario())

    assert checkpoint_path.exists()
    assert store_path.exists()


def test_incremental_flag_off_flushes_synchronously(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FOCUS_AGENT_CHECKPOINT_INCREMENTAL", "0")
    monkeypatch.setenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", _HMAC_KEY)
    checkpoint_path = tmp_path / "checkpoints.pkl"
    store_path = tmp_path / "store.pkl"
    saver = PersistentInMemorySaver(checkpoint_path)
    store = PersistentInMemoryStore(store_path)

    try:
        saver.put(_config(), _checkpoint(), {}, {"answer": "1"})
        store.put(("conversation", "root-1"), "memory-1", {"summary": "sync"})

        assert checkpoint_path.exists()
        assert store_path.exists()
        assert saver._dirty is False
        assert store._dirty is False
        assert saver._flush_timer is None
        assert store._flush_timer is None
    finally:
        saver.close()
        store.close()
