from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import threading
import time
from typing import Protocol
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from ..security.rate_limit import RateLimitResult


class ThreadTurnLockBackend(Protocol):
    def acquire_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
        ...

    def heartbeat_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
        ...

    def release_thread_turn(self, *, thread_id: str, owner: str) -> None:
        ...


class BackgroundJobDeduperBackend(Protocol):
    def try_claim_job_key(self, key: str) -> bool:
        ...

    def release_job_key(self, key: str) -> None:
        ...


class RateLimitBackend(Protocol):
    def check(self, *, key: str, limit: int, window_seconds: float = 60.0) -> RateLimitResult:
        ...


@dataclass(frozen=True, slots=True)
class CoordinationBackend:
    thread_turns: ThreadTurnLockBackend
    job_deduper: BackgroundJobDeduperBackend
    rate_limiter: RateLimitBackend


@dataclass(frozen=True, slots=True)
class ThreadTurnLease:
    thread_id: str
    owner: str


@dataclass(slots=True)
class _MemoryThreadTurnLock:
    owner: str
    expires_at: float


class InMemoryThreadTurnLockBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._locks: dict[str, _MemoryThreadTurnLock] = {}

    def acquire_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
        now = time.monotonic()
        expires_at = now + max(float(ttl_seconds or 0.0), 0.001)
        with self._lock:
            current = self._locks.get(thread_id)
            if current is not None and current.expires_at > now and current.owner != owner:
                return False
            self._locks[thread_id] = _MemoryThreadTurnLock(owner=owner, expires_at=expires_at)
            return True

    def heartbeat_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
        now = time.monotonic()
        expires_at = now + max(float(ttl_seconds or 0.0), 0.001)
        with self._lock:
            current = self._locks.get(thread_id)
            if current is None or current.owner != owner or current.expires_at <= now:
                return False
            current.expires_at = expires_at
            return True

    def release_thread_turn(self, *, thread_id: str, owner: str) -> None:
        with self._lock:
            current = self._locks.get(thread_id)
            if current is not None and current.owner == owner:
                self._locks.pop(thread_id, None)


class InMemoryBackgroundJobDeduperBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keys: set[str] = set()

    def try_claim_job_key(self, key: str) -> bool:
        with self._lock:
            if key in self._keys:
                return False
            self._keys.add(key)
            return True

    def release_job_key(self, key: str) -> None:
        with self._lock:
            self._keys.discard(key)


class InMemoryRateLimitBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, list[float]] = {}

    def check(self, *, key: str, limit: int, window_seconds: float = 60.0) -> RateLimitResult:
        if limit <= 0:
            return RateLimitResult(allowed=True, remaining=0, retry_after_seconds=0.0)
        now = time.monotonic()
        horizon = now - max(float(window_seconds or 0.0), 0.001)
        with self._lock:
            events = [item for item in self._events.get(key, []) if item > horizon]
            if len(events) >= limit:
                self._events[key] = events
                retry_after = max(0.0, events[0] + window_seconds - now)
                return RateLimitResult(allowed=False, remaining=0, retry_after_seconds=retry_after)
            events.append(now)
            self._events[key] = events
            return RateLimitResult(
                allowed=True,
                remaining=max(0, limit - len(events)),
                retry_after_seconds=0.0,
            )


class PostgresThreadTurnLockBackend:
    """Postgres-backed thread turn locks with owner heartbeat and TTL expiry."""

    def __init__(self, database_uri: str) -> None:
        self.database_uri = database_uri

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    @staticmethod
    def _lock_key(thread_id: str) -> str:
        return f"thread_turn:{thread_id}"

    @staticmethod
    def _expires_at(ttl_seconds: float) -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=max(float(ttl_seconds or 0.0), 0.001))

    def acquire_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_runtime_locks (
                        lock_key,
                        lock_type,
                        owner,
                        acquired_at,
                        heartbeat_at,
                        expires_at,
                        metadata
                    )
                    VALUES (%s, 'thread_turn', %s, now(), now(), %s, '{}'::jsonb)
                    ON CONFLICT (lock_key) DO UPDATE SET
                        owner = EXCLUDED.owner,
                        lock_type = EXCLUDED.lock_type,
                        acquired_at = now(),
                        heartbeat_at = now(),
                        expires_at = EXCLUDED.expires_at,
                        metadata = EXCLUDED.metadata
                    WHERE focus_runtime_locks.owner = EXCLUDED.owner
                       OR focus_runtime_locks.expires_at <= now()
                    RETURNING owner
                    """,
                    (self._lock_key(thread_id), owner, self._expires_at(ttl_seconds)),
                )
                return cur.fetchone() is not None

    def heartbeat_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_runtime_locks
                    SET heartbeat_at = now(), expires_at = %s
                    WHERE lock_key = %s
                      AND lock_type = 'thread_turn'
                      AND owner = %s
                      AND expires_at > now()
                    RETURNING owner
                    """,
                    (self._expires_at(ttl_seconds), self._lock_key(thread_id), owner),
                )
                return cur.fetchone() is not None

    def release_thread_turn(self, *, thread_id: str, owner: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM focus_runtime_locks
                    WHERE lock_key = %s
                      AND lock_type = 'thread_turn'
                      AND owner = %s
                    """,
                    (self._lock_key(thread_id), owner),
                )


def create_in_memory_coordination_backend() -> CoordinationBackend:
    return CoordinationBackend(
        thread_turns=InMemoryThreadTurnLockBackend(),
        job_deduper=InMemoryBackgroundJobDeduperBackend(),
        rate_limiter=InMemoryRateLimitBackend(),
    )


def create_coordination_backend(*, database_uri: str | None = None) -> CoordinationBackend:
    in_memory = create_in_memory_coordination_backend()
    if not database_uri:
        return in_memory
    return CoordinationBackend(
        thread_turns=PostgresThreadTurnLockBackend(database_uri),
        job_deduper=in_memory.job_deduper,
        rate_limiter=in_memory.rate_limiter,
    )


def new_thread_turn_owner() -> str:
    return uuid4().hex


def background_job_key(*, kind: str, thread_id: str) -> str:
    return f"chat:{kind}:{thread_id}"


__all__ = [
    "BackgroundJobDeduperBackend",
    "CoordinationBackend",
    "InMemoryBackgroundJobDeduperBackend",
    "InMemoryRateLimitBackend",
    "InMemoryThreadTurnLockBackend",
    "PostgresThreadTurnLockBackend",
    "RateLimitBackend",
    "ThreadTurnLease",
    "ThreadTurnLockBackend",
    "background_job_key",
    "create_coordination_backend",
    "create_in_memory_coordination_backend",
    "new_thread_turn_owner",
]
