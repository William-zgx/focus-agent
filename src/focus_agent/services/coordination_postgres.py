from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..security.rate_limit import RateLimitResult
from .coordination_models import (
    BackgroundJobClaim,
    BackgroundJobSpec,
    _background_job_kind_from_key,
    _background_payload_from_row,
    _datetime_json,
)


class PostgresRateLimitBackend:
    """Postgres-backed fixed-window rate limit buckets shared across workers."""

    def __init__(self, database_uri: str) -> None:
        self.database_uri = database_uri

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    def check(self, *, key: str, limit: int, window_seconds: float = 60.0) -> RateLimitResult:
        if limit <= 0:
            return RateLimitResult(allowed=True, remaining=0, retry_after_seconds=0.0)
        window = max(float(window_seconds or 0.0), 0.001)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH upsert AS (
                        INSERT INTO focus_rate_limit_buckets (
                            bucket_key,
                            token_count,
                            window_start,
                            updated_at
                        )
                        VALUES (%s, 1, now(), now())
                        ON CONFLICT (bucket_key) DO UPDATE SET
                            token_count = CASE
                                WHEN focus_rate_limit_buckets.window_start <= now() - (%s * interval '1 second')
                                    THEN 1
                                WHEN focus_rate_limit_buckets.token_count < %s
                                    THEN focus_rate_limit_buckets.token_count + 1
                                ELSE focus_rate_limit_buckets.token_count
                            END,
                            window_start = CASE
                                WHEN focus_rate_limit_buckets.window_start <= now() - (%s * interval '1 second')
                                    THEN now()
                                ELSE focus_rate_limit_buckets.window_start
                            END,
                            updated_at = now()
                        RETURNING
                            token_count,
                            EXTRACT(EPOCH FROM (
                                window_start + (%s * interval '1 second') - now()
                            )) AS retry_after_seconds
                    )
                    SELECT token_count, retry_after_seconds FROM upsert
                    """,
                    (key, window, limit, window, window),
                )
                row = cur.fetchone() or {}
        token_count = int(row.get("token_count") or 0)
        allowed = token_count <= limit
        retry_after = 0.0 if allowed else max(0.0, float(row.get("retry_after_seconds") or 0.0))
        return RateLimitResult(
            allowed=allowed,
            remaining=max(0, limit - token_count) if allowed else 0,
            retry_after_seconds=retry_after,
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
        return datetime.now(UTC) + timedelta(seconds=max(float(ttl_seconds or 0.0), 0.001))

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

    def __init__(
        self,
        database_uri: str,
        *,
        claim_ttl_seconds: float = 300.0,
        retry_base_delay_seconds: float = 5.0,
        retry_max_delay_seconds: float = 300.0,
        owner: str | None = None,
    ) -> None:
        self.database_uri = database_uri
        self.claim_ttl_seconds = max(float(claim_ttl_seconds or 0.0), 1.0)
        self.retry_base_delay_seconds = max(float(retry_base_delay_seconds or 0.0), 0.0)
        self.retry_max_delay_seconds = max(
            float(retry_max_delay_seconds or 0.0), self.retry_base_delay_seconds
        )
        self.owner = owner or f"background:{uuid4().hex}"
        self._legacy_claims: dict[str, BackgroundJobClaim] = {}
        self._legacy_claims_lock = threading.Lock()

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    @staticmethod
    def _claimed_until_after(ttl_seconds: float) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=max(float(ttl_seconds or 0.0), 0.001))

    def _claimed_until(self) -> datetime:
        return self._claimed_until_after(self.claim_ttl_seconds)

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
                        last_heartbeat_at,
                        last_failed_at,
                        dead_lettered_at,
                        idempotency_key,
                        created_at,
                        updated_at,
                        metadata
                    )
                    VALUES (%s, %s, '{}'::jsonb, now(), 1, 'skip', 'pending', 1, %s, %s, %s, NULL, now(), NULL, NULL, %s, now(), now(), '{}'::jsonb)
                    ON CONFLICT (job_key) DO UPDATE SET
                        status = 'pending',
                        attempt = focus_background_jobs.attempt + 1,
                        claimed_by = EXCLUDED.claimed_by,
                        claimed_until = EXCLUDED.claimed_until,
                        claim_token = EXCLUDED.claim_token,
                        last_error = NULL,
                        last_heartbeat_at = now(),
                        last_failed_at = NULL,
                        dead_lettered_at = NULL,
                        updated_at = now()
                    WHERE focus_background_jobs.status IN ('succeeded', 'failed', 'released', 'dead_lettered')
                       OR focus_background_jobs.claimed_until <= now()
                    RETURNING attempt, claim_token
                    """,
                    (
                        job_key,
                        _background_job_kind_from_key(job_key),
                        self.owner,
                        self._claimed_until(),
                        claim_token,
                        job_key,
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
                        last_heartbeat_at,
                        last_failed_at,
                        dead_lettered_at,
                        idempotency_key,
                        created_at,
                        updated_at,
                        metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'pending', 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, %s, now(), now(), '{}'::jsonb)
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
                        last_heartbeat_at = NULL,
                        last_failed_at = NULL,
                        dead_lettered_at = NULL,
                        idempotency_key = COALESCE(EXCLUDED.idempotency_key, focus_background_jobs.idempotency_key),
                        updated_at = now()
                    WHERE focus_background_jobs.status IN ('succeeded', 'failed', 'released', 'dead_lettered')
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
                        spec.idempotency_key,
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
        claim_until = datetime.now(UTC) + timedelta(
            seconds=max(float(claim_ttl_seconds or self.claim_ttl_seconds), 1.0)
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_background_jobs
                    SET status = CASE
                            WHEN attempt >= max_attempts THEN 'dead_lettered'
                            ELSE 'retrying'
                        END,
                        run_at = CASE
                            WHEN attempt >= max_attempts THEN run_at
                            ELSE now() + make_interval(secs => LEAST(%s, %s * POWER(2, GREATEST(attempt - 1, 0))))
                        END,
                        claimed_by = NULL,
                        claimed_until = NULL,
                        claim_token = NULL,
                        last_error = CASE
                            WHEN attempt >= max_attempts THEN COALESCE(last_error, 'claim expired after max attempts')
                            ELSE 'claim expired before completion'
                        END,
                        last_failed_at = now(),
                        dead_lettered_at = CASE
                            WHEN attempt >= max_attempts THEN COALESCE(dead_lettered_at, now())
                            ELSE NULL
                        END,
                        updated_at = now()
                    WHERE status = 'running'
                      AND claimed_until <= now()
                    """,
                    (self.retry_max_delay_seconds, self.retry_base_delay_seconds),
                )
                cur.execute(
                    """
                    WITH next_job AS (
                        SELECT job_key
                        FROM focus_background_jobs
                        WHERE kind = ANY(%s)
                          AND (
                                (
                                    status IN ('pending', 'retrying')
                                    AND run_at <= now()
                                    AND (claim_token IS NULL OR claimed_until IS NULL OR claimed_until <= now())
                                )
                                OR (status = 'running' AND claimed_until <= now())
                          )
                          AND attempt < max_attempts
                        ORDER BY run_at ASC, updated_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE focus_background_jobs AS jobs
                    SET status = 'running',
                        attempt = jobs.attempt + 1,
                        claimed_by = %s,
                        claimed_until = %s,
                        claim_token = %s,
                        last_error = NULL,
                        last_heartbeat_at = now(),
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
                        jobs.idempotency_key,
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
            idempotency_key=str(row.get("idempotency_key") or row.get("job_key") or ""),
        )
        claim = BackgroundJobClaim(
            claim_token=str(row.get("claim_token") or claim_token),
            owner=self.owner,
            attempt=int(row.get("attempt") or 1),
        )
        return spec, claim

    def heartbeat_job_claim(self, key: str, claim: BackgroundJobClaim, ttl_seconds: float) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_background_jobs
                    SET claimed_until = %s,
                        last_heartbeat_at = now(),
                        updated_at = now()
                    WHERE job_key = %s
                      AND claimed_by = %s
                      AND claim_token = %s
                      AND status = 'running'
                      AND claimed_until > now()
                    RETURNING job_key
                    """,
                    (
                        self._claimed_until_after(ttl_seconds),
                        str(key),
                        claim.owner,
                        claim.claim_token,
                    ),
                )
                return cur.fetchone() is not None

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
                last_heartbeat_at = now(),
                updated_at = now()
            WHERE job_key = %s
              AND claimed_by = %s
              AND claim_token = %s
              AND status IN ('pending', 'running')
              AND claimed_until > now()
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
              AND claimed_until > now()
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
                    WHEN attempt >= max_attempts THEN 'dead_lettered'
                    ELSE 'retrying'
                END,
                run_at = CASE
                    WHEN attempt >= max_attempts THEN run_at
                    ELSE now() + make_interval(secs => LEAST(%s, %s * POWER(2, GREATEST(attempt - 1, 0))))
                END,
                claimed_by = NULL,
                claimed_until = NULL,
                claim_token = NULL,
                last_error = %s,
                last_failed_at = now(),
                dead_lettered_at = CASE
                    WHEN attempt >= max_attempts THEN COALESCE(dead_lettered_at, now())
                    ELSE NULL
                END,
                updated_at = now()
            WHERE job_key = %s
              AND claimed_by = %s
              AND claim_token = %s
              AND status = 'running'
            """,
            (
                self.retry_max_delay_seconds,
                self.retry_base_delay_seconds,
                str(error)[:4000],
                str(key),
                claim.owner,
                claim.claim_token,
            ),
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
              AND status NOT IN ('succeeded', 'failed', 'dead_lettered')
              AND claimed_until > now()
            """,
            (str(key), claim.owner, claim.claim_token),
        )
        self._clear_legacy_claim(key, claim)

    def snapshot(self) -> dict[str, int]:
        metrics = {
            "job_backend_durable": 1,
            "job_pending_total": 0,
            "job_retrying_total": 0,
            "job_running_total": 0,
            "job_succeeded_total": 0,
            "job_failed_total": 0,
            "job_released_total": 0,
            "job_dead_lettered_total": 0,
            "job_attempt_total": 0,
            "job_oldest_pending_seconds": 0,
            "job_oldest_retry_seconds": 0,
            "job_oldest_dead_lettered_seconds": 0,
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
                cur.execute(
                    """
                    WITH oldest AS (
                        SELECT
                            MIN(created_at) FILTER (WHERE status = 'pending') AS pending_at,
                            MIN(COALESCE(last_failed_at, updated_at)) FILTER (WHERE status = 'retrying') AS retry_at,
                            MIN(COALESCE(dead_lettered_at, updated_at)) FILTER (WHERE status = 'dead_lettered') AS dead_lettered_at
                        FROM focus_background_jobs
                    )
                    SELECT
                        COALESCE(EXTRACT(EPOCH FROM (now() - pending_at)), 0) AS oldest_pending_seconds,
                        COALESCE(EXTRACT(EPOCH FROM (now() - retry_at)), 0) AS oldest_retry_seconds,
                        COALESCE(EXTRACT(EPOCH FROM (now() - dead_lettered_at)), 0) AS oldest_dead_lettered_seconds
                    FROM oldest
                    """
                )
                row = cur.fetchone() or {}
                metrics["job_oldest_pending_seconds"] = int(
                    float(row.get("oldest_pending_seconds") or 0)
                )
                metrics["job_oldest_retry_seconds"] = int(
                    float(row.get("oldest_retry_seconds") or 0)
                )
                metrics["job_oldest_dead_lettered_seconds"] = int(
                    float(row.get("oldest_dead_lettered_seconds") or 0)
                )
        return metrics

    def list_dead_letter_jobs(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        limit = max(0, min(int(limit), 200))
        offset = max(0, int(offset))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS count FROM focus_background_jobs WHERE status = 'dead_lettered'"
                )
                count_row = cur.fetchone() or {}
                cur.execute(
                    """
                    SELECT
                        job_key,
                        kind,
                        payload,
                        status,
                        attempt,
                        max_attempts,
                        dedupe_policy,
                        idempotency_key,
                        last_error,
                        dead_lettered_at
                    FROM focus_background_jobs
                    WHERE status = 'dead_lettered'
                    ORDER BY dead_lettered_at DESC NULLS LAST, updated_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (limit, offset),
                )
                rows = cur.fetchall()
        return {
            "items": [
                {
                    "job_key": str(row.get("job_key") or ""),
                    "kind": str(row.get("kind") or ""),
                    "payload": _background_payload_from_row(row.get("payload")),
                    "status": str(row.get("status") or "dead_lettered"),
                    "attempt": int(row.get("attempt") or 0),
                    "max_attempts": int(row.get("max_attempts") or 1),
                    "dedupe_policy": str(row.get("dedupe_policy") or "skip"),
                    "idempotency_key": row.get("idempotency_key"),
                    "last_error": row.get("last_error"),
                    "dead_lettered_at": _datetime_json(row.get("dead_lettered_at")),
                }
                for row in rows
            ],
            "count": int(count_row.get("count") or 0),
            "limit": limit,
            "offset": offset,
        }

    def replay_dead_letter_job(self, key: str) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE focus_background_jobs
                    SET status = 'pending',
                        attempt = 0,
                        run_at = now(),
                        claimed_by = NULL,
                        claimed_until = NULL,
                        claim_token = NULL,
                        last_error = NULL,
                        last_failed_at = NULL,
                        dead_lettered_at = NULL,
                        updated_at = now()
                    WHERE job_key = %s
                      AND status = 'dead_lettered'
                    RETURNING job_key
                    """,
                    (str(key),),
                )
                return cur.fetchone() is not None

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
