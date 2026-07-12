from __future__ import annotations

import asyncio
from pathlib import Path

import focus_agent.engine.local_persistence as local_persistence
import focus_agent.engine.local_persistence_store as local_persistence_store
from focus_agent.engine.local_persistence import PersistentSQLiteStore
from focus_agent.engine.local_persistence_store import PersistentSQLiteStore as ExtractedStore


def test_sqlite_store_remains_compatibly_exported_from_local_persistence() -> None:
    persistence_path = Path(local_persistence.__file__)

    assert len(persistence_path.read_text(encoding="utf-8").splitlines()) <= 620
    assert PersistentSQLiteStore is ExtractedStore
    assert PersistentSQLiteStore is local_persistence_store.PersistentSQLiteStore


def test_extracted_sqlite_store_preserves_async_persistence(tmp_path: Path) -> None:
    store_path = tmp_path / "store.sqlite3"
    namespace = ("conversation", "root-1")

    async def write_item() -> None:
        store = ExtractedStore(store_path)
        try:
            await store.aput(namespace, "memory-1", {"summary": "async conclusion"})
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
