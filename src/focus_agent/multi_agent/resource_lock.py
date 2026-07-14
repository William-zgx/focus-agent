"""Resource-level mutual exclusion for controlled multi-agent execution."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from .contracts import LockMode, ResourceClaim
from .errors import DeadlockDetected


class InMemoryResourceLockManager:
    """TTL-based resource locks for local tests and default-off Agent Team opt-in."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._claims: dict[str, ResourceClaim] = {}
        self._waits_for: dict[str, set[str]] = {}
        self._last_fence_tokens: dict[str, int] = {}

    def try_acquire(
        self,
        *,
        resource_id: str,
        agent_id: str,
        session_id: str,
        mode: LockMode,
        ttl_seconds: float,
        tenant_id: str | None = None,
        resource_namespace: str | None = None,
        fence_token: int | None = None,
    ) -> ResourceClaim | None:
        now = time.monotonic()
        resource_id = _normalize_resource_id(resource_id)
        agent_id = str(agent_id or "").strip()
        session_id = str(session_id or "").strip()
        if not agent_id or not session_id:
            raise ValueError("agent_id and session_id are required")
        resolved_mode = LockMode(mode)
        requested_fence_token = _normalize_fence_token(fence_token)
        tenant_id, resource_namespace, canonical_resource_key = _resolve_lock_scope(
            resource_id=resource_id,
            tenant_id=tenant_id,
            resource_namespace=resource_namespace,
            cross_session=requested_fence_token is not None,
        )
        expires_at = now + max(float(ttl_seconds or 0.0), 0.001)
        with self._lock:
            self._drop_expired(now)
            conflicts = [
                claim
                for claim in self._claims.values()
                if _claims_share_lock_scope(
                    claim,
                    session_id=session_id,
                    resource_id=resource_id,
                    canonical_resource_key=canonical_resource_key,
                )
                and (canonical_resource_key is not None or claim.agent_id != agent_id)
                and _lock_modes_conflict(claim.mode, resolved_mode)
            ]
            if conflicts:
                waiting_on = {claim.agent_id for claim in conflicts if claim.agent_id != agent_id}
                if waiting_on:
                    self._waits_for.setdefault(agent_id, set()).update(waiting_on)
                if _has_cycle(self._waits_for):
                    raise DeadlockDetected(
                        f"Deadlock detected while {agent_id} waits for {resource_id}"
                    )
                return None
            next_fence_token = _next_fence_token(
                previous_fence_token=self._last_fence_tokens.get(canonical_resource_key, 0)
                if canonical_resource_key is not None
                else 0,
                canonical_resource_key=canonical_resource_key,
                requested_fence_token=requested_fence_token,
            )
            if canonical_resource_key is not None and next_fence_token is not None:
                self._last_fence_tokens[canonical_resource_key] = next_fence_token
            claim = ResourceClaim(
                claim_id=uuid4().hex,
                resource_id=resource_id,
                agent_id=agent_id,
                session_id=session_id,
                mode=resolved_mode,
                expires_at=expires_at,
                tenant_id=tenant_id,
                resource_namespace=resource_namespace,
                fence_token=next_fence_token,
                canonical_resource_key=canonical_resource_key,
            )
            self._claims[claim.claim_id] = claim
            self._waits_for.pop(agent_id, None)
            return claim

    def heartbeat(self, claim: ResourceClaim, *, ttl_seconds: float) -> bool:
        expires_at = time.monotonic() + max(float(ttl_seconds or 0.0), 0.001)
        with self._lock:
            current = self._claims.get(claim.claim_id)
            if (
                current is None
                or current.session_id != claim.session_id
                or current.agent_id != claim.agent_id
                or current.expires_at <= time.monotonic()
            ):
                return False
            self._claims[claim.claim_id] = replace(current, expires_at=expires_at)
            return True

    def release(self, claim: ResourceClaim) -> None:
        with self._lock:
            current = self._claims.get(claim.claim_id)
            if (
                current is not None
                and current.session_id == claim.session_id
                and current.agent_id == claim.agent_id
            ):
                self._claims.pop(claim.claim_id, None)
            self._prune_wait_graph()

    def release_session(self, session_id: str) -> int:
        session_id = str(session_id or "").strip()
        if not session_id:
            return 0
        with self._lock:
            claim_ids = [
                claim_id
                for claim_id, claim in self._claims.items()
                if claim.session_id == session_id
            ]
            for claim_id in claim_ids:
                self._claims.pop(claim_id, None)
            self._prune_wait_graph()
            return len(claim_ids)

    def list_active_claims(self) -> list[ResourceClaim]:
        with self._lock:
            self._drop_expired(time.monotonic())
            return sorted(self._claims.values(), key=lambda item: item.claim_id)

    def cleanup_expired(self) -> int:
        with self._lock:
            return self._drop_expired(time.monotonic())

    def detect_deadlocks(self) -> list[list[str]]:
        with self._lock:
            self._drop_expired(time.monotonic())
            cycle = _first_cycle(self._waits_for)
            return [cycle] if cycle else []

    def _drop_expired(self, now: float) -> int:
        expired = [claim_id for claim_id, claim in self._claims.items() if claim.expires_at <= now]
        for claim_id in expired:
            self._claims.pop(claim_id, None)
        self._prune_wait_graph()
        return len(expired)

    def _prune_wait_graph(self) -> None:
        active_agents = {claim.agent_id for claim in self._claims.values()}
        for agent_id in list(self._waits_for):
            waits_for = {
                blocked for blocked in self._waits_for[agent_id] if blocked in active_agents
            }
            if waits_for and agent_id in active_agents:
                self._waits_for[agent_id] = waits_for
            else:
                self._waits_for.pop(agent_id, None)


class PostgresResourceLockManager:
    """Postgres-backed resource locks with TTL expiry and conflict checks."""

    def __init__(self, database_uri: str) -> None:
        self.database_uri = database_uri
        self._fence_token_lock = threading.Lock()
        self._fence_token_floors: dict[str, int] = {}

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    @staticmethod
    def _expires_at(ttl_seconds: float) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=max(float(ttl_seconds or 0.0), 0.001))

    def try_acquire(
        self,
        *,
        resource_id: str,
        agent_id: str,
        session_id: str,
        mode: LockMode,
        ttl_seconds: float,
        tenant_id: str | None = None,
        resource_namespace: str | None = None,
        fence_token: int | None = None,
    ) -> ResourceClaim | None:
        resource_id = _normalize_resource_id(resource_id)
        agent_id = str(agent_id or "").strip()
        session_id = str(session_id or "").strip()
        if not agent_id or not session_id:
            raise ValueError("agent_id and session_id are required")
        resolved_mode = LockMode(mode)
        requested_fence_token = _normalize_fence_token(fence_token)
        tenant_id, resource_namespace, canonical_resource_key = _resolve_lock_scope(
            resource_id=resource_id,
            tenant_id=tenant_id,
            resource_namespace=resource_namespace,
            cross_session=requested_fence_token is not None,
        )
        storage_resource_id = canonical_resource_key or resource_id
        advisory_scope = tenant_id or session_id
        claim_id = uuid4().hex
        expires_at = self._expires_at(ttl_seconds)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                    (advisory_scope, storage_resource_id),
                )
                cur.execute(
                    """
                    UPDATE agent_resource_claims
                    SET released = TRUE, updated_at = now()
                    WHERE released = FALSE AND expires_at <= now()
                    """
                )
                if canonical_resource_key is None:
                    cur.execute(
                        """
                        SELECT claim_id, lock_mode
                        FROM agent_resource_claims
                        WHERE session_id = %s
                          AND resource_id = %s
                          AND released = FALSE
                          AND expires_at > now()
                          AND agent_id <> %s
                        FOR UPDATE
                        """,
                        (session_id, storage_resource_id, agent_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT claim_id, lock_mode
                        FROM agent_resource_claims
                        WHERE resource_id = %s
                          AND released = FALSE
                          AND expires_at > now()
                        FOR UPDATE
                        """,
                        (storage_resource_id,),
                    )
                conflicts = [
                    row
                    for row in cur.fetchall()
                    if _lock_modes_conflict(LockMode(str(row["lock_mode"])), resolved_mode)
                ]
                if conflicts:
                    return None
                fence_token_value = None
                if canonical_resource_key is not None:
                    cur.execute("SELECT txid_current() AS fence_token")
                    row = cur.fetchone()
                    generated_fence_token = int(
                        row["fence_token"] if isinstance(row, dict) else row[0]
                    )
                    with self._fence_token_lock:
                        fence_token_value = _next_fence_token(
                            previous_fence_token=max(
                                self._fence_token_floors.get(canonical_resource_key, 0),
                                generated_fence_token - 1,
                            ),
                            canonical_resource_key=canonical_resource_key,
                            requested_fence_token=requested_fence_token,
                        )
                        self._fence_token_floors[canonical_resource_key] = fence_token_value
                cur.execute(
                    """
                    INSERT INTO agent_resource_claims (
                        claim_id,
                        session_id,
                        resource_id,
                        agent_id,
                        lock_mode,
                        expires_at,
                        released,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, FALSE, now(), now())
                    """,
                    (
                        claim_id,
                        session_id,
                        storage_resource_id,
                        agent_id,
                        resolved_mode.value,
                        expires_at,
                    ),
                )
        return ResourceClaim(
            claim_id=claim_id,
            resource_id=resource_id,
            agent_id=agent_id,
            session_id=session_id,
            mode=resolved_mode,
            expires_at=expires_at.timestamp(),
            tenant_id=tenant_id,
            resource_namespace=resource_namespace,
            fence_token=fence_token_value,
            canonical_resource_key=canonical_resource_key,
        )

    def heartbeat(self, claim: ResourceClaim, *, ttl_seconds: float) -> bool:
        expires_at = self._expires_at(ttl_seconds)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_resource_claims
                    SET expires_at = %s, updated_at = now()
                    WHERE claim_id = %s
                      AND session_id = %s
                      AND agent_id = %s
                      AND released = FALSE
                      AND expires_at > now()
                    RETURNING claim_id
                    """,
                    (expires_at, claim.claim_id, claim.session_id, claim.agent_id),
                )
                return cur.fetchone() is not None

    def release(self, claim: ResourceClaim) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_resource_claims
                    SET released = TRUE, updated_at = now()
                    WHERE claim_id = %s AND agent_id = %s
                    """,
                    (claim.claim_id, claim.agent_id),
                )

    def release_session(self, session_id: str) -> int:
        session_id = str(session_id or "").strip()
        if not session_id:
            return 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_resource_claims
                    SET released = TRUE, updated_at = now()
                    WHERE session_id = %s AND released = FALSE
                    RETURNING claim_id
                    """,
                    (session_id,),
                )
                return len(cur.fetchall())

    def list_active_claims(self) -> list[ResourceClaim]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT claim_id, resource_id, agent_id, session_id, lock_mode, expires_at
                    FROM agent_resource_claims
                    WHERE released = FALSE AND expires_at > now()
                    ORDER BY claim_id
                    """
                )
                return [_claim_from_row(row) for row in cur.fetchall()]

    def cleanup_expired(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_resource_claims
                    SET released = TRUE, updated_at = now()
                    WHERE released = FALSE AND expires_at <= now()
                    RETURNING claim_id
                    """
                )
                return len(cur.fetchall())

    def detect_deadlocks(self) -> list[list[str]]:
        self.cleanup_expired()
        return []


def _claim_from_row(row: dict[str, object]) -> ResourceClaim:
    expires_at = row["expires_at"]
    timestamp = (
        expires_at.timestamp() if isinstance(expires_at, datetime) else float(expires_at or 0.0)
    )
    resource_id = str(row["resource_id"])
    tenant_id, resource_namespace, canonical_resource_key, display_resource_id = (
        _parse_canonical_resource_key(resource_id)
    )
    return ResourceClaim(
        claim_id=str(row["claim_id"]),
        resource_id=display_resource_id,
        agent_id=str(row["agent_id"]),
        session_id=str(row["session_id"]),
        mode=LockMode(str(row["lock_mode"])),
        expires_at=timestamp,
        tenant_id=tenant_id,
        resource_namespace=resource_namespace,
        canonical_resource_key=canonical_resource_key,
    )


def _resolve_lock_scope(
    *,
    resource_id: str,
    tenant_id: str | None,
    resource_namespace: str | None,
    cross_session: bool,
) -> tuple[str | None, str | None, str | None]:
    normalized_tenant_id = _normalize_optional_scope_value(tenant_id, "tenant_id")
    normalized_namespace = _normalize_optional_scope_value(
        resource_namespace,
        "resource_namespace",
    )
    if not cross_session and normalized_tenant_id is None and normalized_namespace is None:
        return None, None, None
    return (
        normalized_tenant_id,
        normalized_namespace,
        _canonical_resource_key(
            tenant_id=normalized_tenant_id,
            resource_namespace=normalized_namespace,
            resource_id=resource_id,
        ),
    )


def _normalize_optional_scope_value(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} must not be blank when provided")
    return normalized


def _canonical_resource_key(
    *,
    tenant_id: str | None,
    resource_namespace: str | None,
    resource_id: str,
) -> str:
    return "focus-agent-resource-lock:v1:" + json.dumps(
        [tenant_id, resource_namespace, resource_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _parse_canonical_resource_key(
    resource_id: str,
) -> tuple[str | None, str | None, str | None, str]:
    prefix = "focus-agent-resource-lock:v1:"
    if not resource_id.startswith(prefix):
        return None, None, None, resource_id
    try:
        tenant_id, resource_namespace, display_resource_id = json.loads(resource_id[len(prefix) :])
    except (TypeError, ValueError):
        return None, None, None, resource_id
    if not isinstance(display_resource_id, str):
        return None, None, None, resource_id
    return (
        tenant_id if isinstance(tenant_id, str) else None,
        resource_namespace if isinstance(resource_namespace, str) else None,
        resource_id,
        display_resource_id,
    )


def _normalize_fence_token(fence_token: int | None) -> int | None:
    if fence_token is None:
        return None
    normalized = int(fence_token)
    if normalized < 0:
        raise ValueError("fence_token must be non-negative")
    return normalized


def _claims_share_lock_scope(
    claim: ResourceClaim,
    *,
    session_id: str,
    resource_id: str,
    canonical_resource_key: str | None,
) -> bool:
    if canonical_resource_key is not None:
        return claim.canonical_resource_key == canonical_resource_key
    return (
        claim.canonical_resource_key is None
        and claim.session_id == session_id
        and claim.resource_id == resource_id
    )


def _next_fence_token(
    *,
    previous_fence_token: int,
    canonical_resource_key: str | None,
    requested_fence_token: int | None,
) -> int | None:
    if canonical_resource_key is None:
        return None
    return max(previous_fence_token + 1, requested_fence_token or 0)


def _normalize_resource_id(resource_id: str) -> str:
    text = str(resource_id or "").strip()
    if not text or ":" not in text:
        raise ValueError("resource_id must use '<type>:<identifier>' format")
    return text


def _lock_modes_conflict(left: LockMode, right: LockMode) -> bool:
    return left == LockMode.EXCLUSIVE or right == LockMode.EXCLUSIVE


def _has_cycle(graph: dict[str, set[str]]) -> bool:
    return _first_cycle(graph) is not None


def _first_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in visiting:
            index = stack.index(node)
            return [*stack[index:], node]
        if node in visited:
            return None
        visiting.add(node)
        stack.append(node)
        for child in graph.get(node, set()):
            cycle = visit(child)
            if cycle is not None:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in list(graph):
        cycle = visit(node)
        if cycle is not None:
            return cycle
    return None


__all__ = ["InMemoryResourceLockManager", "PostgresResourceLockManager"]
