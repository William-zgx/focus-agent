from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from langgraph.graph import END, START, StateGraph

from focus_agent.config import Settings
from focus_agent.core.types import PromptMode
from focus_agent.engine.local_persistence import (
    PersistentInMemorySaver,
    PersistentInMemoryStore,
    PersistentSQLiteSaver,
    PersistentSQLiteStore,
)
from focus_agent.engine.runtime_persistence import _create_local_fallback_persistence

_HMAC_KEY = "local-graph-persistence-test-key-32-chars"


def _local_settings(tmp_path: Path, *, resolved_env: dict[str, str] | None = None) -> Settings:
    return Settings(
        branch_db_path=str(tmp_path / "branches.sqlite3"),
        resolved_env=resolved_env or {},
    )


def _close_local_persistence(persistence: tuple[object, ...]) -> None:
    for component in (persistence[0], persistence[1], persistence[-1]):
        close = getattr(component, "close", None)
        if close is not None:
            close()


def _write_local_state(persistence: tuple[object, ...]) -> None:
    checkpointer, store = persistence[0], persistence[1]
    builder = StateGraph(dict)
    builder.add_node(
        "write_answer", lambda state: {"answer": (state.get("question") or "").upper()}
    )
    builder.add_edge(START, "write_answer")
    builder.add_edge("write_answer", END)
    graph = builder.compile(checkpointer=checkpointer)
    graph.invoke({"question": "hello"}, config={"configurable": {"thread_id": "thread-1"}})
    store.put(("conversation", "root-1"), "memory-1", {"summary": "existing conclusion"})


def _assert_local_state_restored(persistence: tuple[object, ...]) -> None:
    checkpointer, store = persistence[0], persistence[1]
    builder = StateGraph(dict)
    builder.add_node(
        "write_answer", lambda state: {"answer": (state.get("question") or "").upper()}
    )
    builder.add_edge(START, "write_answer")
    builder.add_edge("write_answer", END)
    graph = builder.compile(checkpointer=checkpointer)

    restored_state = graph.get_state({"configurable": {"thread_id": "thread-1"}})
    restored_item = store.get(("conversation", "root-1"), "memory-1")

    assert restored_state.values["answer"] == "HELLO"
    assert restored_item is not None
    assert restored_item.value["summary"] == "existing conclusion"


def test_default_local_persistence_restores_without_hmac_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_BACKEND", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE", raising=False)
    settings = _local_settings(tmp_path)

    persistence = _create_local_fallback_persistence(settings)
    try:
        _write_local_state(persistence)
    finally:
        _close_local_persistence(persistence)

    restored = _create_local_fallback_persistence(settings)
    try:
        _assert_local_state_restored(restored)
    finally:
        _close_local_persistence(restored)


def test_default_local_persistence_uses_signed_legacy_pickles(tmp_path: Path, monkeypatch, caplog):
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_BACKEND", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE", raising=False)
    legacy_settings = _local_settings(
        tmp_path,
        resolved_env={
            "FOCUS_AGENT_CHECKPOINT_BACKEND": "pickle",
            "FOCUS_AGENT_CHECKPOINT_HMAC_KEY": _HMAC_KEY,
        },
    )
    persistence = _create_local_fallback_persistence(legacy_settings)
    try:
        _write_local_state(persistence)
    finally:
        _close_local_persistence(persistence)

    caplog.set_level("WARNING", logger="focus_agent.engine.runtime_persistence")
    restored = _create_local_fallback_persistence(
        _local_settings(
            tmp_path,
            resolved_env={"FOCUS_AGENT_CHECKPOINT_HMAC_KEY": _HMAC_KEY},
        )
    )
    try:
        _assert_local_state_restored(restored)
        assert isinstance(restored[0], PersistentInMemorySaver)
        assert isinstance(restored[1], PersistentInMemoryStore)
    finally:
        _close_local_persistence(restored)

    assert "Using signed legacy pickle persistence" in caplog.text
    assert not (tmp_path / "langgraph-checkpoints.sqlite3").exists()
    assert not (tmp_path / "langgraph-store.sqlite3").exists()


def test_default_local_persistence_rejects_unsigned_legacy_pickles(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_BACKEND", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE", raising=False)
    legacy_checkpoint = tmp_path / "langgraph-checkpoints.pkl"
    legacy_checkpoint.write_bytes(b"unsigned legacy checkpoint")

    with pytest.raises(ValueError, match="Cannot safely use legacy pickle persistence"):
        _create_local_fallback_persistence(
            _local_settings(
                tmp_path,
                resolved_env={"FOCUS_AGENT_CHECKPOINT_HMAC_KEY": _HMAC_KEY},
            )
        )

    assert not (tmp_path / "langgraph-checkpoints.sqlite3").exists()
    assert not (tmp_path / "langgraph-store.sqlite3").exists()


def test_default_local_persistence_rejects_legacy_pickles_without_hmac_key(
    tmp_path: Path, monkeypatch
):
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_BACKEND", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE", raising=False)
    (tmp_path / "langgraph-checkpoints.pkl").write_bytes(b"legacy checkpoint")

    with pytest.raises(ValueError, match="FOCUS_AGENT_CHECKPOINT_HMAC_KEY"):
        _create_local_fallback_persistence(_local_settings(tmp_path))

    assert not (tmp_path / "langgraph-checkpoints.sqlite3").exists()
    assert not (tmp_path / "langgraph-store.sqlite3").exists()


def test_explicit_pickle_without_hmac_key_is_rejected_before_creation(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE", raising=False)
    settings = _local_settings(
        tmp_path,
        resolved_env={"FOCUS_AGENT_CHECKPOINT_BACKEND": "pickle"},
    )

    with pytest.raises(ValueError, match="FOCUS_AGENT_CHECKPOINT_HMAC_KEY"):
        _create_local_fallback_persistence(settings)

    assert not (tmp_path / "langgraph-checkpoints.pkl").exists()
    assert not (tmp_path / "langgraph-store.pkl").exists()


def test_explicit_pickle_with_resolved_hmac_key_restores_after_restart(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE", raising=False)
    settings = _local_settings(
        tmp_path,
        resolved_env={
            "FOCUS_AGENT_CHECKPOINT_BACKEND": "pickle",
            "FOCUS_AGENT_CHECKPOINT_HMAC_KEY": _HMAC_KEY,
        },
    )

    persistence = _create_local_fallback_persistence(settings)
    try:
        _write_local_state(persistence)
    finally:
        _close_local_persistence(persistence)

    restored = _create_local_fallback_persistence(settings)
    try:
        _assert_local_state_restored(restored)
    finally:
        _close_local_persistence(restored)


def test_persistent_in_memory_saver_restores_thread_state(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", _HMAC_KEY)
    checkpoint_path = tmp_path / "langgraph-checkpoints.pkl"
    saver = PersistentInMemorySaver(checkpoint_path)

    builder = StateGraph(dict)
    builder.add_node(
        "write_answer", lambda state: {"answer": (state.get("question") or "").upper()}
    )
    builder.add_edge(START, "write_answer")
    builder.add_edge("write_answer", END)
    graph = builder.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "thread-1"}}
    graph.invoke({"question": "hello"}, config=config)
    saver.close()

    restored_graph = builder.compile(checkpointer=PersistentInMemorySaver(checkpoint_path))
    restored_state = restored_graph.get_state(config)

    assert restored_state.values["answer"] == "HELLO"


def test_persistent_in_memory_store_restores_items(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", _HMAC_KEY)
    store_path = tmp_path / "langgraph-store.pkl"
    store = PersistentInMemoryStore(store_path)
    namespace = ("conversation", "root-1", "main")

    store.put(
        namespace, "memory-1", {"summary": "existing conclusion", "type": "imported_conclusion"}
    )
    store.close()

    restored = PersistentInMemoryStore(store_path)
    item = restored.get(namespace, "memory-1")

    assert item is not None
    assert item.value["summary"] == "existing conclusion"


def test_persistent_in_memory_saver_allows_prompt_mode_without_warning(tmp_path: Path, caplog):
    checkpoint_path = tmp_path / "langgraph-checkpoints.pkl"
    saver = PersistentInMemorySaver(checkpoint_path)

    caplog.set_level("WARNING", logger="langgraph.checkpoint.serde.jsonplus")

    encoded = saver.serde.dumps_typed(PromptMode.EXPLORE)
    decoded = saver.serde.loads_typed(encoded)

    assert decoded == PromptMode.EXPLORE
    assert "Deserializing unregistered type focus_agent.core.types.PromptMode" not in caplog.text


def test_persistent_sqlite_saver_restores_thread_state(tmp_path: Path):
    checkpoint_path = tmp_path / "langgraph-checkpoints.sqlite3"
    saver = PersistentSQLiteSaver(checkpoint_path)

    builder = StateGraph(dict)
    builder.add_node(
        "write_answer", lambda state: {"answer": (state.get("question") or "").upper()}
    )
    builder.add_edge(START, "write_answer")
    builder.add_edge("write_answer", END)
    graph = builder.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "thread-1"}}
    graph.invoke({"question": "hello"}, config=config)
    saver.close()

    restored = PersistentSQLiteSaver(checkpoint_path)
    try:
        restored_graph = builder.compile(checkpointer=restored)
        restored_state = restored_graph.get_state(config)
    finally:
        restored.close()

    assert restored_state.values["answer"] == "HELLO"


def test_persistent_sqlite_store_async_write_restores_after_restart(tmp_path: Path):
    store_path = tmp_path / "langgraph-store.sqlite3"
    namespace = ("conversation", "root-1")

    async def write_item() -> None:
        store = PersistentSQLiteStore(store_path)
        try:
            await store.aput(
                namespace,
                "memory-1",
                {"summary": "async conclusion"},
            )
        finally:
            store.close()

    asyncio.run(write_item())

    restored = PersistentSQLiteStore(store_path)
    try:
        item = restored.get(namespace, "memory-1")
    finally:
        restored.close()

    assert item is not None
    assert item.value["summary"] == "async conclusion"
