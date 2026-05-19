from __future__ import annotations

import atexit
import hashlib
import hmac
import logging
import os
import pickle
import threading
import weakref
from collections import defaultdict
from pathlib import Path
from threading import RLock
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.store.base import PutOp
from langgraph.store.memory import InMemoryStore

logger = logging.getLogger("focus_agent.local_persistence")

_CHECKPOINT_HMAC_KEY_ENV = "FOCUS_AGENT_CHECKPOINT_HMAC_KEY"
_CHECKPOINT_VERIFY_SIGNATURE_ENV = "FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE"
_FALSE_ENV_VALUES = {"0", "false", "no", "off"}
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


def _checkpoint_signature_path(path: Path) -> Path:
    return path.with_name(path.name + ".sig")


def _checkpoint_verify_signature_enabled() -> bool:
    return (
        os.environ.get(_CHECKPOINT_VERIFY_SIGNATURE_ENV, "true").strip().lower()
        not in _FALSE_ENV_VALUES
    )


def _checkpoint_hmac_key() -> bytes | None:
    value = os.environ.get(_CHECKPOINT_HMAC_KEY_ENV)
    if not value:
        return None
    return value.encode("utf-8")


def _checkpoint_hmac_digest(data: bytes, key: bytes) -> str:
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def _checkpoint_file_owner_matches(path: Path) -> bool:
    getuid = getattr(os, "getuid", None)
    if getuid is None:
        return True
    try:
        return path.stat().st_uid == getuid()
    except OSError:
        return False


def _write_checkpoint_signature(path: Path, data: bytes) -> None:
    sig_path = _checkpoint_signature_path(path)
    key = _checkpoint_hmac_key()
    if key is None:
        try:
            sig_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("failed to remove stale checkpoint signature: %s", sig_path, exc_info=True)
        return

    tmp_path = sig_path.with_name(sig_path.name + ".tmp")
    tmp_path.write_text(_checkpoint_hmac_digest(data, key) + "\n", encoding="utf-8")
    os.replace(tmp_path, sig_path)


def _checkpoint_signature_is_valid(path: Path, data: bytes) -> bool:
    sig_path = _checkpoint_signature_path(path)
    if not sig_path.exists():
        logger.warning("refusing to load checkpoint pickle without signature: %s", path)
        return False
    if not _checkpoint_file_owner_matches(sig_path):
        logger.warning("refusing to load checkpoint signature with owner mismatch: %s", sig_path)
        return False

    key = _checkpoint_hmac_key()
    if key is None:
        logger.warning(
            "refusing to load checkpoint pickle without %s: %s",
            _CHECKPOINT_HMAC_KEY_ENV,
            path,
        )
        return False

    try:
        actual = sig_path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning("refusing to load unreadable checkpoint signature: %s", sig_path)
        return False

    expected = _checkpoint_hmac_digest(data, key)
    if not hmac.compare_digest(actual, expected):
        logger.warning("refusing to load checkpoint pickle with invalid signature: %s", path)
        return False
    return True


def _atomic_pickle_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    data = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    with tmp_path.open("wb") as handle:
        handle.write(data)
    os.replace(tmp_path, path)
    _write_checkpoint_signature(path, data)


def _pickle_load(path: Path) -> Any | None:
    if not path.exists():
        return None
    if not _checkpoint_file_owner_matches(path):
        logger.warning("refusing to load checkpoint pickle with owner mismatch: %s", path)
        return None
    data = path.read_bytes()
    if _checkpoint_verify_signature_enabled() and not _checkpoint_signature_is_valid(path, data):
        return None
    return pickle.loads(data)


_PERSISTENCE_REGISTRY_LOCK = RLock()
_PERSISTENCE_INSTANCES: weakref.WeakSet[Any] = weakref.WeakSet()


def _checkpoint_incremental_enabled() -> bool:
    value = os.environ.get("FOCUS_AGENT_CHECKPOINT_INCREMENTAL", "true")
    return value.strip().lower() not in _FALSE_ENV_VALUES


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


class _DebouncedFlushMixin:
    _flush_interval_ms: int
    _flush_timer: threading.Timer | None
    _dirty: bool

    def _init_debounced_flush(self) -> None:
        self._dirty = False
        self._flush_timer = None
        self._flush_interval_ms = 100
        self._incremental_flush_enabled = _checkpoint_incremental_enabled()

    def _mark_dirty(self) -> None:
        with self._lock:
            self._dirty = True
            if not self._incremental_flush_enabled:
                self._flush()
                self._dirty = False
                return
            if self._flush_timer is not None:
                return
            timer = threading.Timer(self._flush_interval_ms / 1000, self._flush_dirty)
            timer.daemon = True
            self._flush_timer = timer
            timer.start()

    def _flush_dirty(self) -> None:
        with self._lock:
            self._flush_timer = None
            if self._dirty:
                self._flush()
                self._dirty = False

    def _flush_dirty_now(self) -> None:
        with self._lock:
            self._dirty = True
            self._cancel_flush_timer()
            self._flush()
            self._dirty = False

    def _cancel_flush_timer(self) -> None:
        timer = self._flush_timer
        self._flush_timer = None
        if timer is not None:
            timer.cancel()

    def close(self) -> None:
        with self._lock:
            self._cancel_flush_timer()
            if self._dirty:
                self._flush()
                self._dirty = False


class PersistentInMemorySaver(_DebouncedFlushMixin, InMemorySaver):
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        _flush_open_persistence_for_path(self.path)
        self._lock = RLock()
        self._init_debounced_flush()
        super().__init__(serde=_focus_agent_checkpoint_serde())
        self._restore()
        _register_persistence_instance(self)

    def _restore(self) -> None:
        payload = _pickle_load(self.path)
        if not payload:
            return
        storage = defaultdict(lambda: defaultdict(dict))
        for thread_id, namespaces in payload.get("storage", {}).items():
            storage[thread_id] = defaultdict(
                dict, {ns: dict(checkpoints) for ns, checkpoints in namespaces.items()}
            )
        self.storage = storage
        self.writes = defaultdict(
            dict, {tuple(key): dict(value) for key, value in payload.get("writes", {}).items()}
        )
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
            self._mark_dirty()
        return result

    def put_writes(self, config, writes, task_id, task_path=""):
        with self._lock:
            super().put_writes(config, writes, task_id, task_path)
            self._mark_dirty()

    def delete_thread(self, thread_id: str) -> None:
        with self._lock:
            super().delete_thread(thread_id)
            self._flush_dirty_now()

    async def aput(self, config, checkpoint, metadata, new_versions):
        with self._lock:
            result = super().put(config, checkpoint, metadata, new_versions)
            self._mark_dirty()
        return result

    async def aput_writes(self, config, writes, task_id, task_path=""):
        with self._lock:
            super().put_writes(config, writes, task_id, task_path)
            self._mark_dirty()

    async def adelete_thread(self, thread_id: str) -> None:
        with self._lock:
            super().delete_thread(thread_id)
            self._flush_dirty_now()


class PersistentInMemoryStore(_DebouncedFlushMixin, InMemoryStore):
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        _flush_open_persistence_for_path(self.path)
        self._lock = RLock()
        self._init_debounced_flush()
        super().__init__()
        self._restore()
        _register_persistence_instance(self)

    def _restore(self) -> None:
        payload = _pickle_load(self.path)
        if not payload:
            return
        self._data = defaultdict(
            dict,
            {tuple(namespace): dict(items) for namespace, items in payload.get("data", {}).items()},
        )
        self._vectors = defaultdict(
            lambda: defaultdict(dict),
            {
                tuple(namespace): defaultdict(
                    dict, {key: dict(paths) for key, paths in values.items()}
                )
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
        ops = list(ops)
        with self._lock:
            result = super().batch(ops)
            if any(isinstance(op, PutOp) for op in ops):
                self._mark_dirty()
        return result

    async def abatch(self, ops):
        ops = list(ops)
        with self._lock:
            result = await super().abatch(ops)
            if any(isinstance(op, PutOp) for op in ops):
                self._mark_dirty()
        return result
