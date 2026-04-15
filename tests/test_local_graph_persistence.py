from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, START, StateGraph

from focus_agent.engine.local_persistence import PersistentInMemorySaver, PersistentInMemoryStore


def test_persistent_in_memory_saver_restores_thread_state(tmp_path: Path):
    checkpoint_path = tmp_path / "langgraph-checkpoints.pkl"
    saver = PersistentInMemorySaver(checkpoint_path)

    builder = StateGraph(dict)
    builder.add_node("write_answer", lambda state: {"answer": (state.get("question") or "").upper()})
    builder.add_edge(START, "write_answer")
    builder.add_edge("write_answer", END)
    graph = builder.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "thread-1"}}
    graph.invoke({"question": "hello"}, config=config)

    restored_graph = builder.compile(checkpointer=PersistentInMemorySaver(checkpoint_path))
    restored_state = restored_graph.get_state(config)

    assert restored_state.values["answer"] == "HELLO"


def test_persistent_in_memory_store_restores_items(tmp_path: Path):
    store_path = tmp_path / "langgraph-store.pkl"
    store = PersistentInMemoryStore(store_path)
    namespace = ("conversation", "root-1", "main")

    store.put(namespace, "memory-1", {"summary": "existing conclusion", "type": "imported_conclusion"})

    restored = PersistentInMemoryStore(store_path)
    item = restored.get(namespace, "memory-1")

    assert item is not None
    assert item.value["summary"] == "existing conclusion"
