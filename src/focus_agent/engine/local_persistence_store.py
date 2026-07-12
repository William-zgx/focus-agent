from __future__ import annotations

import asyncio
import atexit
import json
import sqlite3
import weakref
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.store.base import Item, PutOp
from langgraph.store.memory import InMemoryStore

_FOCUS_AGENT_ALLOWED_MSGPACK_TYPES: tuple[tuple[str, str], ...] = (
    ("focus_agent.core.types", "PromptMode"),
    ("focus_agent.core.types", "PinnedFact"),
    ("focus_agent.core.types", "ConstraintItem"),
    ("focus_agent.core.types", "FindingItem"),
    ("focus_agent.core.types", "ArtifactRef"),
    ("focus_agent.core.types", "CitationRef"),
    ("focus_agent.core.types", "ContextBudget"),
    ("focus_agent.core.types", "Plan"),
    ("focus_agent.core.types", "PlanStep"),
    ("focus_agent.core.types", "ReflectionVerdict"),
)


def _focus_agent_checkpoint_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=_FOCUS_AGENT_ALLOWED_MSGPACK_TYPES)


_PERSISTENCE_REGISTRY_LOCK = RLock()
_PERSISTENCE_INSTANCES: weakref.WeakSet[Any] = weakref.WeakSet()


def _register_persistence_instance(instance: Any) -> None:
    with _PERSISTENCE_REGISTRY_LOCK:
        _PERSISTENCE_INSTANCES.add(instance)


def _flush_open_persistence_for_path(path: Path) -> None:
    with _PERSISTENCE_REGISTRY_LOCK:
        instances = [
            instance
            for instance in _PERSISTENCE_INSTANCES
            if getattr(instance, "path", None) == path
        ]
    for instance in instances:
        instance.close()


def _close_registered_persistence() -> None:
    with _PERSISTENCE_REGISTRY_LOCK:
        instances = list(_PERSISTENCE_INSTANCES)
    for instance in instances:
        instance.close()


atexit.register(_close_registered_persistence)


class PersistentSQLiteStore(InMemoryStore):
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        _flush_open_persistence_for_path(self.path)
        self._lock = RLock()
        self._serde = _focus_agent_checkpoint_serde()
        super().__init__()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self.setup()
        self._restore()
        _register_persistence_instance(self)

    def setup(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS store_items (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_type TEXT NOT NULL,
                    value BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, key)
                );

                CREATE TABLE IF NOT EXISTS store_vectors (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    path TEXT NOT NULL,
                    vector TEXT NOT NULL,
                    PRIMARY KEY (namespace, key, path)
                );
                """
            )

    @staticmethod
    def _encode_namespace(namespace: tuple[str, ...]) -> str:
        return json.dumps(namespace, ensure_ascii=True, separators=(",", ":"))

    @staticmethod
    def _decode_namespace(namespace: str) -> tuple[str, ...]:
        return tuple(json.loads(namespace))

    def _restore(self) -> None:
        data = defaultdict(dict)
        vectors = defaultdict(lambda: defaultdict(dict))
        for row in self._conn.execute(
            """
            SELECT namespace, key, value_type, value, created_at, updated_at
            FROM store_items
            """
        ):
            namespace = self._decode_namespace(row[0])
            key = row[1]
            data[namespace][key] = Item(
                namespace=namespace,
                key=key,
                value=self._serde.loads_typed((row[2], bytes(row[3]))),
                created_at=datetime.fromisoformat(row[4]),
                updated_at=datetime.fromisoformat(row[5]),
            )
        for row in self._conn.execute("SELECT namespace, key, path, vector FROM store_vectors"):
            namespace = self._decode_namespace(row[0])
            vectors[namespace][row[1]][row[2]] = json.loads(row[3])
        self._data = data
        self._vectors = vectors

    def _persist_put_ops(self, ops: list[object]) -> None:
        put_ops = {(op.namespace, op.key): op for op in ops if isinstance(op, PutOp)}
        if not put_ops:
            return
        with self._conn:
            for namespace, key in put_ops:
                encoded_namespace = self._encode_namespace(namespace)
                item = self._data[namespace].get(key)
                if item is None:
                    self._conn.execute(
                        "DELETE FROM store_items WHERE namespace = ? AND key = ?",
                        (encoded_namespace, key),
                    )
                    self._conn.execute(
                        "DELETE FROM store_vectors WHERE namespace = ? AND key = ?",
                        (encoded_namespace, key),
                    )
                    continue

                value_type, value = self._serde.dumps_typed(item.value)
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO store_items (
                        namespace, key, value_type, value, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        encoded_namespace,
                        key,
                        value_type,
                        sqlite3.Binary(value),
                        item.created_at.isoformat(),
                        item.updated_at.isoformat(),
                    ),
                )
                self._conn.execute(
                    "DELETE FROM store_vectors WHERE namespace = ? AND key = ?",
                    (encoded_namespace, key),
                )
                self._conn.executemany(
                    """
                    INSERT INTO store_vectors (namespace, key, path, vector)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (
                            encoded_namespace,
                            key,
                            path,
                            json.dumps(vector, separators=(",", ":")),
                        )
                        for path, vector in self._vectors[namespace].get(key, {}).items()
                    ],
                )

    def batch(self, ops):
        ops = list(ops)
        with self._lock:
            result = super().batch(ops)
            self._persist_put_ops(ops)
        return result

    async def abatch(self, ops):
        return await asyncio.to_thread(self.batch, list(ops))

    def close(self) -> None:
        with self._lock:
            conn = getattr(self, "_conn", None)
            if conn is not None:
                conn.close()
                self._conn = None
