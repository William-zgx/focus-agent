from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from ..security.rate_limit import RateLimitResult
from .coordination_models import BackgroundJobClaim, BackgroundJobSpec


@dataclass(slots=True)
class _MemoryThreadTurnLock:
    owner: str
    expires_at: float


@dataclass(slots=True)
class _MemoryBackgroundJob:
    spec: BackgroundJobSpec
    status: str
    created_at: float = field(default_factory=time.monotonic)
    updated_at: float = field(default_factory=time.monotonic)
    attempt: int = 0
    claim: BackgroundJobClaim | None = None
    claimed_until: float = 0.0
    last_heartbeat_at: float = 0.0
    last_failed_at: float = 0.0
    dead_lettered_at: float = 0.0
    last_error: str | None = None


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

    def __init__(
        self,
        *,
        retry_base_delay_seconds: float = 5.0,
        retry_max_delay_seconds: float = 300.0,
    ) -> None:
        self._lock = threading.Lock()
        self._keys: set[str] = set()
        self._jobs: dict[str, _MemoryBackgroundJob] = {}
        self.owner = f"memory-background:{uuid4().hex}"
        self.retry_base_delay_seconds = max(float(retry_base_delay_seconds or 0.0), 0.0)
        self.retry_max_delay_seconds = max(
            float(retry_max_delay_seconds or 0.0), self.retry_base_delay_seconds
        )

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

    def heartbeat_job_claim(self, key: str, claim: BackgroundJobClaim, ttl_seconds: float) -> bool:
        now = time.monotonic()
        claimed_until = now + max(float(ttl_seconds or 0.0), 0.001)
        with self._lock:
            job = self._jobs.get(key)
            if (
                job is None
                or job.claim != claim
                or job.status != "running"
                or job.claimed_until <= now
            ):
                return False
            job.claimed_until = claimed_until
            job.last_heartbeat_at = now
            job.updated_at = now
            return True

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
        run_now = datetime.now(UTC)
        ttl = max(float(claim_ttl_seconds or 300.0), 1.0)
        with self._lock:
            for key in sorted(self._jobs):
                job = self._jobs[key]
                if job.spec.kind not in kinds:
                    continue
                if job.status == "running" and job.claimed_until <= now:
                    if job.attempt >= job.spec.max_attempts:
                        self._dead_letter_memory_job(job, "claim expired after max attempts", now)
                        continue
                    self._retry_memory_job(job, "claim expired before completion", now)
                    run_now = datetime.now(UTC)
                due_pending = (
                    job.status in {"pending", "retrying"}
                    and job.spec.run_at <= run_now
                    and (job.claim is None or job.claimed_until <= now)
                )
                if not due_pending:
                    continue
                if job.attempt >= job.spec.max_attempts:
                    self._dead_letter_memory_job(job, "max attempts exhausted", now)
                    continue
                job.attempt += 1
                claim = BackgroundJobClaim(
                    claim_token=uuid4().hex,
                    owner=self.owner,
                    attempt=job.attempt,
                )
                job.status = "running"
                job.claim = claim
                job.claimed_until = now + ttl
                job.last_heartbeat_at = now
                job.updated_at = now
                return job.spec, claim
        return None

    def mark_job_claim_running(self, key: str, claim: BackgroundJobClaim) -> None:
        now = time.monotonic()
        with self._lock:
            job = self._jobs.get(key)
            if (
                job is not None
                and job.claim == claim
                and job.status in {"pending", "running"}
                and job.claimed_until > now
            ):
                job.status = "running"
                job.last_heartbeat_at = now
                job.updated_at = now

    def mark_job_claim_succeeded(self, key: str, claim: BackgroundJobClaim) -> None:
        now = time.monotonic()
        with self._lock:
            job = self._jobs.get(key)
            if (
                job is not None
                and job.claim == claim
                and job.status == "running"
                and job.claimed_until > now
            ):
                job.status = "succeeded"
                job.claim = None
                job.claimed_until = 0.0
                job.last_error = None
                job.updated_at = now

    def mark_job_claim_failed(self, key: str, claim: BackgroundJobClaim, error: str) -> None:
        now = time.monotonic()
        with self._lock:
            job = self._jobs.get(key)
            if job is not None and job.claim == claim and job.status == "running":
                if job.attempt >= job.spec.max_attempts:
                    self._dead_letter_memory_job(job, str(error)[:4000], now)
                else:
                    self._retry_memory_job(job, str(error)[:4000], now)

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
            now = time.monotonic()
            oldest_pending_at: float | None = None
            oldest_retry_at: float | None = None
            oldest_dead_lettered_at: float | None = None
            for job in self._jobs.values():
                status_key = f"job_{job.status}_total"
                status_counts[status_key] = status_counts.get(status_key, 0) + 1
                status_counts["job_attempt_total"] += job.attempt
                if job.status == "pending":
                    oldest_pending_at = (
                        job.created_at
                        if oldest_pending_at is None
                        else min(oldest_pending_at, job.created_at)
                    )
                elif job.status == "retrying":
                    timestamp = job.last_failed_at or job.updated_at
                    oldest_retry_at = (
                        timestamp if oldest_retry_at is None else min(oldest_retry_at, timestamp)
                    )
                elif job.status == "dead_lettered":
                    timestamp = job.dead_lettered_at or job.updated_at
                    oldest_dead_lettered_at = (
                        timestamp
                        if oldest_dead_lettered_at is None
                        else min(oldest_dead_lettered_at, timestamp)
                    )
            if oldest_pending_at is not None:
                status_counts["job_oldest_pending_seconds"] = int(max(0.0, now - oldest_pending_at))
            if oldest_retry_at is not None:
                status_counts["job_oldest_retry_seconds"] = int(max(0.0, now - oldest_retry_at))
            if oldest_dead_lettered_at is not None:
                status_counts["job_oldest_dead_lettered_seconds"] = int(
                    max(0.0, now - oldest_dead_lettered_at)
                )
            pending_total = len(self._keys) + status_counts["job_pending_total"]
            return {
                **status_counts,
                "job_backend_durable": 0,
                "job_pending_total": pending_total,
            }

    def list_dead_letter_jobs(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        limit = max(0, min(int(limit), 200))
        offset = max(0, int(offset))
        with self._lock:
            now = time.monotonic()
            jobs = [job for job in self._jobs.values() if job.status == "dead_lettered"]
            jobs.sort(key=lambda job: job.dead_lettered_at or job.updated_at, reverse=True)
            return {
                "items": [
                    {
                        "job_key": job.spec.key,
                        "kind": job.spec.kind,
                        "payload": dict(job.spec.payload),
                        "status": job.status,
                        "attempt": job.attempt,
                        "max_attempts": job.spec.max_attempts,
                        "dedupe_policy": job.spec.dedupe_policy,
                        "idempotency_key": job.spec.idempotency_key,
                        "last_error": job.last_error,
                        "dead_lettered_age_seconds": int(
                            max(0.0, now - (job.dead_lettered_at or job.updated_at))
                        ),
                    }
                    for job in jobs[offset : offset + limit]
                ],
                "count": len(jobs),
                "limit": limit,
                "offset": offset,
            }

    def replay_dead_letter_job(self, key: str) -> bool:
        job_key = str(key or "").strip()
        if not job_key:
            return False
        with self._lock:
            job = self._jobs.get(job_key)
            if job is None or job.status != "dead_lettered":
                return False
            now = time.monotonic()
            job.status = "pending"
            job.attempt = 0
            job.claim = None
            job.claimed_until = 0.0
            job.last_error = None
            job.last_failed_at = 0.0
            job.dead_lettered_at = 0.0
            job.updated_at = now
            job.spec = replace(job.spec, run_at=datetime.now(UTC))
            return True

    def _retry_delay_seconds(self, attempt: int) -> float:
        if self.retry_base_delay_seconds <= 0:
            return 0.0
        return min(
            self.retry_max_delay_seconds,
            self.retry_base_delay_seconds * (2 ** max(int(attempt) - 1, 0)),
        )

    def _retry_memory_job(self, job: _MemoryBackgroundJob, error: str, now: float) -> None:
        delay_seconds = self._retry_delay_seconds(job.attempt)
        job.status = "retrying"
        job.claim = None
        job.claimed_until = 0.0
        job.last_error = str(error)[:4000]
        job.last_failed_at = now
        job.updated_at = now
        job.dead_lettered_at = 0.0
        job.spec = replace(
            job.spec,
            run_at=datetime.now(UTC) + timedelta(seconds=delay_seconds),
        )

    def _dead_letter_memory_job(self, job: _MemoryBackgroundJob, error: str, now: float) -> None:
        job.status = "dead_lettered"
        job.claim = None
        job.claimed_until = 0.0
        job.last_error = str(error)[:4000]
        job.last_failed_at = now
        job.dead_lettered_at = now
        job.updated_at = now


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
