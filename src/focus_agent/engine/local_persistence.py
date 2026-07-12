from __future__ import annotations

import hashlib
import hmac
import logging
import os
import pickle
import sqlite3
import threading
from collections import defaultdict
from pathlib import Path
from threading import RLock
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.base import PutOp
from langgraph.store.memory import InMemoryStore

from .local_persistence_store import PersistentSQLiteStore as PersistentSQLiteStore
from .local_persistence_store import (
    _flush_open_persistence_for_path,
    _focus_agent_checkpoint_serde,
    _register_persistence_instance,
)

logger = logging.getLogger("focus_agent.local_persistence")

_CHECKPOINT_HMAC_KEY_ENV = "FOCUS_AGENT_CHECKPOINT_HMAC_KEY"
_CHECKPOINT_VERIFY_SIGNATURE_ENV = "FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE"
_FALSE_ENV_VALUES = {"0", "false", "no", "off"}


def _checkpoint_signature_path(path: Path) -> Path:
    return path.with_name(path.name + ".sig")


def _checkpoint_verify_signature_enabled(value: bool | None = None) -> bool:
    if value is not None:
        return value
    return (
        os.environ.get(_CHECKPOINT_VERIFY_SIGNATURE_ENV, "true").strip().lower()
        not in _FALSE_ENV_VALUES
    )


def _checkpoint_hmac_key(value: str | bytes | None = None) -> bytes | None:
    if value is None:
        value = os.environ.get(_CHECKPOINT_HMAC_KEY_ENV)
    if not value:
        return None
    if isinstance(value, bytes):
        return value
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


def _write_checkpoint_signature(
    path: Path,
    data: bytes,
    *,
    hmac_key: str | bytes | None = None,
) -> None:
    sig_path = _checkpoint_signature_path(path)
    key = _checkpoint_hmac_key(hmac_key)
    if key is None:
        try:
            sig_path.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "failed to remove stale checkpoint signature: %s", sig_path, exc_info=True
            )
        return

    tmp_path = sig_path.with_name(sig_path.name + ".tmp")
    tmp_path.write_text(_checkpoint_hmac_digest(data, key) + "\n", encoding="utf-8")
    os.replace(tmp_path, sig_path)


def _checkpoint_signature_is_valid(
    path: Path,
    data: bytes,
    *,
    hmac_key: str | bytes | None = None,
) -> bool:
    failure = _checkpoint_signature_failure(path, data, hmac_key=hmac_key)
    if failure is None:
        return True
    logger.warning("refusing to load checkpoint pickle %s: %s", failure, path)
    return False


def _checkpoint_signature_failure(
    path: Path,
    data: bytes,
    *,
    hmac_key: str | bytes | None = None,
) -> str | None:
    sig_path = _checkpoint_signature_path(path)
    if not sig_path.exists():
        return f"without signature (missing HMAC signature file {sig_path})"
    if not _checkpoint_file_owner_matches(sig_path):
        return f"with owner mismatch (HMAC signature owner mismatch for {sig_path})"

    key = _checkpoint_hmac_key(hmac_key)
    if key is None:
        return f"without {_CHECKPOINT_HMAC_KEY_ENV}, required to verify the HMAC signature"

    try:
        actual = sig_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        return f"with unreadable HMAC signature file {sig_path}: {exc}"

    expected = _checkpoint_hmac_digest(data, key)
    if not hmac.compare_digest(actual, expected):
        return "with invalid signature (invalid HMAC signature)"
    return None


def _pickle_load_error(path: Path, reason: str) -> ValueError:
    return ValueError(f"Cannot load local pickle persistence at {path}: {reason}.")


def _atomic_pickle_dump(
    path: Path,
    payload: Any,
    *,
    hmac_key: str | bytes | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    data = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    with tmp_path.open("wb") as handle:
        handle.write(data)
    os.replace(tmp_path, path)
    _write_checkpoint_signature(path, data, hmac_key=hmac_key)


def _pickle_load(
    path: Path,
    *,
    hmac_key: str | bytes | None = None,
    verify_signature: bool | None = None,
    fail_on_invalid: bool = False,
) -> Any | None:
    if not path.exists():
        return None
    if not _checkpoint_file_owner_matches(path):
        if fail_on_invalid:
            raise _pickle_load_error(path, "pickle file owner mismatch")
        logger.warning("refusing to load checkpoint pickle with owner mismatch: %s", path)
        return None
    try:
        data = path.read_bytes()
    except OSError as exc:
        if fail_on_invalid:
            raise _pickle_load_error(path, f"pickle file is unreadable: {exc}") from exc
        raise
    if _checkpoint_verify_signature_enabled(verify_signature):
        if fail_on_invalid:
            failure = _checkpoint_signature_failure(path, data, hmac_key=hmac_key)
            if failure is not None:
                raise _pickle_load_error(path, failure)
        elif not _checkpoint_signature_is_valid(path, data, hmac_key=hmac_key):
            return None
    try:
        payload = pickle.loads(data)
    except Exception as exc:
        if fail_on_invalid:
            raise _pickle_load_error(path, "pickle payload is corrupt or incompatible") from exc
        raise
    if fail_on_invalid and not isinstance(payload, dict):
        raise _pickle_load_error(path, "pickle payload is corrupt or incompatible")
    return payload


def _checkpoint_incremental_enabled() -> bool:
    value = os.environ.get("FOCUS_AGENT_CHECKPOINT_INCREMENTAL", "true")
    return value.strip().lower() not in _FALSE_ENV_VALUES


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
    def __init__(
        self,
        path: str | Path,
        *,
        hmac_key: str | bytes | None = None,
        verify_signature: bool | None = None,
    ):
        self.path = Path(path).expanduser()
        self._hmac_key = hmac_key
        self._verify_signature = verify_signature
        _flush_open_persistence_for_path(self.path)
        self._lock = RLock()
        self._init_debounced_flush()
        super().__init__(serde=_focus_agent_checkpoint_serde())
        self._restore()
        _register_persistence_instance(self)

    def _restore(self) -> None:
        payload = _pickle_load(
            self.path,
            hmac_key=self._hmac_key,
            verify_signature=self._verify_signature,
            fail_on_invalid=True,
        )
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
            _atomic_pickle_dump(
                self.path,
                payload,
                hmac_key=self._hmac_key,
            )

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


class PersistentSQLiteSaver(InMemorySaver):
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        _flush_open_persistence_for_path(self.path)
        self._lock = RLock()
        super().__init__(serde=_focus_agent_checkpoint_serde())
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
                CREATE TABLE IF NOT EXISTS checkpoint_storage (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    checkpoint_type TEXT NOT NULL,
                    checkpoint BLOB NOT NULL,
                    metadata_type TEXT NOT NULL,
                    metadata BLOB NOT NULL,
                    parent_checkpoint_id TEXT,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                );

                CREATE TABLE IF NOT EXISTS checkpoint_blobs (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    version BLOB NOT NULL,
                    value_type TEXT NOT NULL,
                    value BLOB NOT NULL,
                    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
                );

                CREATE TABLE IF NOT EXISTS checkpoint_writes (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    write_idx INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    value_type TEXT NOT NULL,
                    value BLOB NOT NULL,
                    task_path TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx)
                );
                """
            )

    def _restore(self) -> None:
        storage = defaultdict(lambda: defaultdict(dict))
        writes = defaultdict(dict)
        blobs = {}
        for row in self._conn.execute(
            """
            SELECT thread_id, checkpoint_ns, checkpoint_id, checkpoint_type, checkpoint,
                   metadata_type, metadata, parent_checkpoint_id
            FROM checkpoint_storage
            """
        ):
            thread_id, checkpoint_ns, checkpoint_id = row[0], row[1], row[2]
            storage[thread_id][checkpoint_ns][checkpoint_id] = (
                (row[3], bytes(row[4])),
                (row[5], bytes(row[6])),
                row[7],
            )
        for row in self._conn.execute(
            """
            SELECT thread_id, checkpoint_ns, channel, version, value_type, value
            FROM checkpoint_blobs
            """
        ):
            version = pickle.loads(bytes(row[3]))
            blobs[(row[0], row[1], row[2], version)] = (row[4], bytes(row[5]))
        for row in self._conn.execute(
            """
            SELECT thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx,
                   channel, value_type, value, task_path
            FROM checkpoint_writes
            """
        ):
            outer_key = (row[0], row[1], row[2])
            inner_key = (row[3], int(row[4]))
            writes[outer_key][inner_key] = (row[3], row[5], (row[6], bytes(row[7])), row[8])
        self.storage = storage
        self.writes = writes
        self.blobs = blobs

    def put(self, config, checkpoint, metadata, new_versions):
        with self._lock:
            result = super().put(config, checkpoint, metadata, new_versions)
            thread_id = result["configurable"]["thread_id"]
            checkpoint_ns = result["configurable"].get("checkpoint_ns", "")
            checkpoint_id = result["configurable"]["checkpoint_id"]
            checkpoint_b, metadata_b, parent_checkpoint_id = self.storage[thread_id][checkpoint_ns][
                checkpoint_id
            ]
            rows = []
            for channel, version in new_versions.items():
                value_type, value = self.blobs[(thread_id, checkpoint_ns, channel, version)]
                rows.append(
                    (
                        thread_id,
                        checkpoint_ns,
                        channel,
                        sqlite3.Binary(pickle.dumps(version, protocol=pickle.HIGHEST_PROTOCOL)),
                        value_type,
                        sqlite3.Binary(value),
                    )
                )
            with self._conn:
                self._conn.executemany(
                    """
                    INSERT OR REPLACE INTO checkpoint_blobs (
                        thread_id, checkpoint_ns, channel, version, value_type, value
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO checkpoint_storage (
                        thread_id, checkpoint_ns, checkpoint_id, checkpoint_type, checkpoint,
                        metadata_type, metadata, parent_checkpoint_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        thread_id,
                        checkpoint_ns,
                        checkpoint_id,
                        checkpoint_b[0],
                        sqlite3.Binary(checkpoint_b[1]),
                        metadata_b[0],
                        sqlite3.Binary(metadata_b[1]),
                        parent_checkpoint_id,
                    ),
                )
        return result

    def put_writes(self, config, writes, task_id, task_path=""):
        with self._lock:
            super().put_writes(config, writes, task_id, task_path)
            configurable = config["configurable"]
            thread_id = configurable["thread_id"]
            checkpoint_ns = configurable.get("checkpoint_ns", "")
            checkpoint_id = configurable["checkpoint_id"]
            outer_key = (thread_id, checkpoint_ns, checkpoint_id)
            rows = [
                (
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                    write_task_id,
                    write_idx,
                    channel,
                    value[0],
                    sqlite3.Binary(value[1]),
                    write_task_path,
                )
                for (write_task_id, write_idx), (
                    _,
                    channel,
                    value,
                    write_task_path,
                ) in self.writes[outer_key].items()
            ]
            with self._conn:
                self._conn.executemany(
                    """
                    INSERT OR REPLACE INTO checkpoint_writes (
                        thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx,
                        channel, value_type, value, task_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )

    def delete_thread(self, thread_id: str) -> None:
        with self._lock:
            super().delete_thread(thread_id)
            with self._conn:
                self._conn.execute(
                    "DELETE FROM checkpoint_storage WHERE thread_id = ?", (thread_id,)
                )
                self._conn.execute("DELETE FROM checkpoint_blobs WHERE thread_id = ?", (thread_id,))
                self._conn.execute(
                    "DELETE FROM checkpoint_writes WHERE thread_id = ?", (thread_id,)
                )

    async def aput(self, config, checkpoint, metadata, new_versions):
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(self, config, writes, task_id, task_path=""):
        self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        self.delete_thread(thread_id)

    def close(self) -> None:
        with self._lock:
            conn = getattr(self, "_conn", None)
            if conn is not None:
                conn.close()
                self._conn = None


class PersistentInMemoryStore(_DebouncedFlushMixin, InMemoryStore):
    def __init__(
        self,
        path: str | Path,
        *,
        hmac_key: str | bytes | None = None,
        verify_signature: bool | None = None,
    ):
        self.path = Path(path).expanduser()
        self._hmac_key = hmac_key
        self._verify_signature = verify_signature
        _flush_open_persistence_for_path(self.path)
        self._lock = RLock()
        self._init_debounced_flush()
        super().__init__()
        self._restore()
        _register_persistence_instance(self)

    def _restore(self) -> None:
        payload = _pickle_load(
            self.path,
            hmac_key=self._hmac_key,
            verify_signature=self._verify_signature,
            fail_on_invalid=True,
        )
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
            _atomic_pickle_dump(
                self.path,
                payload,
                hmac_key=self._hmac_key,
            )

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
