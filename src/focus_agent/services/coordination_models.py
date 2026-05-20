from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from focus_agent.multi_agent.contracts import (
    ApprovalQueuePort,
    FailureHandlerPort,
    MessageBusPort,
    ResourceLockPort,
)

from ..security.rate_limit import RateLimitResult

BACKGROUND_JOB_DEDUPE_POLICIES = frozenset({"skip", "replace"})


class ThreadTurnLockBackend(Protocol):
    def acquire_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool: ...

    def heartbeat_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool: ...

    def release_thread_turn(self, *, thread_id: str, owner: str) -> None: ...


class BackgroundJobDeduperBackend(Protocol):
    def try_claim_job_key(self, key: str) -> bool: ...

    def release_job_key(self, key: str) -> None: ...


class RateLimitBackend(Protocol):
    def check(self, *, key: str, limit: int, window_seconds: float = 60.0) -> RateLimitResult: ...


@dataclass(frozen=True, slots=True)
class BackgroundJobSpec:
    kind: str
    key: str
    payload: dict[str, Any] = field(default_factory=dict)
    run_at: datetime | None = None
    max_attempts: int = 1
    dedupe_policy: str = "skip"
    idempotency_key: str | None = None

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
        object.__setattr__(
            self,
            "idempotency_key",
            str(self.idempotency_key or key).strip() or None,
        )


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
    resource_locks: ResourceLockPort | None = None
    message_bus: MessageBusPort | None = None
    failure_handler: FailureHandlerPort | None = None
    approval_queue: ApprovalQueuePort | None = None


@dataclass(frozen=True, slots=True)
class ThreadTurnLease:
    thread_id: str
    owner: str


def _normalize_background_run_at(run_at: datetime | None) -> datetime:
    if run_at is None:
        return datetime.now(UTC)
    if run_at.tzinfo is None:
        return run_at.replace(tzinfo=UTC)
    return run_at.astimezone(UTC)


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


def _datetime_json(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if value is None:
        return None
    return str(value)
