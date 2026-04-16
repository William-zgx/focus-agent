from __future__ import annotations

from collections import defaultdict
import os
import pickle
from pathlib import Path
from threading import RLock
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.store.memory import InMemoryStore

_FOCUS_AGENT_ALLOWED_MSGPACK_TYPES: tuple[tuple[str, str], ...] = (
    ("focus_agent.core.types", "PromptMode"),
    ("focus_agent.core.types", "PinnedFact"),
    ("focus_agent.core.types", "ConstraintItem"),
    ("focus_agent.core.types", "FindingItem"),
    ("focus_agent.core.types", "ArtifactRef"),
    ("focus_agent.core.types", "CitationRef"),
    ("focus_agent.core.types", "ContextBudget"),
)


def _focus_agent_checkpoint_serde() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=_FOCUS_AGENT_ALLOWED_MSGPACK_TYPES)


def _atomic_pickle_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp_path, path)


def _pickle_load(path: Path) -> Any | None:
    if not path.exists():
        return None
    with path.open("rb") as handle:
        return pickle.load(handle)


class PersistentInMemorySaver(InMemorySaver):
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self._lock = RLock()
        super().__init__(serde=_focus_agent_checkpoint_serde())
        self._restore()

    def _restore(self) -> None:
        payload = _pickle_load(self.path)
        if not payload:
            return
        storage = defaultdict(lambda: defaultdict(dict))
        for thread_id, namespaces in payload.get("storage", {}).items():
            storage[thread_id] = defaultdict(dict, {ns: dict(checkpoints) for ns, checkpoints in namespaces.items()})
        self.storage = storage
        self.writes = defaultdict(dict, {tuple(key): dict(value) for key, value in payload.get("writes", {}).items()})
        self.blobs = dict(payload.get("blobs", {}))

    def _flush(self) -> None:
        with self._lock:
            payload = {
                "storage": {
                    thread_id: {ns: dict(checkpoints) for ns, checkpoints in namespaces.items()}
                    for thread_id, namespaces in self.storage.items()
                },
                "writes": {tuple(key): dict(value) for key, value in self.writes.items()},
                "blobs": dict(self.blobs),
            }
            _atomic_pickle_dump(self.path, payload)

    def put(self, config, checkpoint, metadata, new_versions):
        with self._lock:
            result = super().put(config, checkpoint, metadata, new_versions)
            self._flush()
        return result

    def put_writes(self, config, writes, task_id, task_path=""):
        with self._lock:
            super().put_writes(config, writes, task_id, task_path)
            self._flush()

    def delete_thread(self, thread_id: str) -> None:
        with self._lock:
            super().delete_thread(thread_id)
            self._flush()

    async def aput(self, config, checkpoint, metadata, new_versions):
        with self._lock:
            result = await super().aput(config, checkpoint, metadata, new_versions)
            self._flush()
        return result

    async def aput_writes(self, config, writes, task_id, task_path=""):
        with self._lock:
            await super().aput_writes(config, writes, task_id, task_path)
            self._flush()

    async def adelete_thread(self, thread_id: str) -> None:
        with self._lock:
            await super().adelete_thread(thread_id)
            self._flush()


class PersistentInMemoryStore(InMemoryStore):
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self._lock = RLock()
        super().__init__()
        self._restore()

    def _restore(self) -> None:
        payload = _pickle_load(self.path)
        if not payload:
            return
        self._data = defaultdict(dict, {tuple(namespace): dict(items) for namespace, items in payload.get("data", {}).items()})
        self._vectors = defaultdict(
            lambda: defaultdict(dict),
            {
                tuple(namespace): defaultdict(dict, {key: dict(paths) for key, paths in values.items()})
                for namespace, values in payload.get("vectors", {}).items()
            },
        )

    def _flush(self) -> None:
        with self._lock:
            payload = {
                "data": {tuple(namespace): dict(items) for namespace, items in self._data.items()},
                "vectors": {
                    tuple(namespace): {key: dict(paths) for key, paths in values.items()}
                    for namespace, values in self._vectors.items()
                },
            }
            _atomic_pickle_dump(self.path, payload)

    def batch(self, ops):
        with self._lock:
            result = super().batch(ops)
            self._flush()
        return result

    async def abatch(self, ops):
        with self._lock:
            result = await super().abatch(ops)
            self._flush()
        return result
