from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from focus_agent.core.types import PromptMode
from focus_agent.engine.local_persistence import (
    PersistentInMemorySaver,
    PersistentInMemoryStore,
    PersistentSQLiteSaver,
)

_HMAC_KEY = "local-graph-persistence-test-key-32-chars"


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
