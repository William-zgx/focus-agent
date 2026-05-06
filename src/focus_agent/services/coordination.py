from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import threading
import time
from typing import Any, Protocol
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
    durable = False

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

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "job_backend_durable": 0,
                "job_pending_total": len(self._keys),
            }


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


class PostgresBackgroundJobDeduperBackend:
    """Postgres-backed durable background job key coordination."""

    durable = True

    def __init__(self, database_uri: str, *, claim_ttl_seconds: float = 300.0, owner: str | None = None) -> None:
        self.database_uri = database_uri
        self.claim_ttl_seconds = max(float(claim_ttl_seconds or 0.0), 1.0)
        self.owner = owner or f"background:{uuid4().hex}"

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    def _claimed_until(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=self.claim_ttl_seconds)

    def try_claim_job_key(self, key: str) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_background_jobs (
                        job_key,
                        status,
                        attempt,
                        claimed_by,
                        claimed_until,
                        last_error,
                        created_at,
                        updated_at,
                        metadata
                    )
                    VALUES (%s, 'pending', 1, %s, %s, NULL, now(), now(), '{}'::jsonb)
                    ON CONFLICT (job_key) DO UPDATE SET
                        status = 'pending',
                        attempt = focus_background_jobs.attempt + 1,
                        claimed_by = EXCLUDED.claimed_by,
                        claimed_until = EXCLUDED.claimed_until,
                        last_error = NULL,
                        updated_at = now()
                    WHERE focus_background_jobs.status IN ('succeeded', 'failed', 'released')
                       OR focus_background_jobs.claimed_until <= now()
                    RETURNING attempt
                    """,
                    (str(key), self.owner, self._claimed_until()),
                )
                return cur.fetchone() is not None

    def mark_job_running(self, key: str) -> None:
        self._update_job(
            """
            UPDATE focus_background_jobs
            SET status = 'running',
                claimed_until = %s,
                updated_at = now()
            WHERE job_key = %s
              AND claimed_by = %s
              AND status = 'pending'
            """,
            (self._claimed_until(), str(key), self.owner),
        )

    def mark_job_succeeded(self, key: str) -> None:
        self._update_job(
            """
            UPDATE focus_background_jobs
            SET status = 'succeeded',
                claimed_by = NULL,
                claimed_until = NULL,
                last_error = NULL,
                updated_at = now()
            WHERE job_key = %s
              AND claimed_by = %s
              AND status = 'running'
            """,
            (str(key), self.owner),
        )

    def mark_job_failed(self, key: str, error: str) -> None:
        self._update_job(
            """
            UPDATE focus_background_jobs
            SET status = 'failed',
                claimed_by = NULL,
                claimed_until = NULL,
                last_error = %s,
                updated_at = now()
            WHERE job_key = %s
              AND claimed_by = %s
              AND status = 'running'
            """,
            (str(error)[:4000], str(key), self.owner),
        )

    def release_job_key(self, key: str) -> None:
        self._update_job(
            """
            UPDATE focus_background_jobs
            SET status = 'released',
                claimed_by = NULL,
                claimed_until = NULL,
                updated_at = now()
            WHERE job_key = %s
              AND status NOT IN ('succeeded', 'failed')
            """,
            (str(key),),
        )

    def snapshot(self) -> dict[str, int]:
        metrics = {
            "job_backend_durable": 1,
            "job_pending_total": 0,
            "job_running_total": 0,
            "job_succeeded_total": 0,
            "job_failed_total": 0,
            "job_released_total": 0,
            "job_attempt_total": 0,
        }
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, COUNT(*) AS count, COALESCE(SUM(attempt), 0) AS attempts
                    FROM focus_background_jobs
                    GROUP BY status
                    """
                )
                for row in cur.fetchall():
                    status = str(row.get("status") or "unknown").strip().lower()
                    count = int(row.get("count") or 0)
                    attempts = int(row.get("attempts") or 0)
                    metrics[f"job_{status}_total"] = count
                    metrics["job_attempt_total"] += attempts
        return metrics

    def _update_job(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)


def create_in_memory_coordination_backend() -> CoordinationBackend:
    return CoordinationBackend(
        thread_turns=InMemoryThreadTurnLockBackend(),
        job_deduper=InMemoryBackgroundJobDeduperBackend(),
        rate_limiter=InMemoryRateLimitBackend(),
    )


def create_coordination_backend(
    *,
    database_uri: str | None = None,
    background_job_backend: str = "memory",
    background_job_claim_ttl_seconds: float = 300.0,
) -> CoordinationBackend:
    in_memory = create_in_memory_coordination_backend()
    if not database_uri:
        return in_memory
    job_backend = in_memory.job_deduper
    if str(background_job_backend or "memory").strip().lower() == "postgres":
        job_backend = PostgresBackgroundJobDeduperBackend(
            database_uri,
            claim_ttl_seconds=background_job_claim_ttl_seconds,
        )
    return CoordinationBackend(
        thread_turns=PostgresThreadTurnLockBackend(database_uri),
        job_deduper=job_backend,
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
    "PostgresBackgroundJobDeduperBackend",
    "PostgresThreadTurnLockBackend",
    "RateLimitBackend",
    "ThreadTurnLease",
    "ThreadTurnLockBackend",
    "background_job_key",
    "create_coordination_backend",
    "create_in_memory_coordination_backend",
    "new_thread_turn_owner",
]
