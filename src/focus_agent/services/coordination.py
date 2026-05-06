from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import threading
import time
from typing import Any, Protocol
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..security.rate_limit import RateLimitResult


BACKGROUND_JOB_DEDUPE_POLICIES = frozenset({"skip", "replace"})


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
class BackgroundJobSpec:
    kind: str
    key: str
    payload: dict[str, Any] = field(default_factory=dict)
    run_at: datetime | None = None
    max_attempts: int = 1
    dedupe_policy: str = "skip"

    def __post_init__(self) -> None:
        kind = str(self.kind or "").strip()
        key = str(self.key or "").strip()
        if not kind:
            raise ValueError("background job kind is required")
        if not key:
            raise ValueError("background job key is required")
        dedupe_policy = str(self.dedupe_policy or "skip").strip().lower()
        if dedupe_policy not in BACKGROUND_JOB_DEDUPE_POLICIES:
            raise ValueError(f"unsupported background job dedupe policy: {dedupe_policy}")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "payload", dict(self.payload or {}))
        object.__setattr__(self, "run_at", _normalize_background_run_at(self.run_at))
        object.__setattr__(self, "max_attempts", max(1, int(self.max_attempts or 1)))
        object.__setattr__(self, "dedupe_policy", dedupe_policy)


@dataclass(frozen=True, slots=True)
class BackgroundJobClaim:
    claim_token: str
    owner: str
    attempt: int


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


@dataclass(slots=True)
class _MemoryBackgroundJob:
    spec: BackgroundJobSpec
    status: str
    attempt: int = 0
    claim: BackgroundJobClaim | None = None
    claimed_until: float = 0.0
    last_error: str | None = None


def _normalize_background_run_at(run_at: datetime | None) -> datetime:
    if run_at is None:
        return datetime.now(timezone.utc)
    if run_at.tzinfo is None:
        return run_at.replace(tzinfo=timezone.utc)
    return run_at.astimezone(timezone.utc)


def _background_job_kind_from_key(key: str) -> str:
    parts = str(key or "").split(":", 2)
    if len(parts) == 3 and parts[0] == "chat" and parts[1]:
        return parts[1]
    return "legacy"


def _background_payload_from_row(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, dict):
            return dict(decoded)
    return {}


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
        self._jobs: dict[str, _MemoryBackgroundJob] = {}
        self.owner = f"memory-background:{uuid4().hex}"

    def try_claim_job_key(self, key: str) -> bool:
        return self.claim_job_key(key) is not None

    def claim_job_key(self, key: str) -> BackgroundJobClaim | None:
        job_key = str(key or "background:anonymous")
        with self._lock:
            if job_key in self._keys:
                return None
            self._keys.add(job_key)
            return BackgroundJobClaim(
                claim_token=uuid4().hex,
                owner=self.owner,
                attempt=1,
            )

    def release_job_key(self, key: str) -> None:
        self.release_job_claim(
            str(key or "background:anonymous"),
            BackgroundJobClaim(claim_token="", owner=self.owner, attempt=0),
        )

    def release_job_claim(self, key: str, claim: BackgroundJobClaim) -> None:
        with self._lock:
            self._keys.discard(key)
            job = self._jobs.get(key)
            if job is not None and (claim.claim_token == "" or job.claim == claim):
                job.status = "released"
                job.claim = None
                job.claimed_until = 0.0

    def enqueue_job(self, spec: BackgroundJobSpec) -> bool:
        with self._lock:
            current = self._jobs.get(spec.key)
            if current is not None:
                if current.status in {"pending", "running"} and spec.dedupe_policy != "replace":
                    return False
                if current.status == "running" and spec.dedupe_policy == "replace":
                    return False
            self._jobs[spec.key] = _MemoryBackgroundJob(spec=spec, status="pending")
            return True

    def claim_next_job(
        self,
        *,
        allowed_kinds: tuple[str, ...] | list[str] | set[str],
        claim_ttl_seconds: float | None = None,
    ) -> tuple[BackgroundJobSpec, BackgroundJobClaim] | None:
        kinds = {str(kind) for kind in allowed_kinds if str(kind or "").strip()}
        if not kinds:
            return None
        now = time.monotonic()
        run_now = datetime.now(timezone.utc)
        ttl = max(float(claim_ttl_seconds or 300.0), 1.0)
        with self._lock:
            for key in sorted(self._jobs):
                job = self._jobs[key]
                if job.spec.kind not in kinds:
                    continue
                if job.status == "running" and job.claimed_until <= now and job.attempt >= job.spec.max_attempts:
                    job.status = "failed"
                    job.claim = None
                    job.claimed_until = 0.0
                    if job.last_error is None:
                        job.last_error = "claim expired after max attempts"
                    continue
                due_pending = job.status == "pending" and job.spec.run_at <= run_now
                expired_running = job.status == "running" and job.claimed_until <= now
                if not due_pending and not expired_running:
                    continue
                if job.attempt >= job.spec.max_attempts:
                    job.status = "failed"
                    if job.last_error is None:
                        job.last_error = "max attempts exhausted"
                    continue
                job.attempt += 1
                claim = BackgroundJobClaim(
                    claim_token=uuid4().hex,
                    owner=self.owner,
                    attempt=job.attempt,
                )
                job.status = "pending"
                job.claim = claim
                job.claimed_until = now + ttl
                return job.spec, claim
        return None

    def mark_job_claim_running(self, key: str, claim: BackgroundJobClaim) -> None:
        with self._lock:
            job = self._jobs.get(key)
            if job is not None and job.claim == claim and job.status == "pending":
                job.status = "running"

    def mark_job_claim_succeeded(self, key: str, claim: BackgroundJobClaim) -> None:
        with self._lock:
            job = self._jobs.get(key)
            if job is not None and job.claim == claim and job.status == "running":
                job.status = "succeeded"
                job.claim = None
                job.claimed_until = 0.0
                job.last_error = None

    def mark_job_claim_failed(self, key: str, claim: BackgroundJobClaim, error: str) -> None:
        with self._lock:
            job = self._jobs.get(key)
            if job is not None and job.claim == claim and job.status == "running":
                job.claim = None
                job.claimed_until = 0.0
                job.last_error = str(error)[:4000]
                job.status = "failed" if job.attempt >= job.spec.max_attempts else "pending"

    def mark_job_running(self, key: str) -> None:
        return None

    def mark_job_succeeded(self, key: str) -> None:
        with self._lock:
            self._keys.discard(key)

    def mark_job_failed(self, key: str, error: str) -> None:
        with self._lock:
            self._keys.discard(key)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            status_counts = {
                "job_pending_total": 0,
                "job_running_total": 0,
                "job_succeeded_total": 0,
                "job_failed_total": 0,
                "job_released_total": 0,
                "job_attempt_total": 0,
            }
            for job in self._jobs.values():
                status_key = f"job_{job.status}_total"
                status_counts[status_key] = status_counts.get(status_key, 0) + 1
                status_counts["job_attempt_total"] += job.attempt
            pending_total = len(self._keys) + status_counts["job_pending_total"]
            return {
                **status_counts,
                "job_backend_durable": 0,
                "job_pending_total": pending_total,
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
        self._legacy_claims: dict[str, BackgroundJobClaim] = {}
        self._legacy_claims_lock = threading.Lock()

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    def _claimed_until(self) -> datetime:
        return datetime.now(timezone.utc) + timedelta(seconds=self.claim_ttl_seconds)

    def try_claim_job_key(self, key: str) -> bool:
        return self.claim_job_key(key) is not None

    def claim_job_key(self, key: str) -> BackgroundJobClaim | None:
        job_key = str(key)
        claim_token = uuid4().hex
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_background_jobs (
                        job_key,
                        kind,
                        payload,
                        run_at,
                        max_attempts,
                        dedupe_policy,
                        status,
                        attempt,
                        claimed_by,
                        claimed_until,
                        claim_token,
                        last_error,
                        created_at,
                        updated_at,
                        metadata
                    )
                    VALUES (%s, %s, '{}'::jsonb, now(), 1, 'skip', 'pending', 1, %s, %s, %s, NULL, now(), now(), '{}'::jsonb)
                    ON CONFLICT (job_key) DO UPDATE SET
                        status = 'pending',
                        attempt = focus_background_jobs.attempt + 1,
                        claimed_by = EXCLUDED.claimed_by,
                        claimed_until = EXCLUDED.claimed_until,
                        claim_token = EXCLUDED.claim_token,
                        last_error = NULL,
                        updated_at = now()
                    WHERE focus_background_jobs.status IN ('succeeded', 'failed', 'released')
                       OR focus_background_jobs.claimed_until <= now()
                    RETURNING attempt, claim_token
                    """,
                    (
                        job_key,
                        _background_job_kind_from_key(job_key),
                        self.owner,
                        self._claimed_until(),
                        claim_token,
                    ),
                )
                row = cur.fetchone()
        if row is None:
            return None
        claim = BackgroundJobClaim(
            claim_token=str(row.get("claim_token") or claim_token),
            owner=self.owner,
            attempt=int(row.get("attempt") or 1),
        )
        with self._legacy_claims_lock:
            self._legacy_claims[job_key] = claim
        return claim

    def enqueue_job(self, spec: BackgroundJobSpec) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO focus_background_jobs (
                        job_key,
                        kind,
                        payload,
                        run_at,
                        max_attempts,
                        dedupe_policy,
                        status,
                        attempt,
                        claimed_by,
                        claimed_until,
                        claim_token,
                        last_error,
                        created_at,
                        updated_at,
                        metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'pending', 0, NULL, NULL, NULL, NULL, now(), now(), '{}'::jsonb)
                    ON CONFLICT (job_key) DO UPDATE SET
                        kind = EXCLUDED.kind,
                        payload = EXCLUDED.payload,
                        run_at = EXCLUDED.run_at,
                        max_attempts = EXCLUDED.max_attempts,
                        dedupe_policy = EXCLUDED.dedupe_policy,
                        status = 'pending',
                        attempt = 0,
                        claimed_by = NULL,
                        claimed_until = NULL,
                        claim_token = NULL,
                        last_error = NULL,
                        updated_at = now()
                    WHERE focus_background_jobs.status IN ('succeeded', 'failed', 'released')
                       OR (
                            EXCLUDED.dedupe_policy = 'replace'
                            AND focus_background_jobs.status != 'running'
                       )
                    RETURNING job_key
                    """,
                    (
                        spec.key,
                        spec.kind,
                        Jsonb(spec.payload),
                        spec.run_at,
                        spec.max_attempts,
                        spec.dedupe_policy,
                    ),
                )
                return cur.fetchone() is not None

    def claim_next_job(
        self,
        *,
        allowed_kinds: tuple[str, ...] | list[str] | set[str],
        claim_ttl_seconds: float | None = None,
    ) -> tuple[BackgroundJobSpec, BackgroundJobClaim] | None:
        kinds = tuple(str(kind).strip() for kind in allowed_kinds if str(kind or "").strip())
        if not kinds:
            return None
        claim_token = uuid4().hex
        claim_until = datetime.now(timezone.utc) + timedelta(
            seconds=max(float(claim_ttl_seconds or self.claim_ttl_seconds), 1.0)
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_background_jobs
                    SET status = 'failed',
                        claimed_by = NULL,
                        claimed_until = NULL,
                        claim_token = NULL,
                        last_error = COALESCE(last_error, 'claim expired after max attempts'),
                        updated_at = now()
                    WHERE status = 'running'
                      AND claimed_until <= now()
                      AND attempt >= max_attempts
                    """
                )
                cur.execute(
                    """
                    WITH next_job AS (
                        SELECT job_key
                        FROM focus_background_jobs
                        WHERE kind = ANY(%s)
                          AND (
                                (status = 'pending' AND run_at <= now())
                                OR (status = 'running' AND claimed_until <= now())
                          )
                          AND attempt < max_attempts
                        ORDER BY run_at ASC, updated_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE focus_background_jobs AS jobs
                    SET status = 'pending',
                        attempt = jobs.attempt + 1,
                        claimed_by = %s,
                        claimed_until = %s,
                        claim_token = %s,
                        last_error = NULL,
                        updated_at = now()
                    FROM next_job
                    WHERE jobs.job_key = next_job.job_key
                    RETURNING
                        jobs.job_key,
                        jobs.kind,
                        jobs.payload,
                        jobs.run_at,
                        jobs.max_attempts,
                        jobs.dedupe_policy,
                        jobs.attempt,
                        jobs.claim_token
                    """,
                    (list(kinds), self.owner, claim_until, claim_token),
                )
                row = cur.fetchone()
        if row is None:
            return None
        spec = BackgroundJobSpec(
            kind=str(row.get("kind") or ""),
            key=str(row.get("job_key") or ""),
            payload=_background_payload_from_row(row.get("payload")),
            run_at=row.get("run_at"),
            max_attempts=int(row.get("max_attempts") or 1),
            dedupe_policy=str(row.get("dedupe_policy") or "skip"),
        )
        claim = BackgroundJobClaim(
            claim_token=str(row.get("claim_token") or claim_token),
            owner=self.owner,
            attempt=int(row.get("attempt") or 1),
        )
        return spec, claim

    def mark_job_running(self, key: str) -> None:
        claim = self._legacy_claim_for_key(key)
        if claim is None:
            return
        self.mark_job_claim_running(key, claim)

    def mark_job_claim_running(self, key: str, claim: BackgroundJobClaim) -> None:
        self._update_job(
            """
            UPDATE focus_background_jobs
            SET status = 'running',
                claimed_until = %s,
                updated_at = now()
            WHERE job_key = %s
              AND claimed_by = %s
              AND claim_token = %s
              AND status = 'pending'
            """,
            (self._claimed_until(), str(key), claim.owner, claim.claim_token),
        )

    def mark_job_succeeded(self, key: str) -> None:
        claim = self._legacy_claim_for_key(key)
        if claim is None:
            return
        self.mark_job_claim_succeeded(key, claim)

    def mark_job_claim_succeeded(self, key: str, claim: BackgroundJobClaim) -> None:
        self._update_job(
            """
            UPDATE focus_background_jobs
            SET status = 'succeeded',
                claimed_by = NULL,
                claimed_until = NULL,
                claim_token = NULL,
                last_error = NULL,
                updated_at = now()
            WHERE job_key = %s
              AND claimed_by = %s
              AND claim_token = %s
              AND status = 'running'
            """,
            (str(key), claim.owner, claim.claim_token),
        )
        self._clear_legacy_claim(key, claim)

    def mark_job_failed(self, key: str, error: str) -> None:
        claim = self._legacy_claim_for_key(key)
        if claim is None:
            return
        self.mark_job_claim_failed(key, claim, error)

    def mark_job_claim_failed(self, key: str, claim: BackgroundJobClaim, error: str) -> None:
        self._update_job(
            """
            UPDATE focus_background_jobs
            SET status = CASE
                    WHEN attempt >= max_attempts THEN 'failed'
                    ELSE 'pending'
                END,
                claimed_by = NULL,
                claimed_until = NULL,
                claim_token = NULL,
                last_error = %s,
                updated_at = now()
            WHERE job_key = %s
              AND claimed_by = %s
              AND claim_token = %s
              AND status = 'running'
            """,
            (str(error)[:4000], str(key), claim.owner, claim.claim_token),
        )
        self._clear_legacy_claim(key, claim)

    def release_job_key(self, key: str) -> None:
        claim = self._legacy_claim_for_key(key)
        if claim is None:
            return
        self.release_job_claim(key, claim)

    def release_job_claim(self, key: str, claim: BackgroundJobClaim) -> None:
        self._update_job(
            """
            UPDATE focus_background_jobs
            SET status = 'released',
                claimed_by = NULL,
                claimed_until = NULL,
                claim_token = NULL,
                updated_at = now()
            WHERE job_key = %s
              AND claimed_by = %s
              AND claim_token = %s
              AND status NOT IN ('succeeded', 'failed')
            """,
            (str(key), claim.owner, claim.claim_token),
        )
        self._clear_legacy_claim(key, claim)

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

    def _legacy_claim_for_key(self, key: str) -> BackgroundJobClaim | None:
        with self._legacy_claims_lock:
            return self._legacy_claims.get(str(key))

    def _clear_legacy_claim(self, key: str, claim: BackgroundJobClaim) -> None:
        with self._legacy_claims_lock:
            current = self._legacy_claims.get(str(key))
            if current == claim:
                self._legacy_claims.pop(str(key), None)


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
    "BACKGROUND_JOB_DEDUPE_POLICIES",
    "BackgroundJobDeduperBackend",
    "BackgroundJobClaim",
    "BackgroundJobSpec",
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
