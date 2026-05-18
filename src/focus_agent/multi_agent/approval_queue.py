"""Approval request queue used to decouple tool governance from graph interrupts."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .contracts import ApprovalRequest, ApprovalStatus


class InMemoryApprovalQueue:
    """Async approval queue that blocks only the requested tool call."""

    def __init__(self, *, auto_approve_low_risk: bool = False) -> None:
        self.auto_approve_low_risk = auto_approve_low_risk
        self._lock = threading.Lock()
        self._requests: dict[str, ApprovalRequest] = {}
        self._events: dict[str, asyncio.Event] = {}

    async def submit_and_wait(
        self,
        *,
        request_id: str,
        session_id: str,
        agent_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        risk_level: str,
        timeout_seconds: float,
    ) -> ApprovalStatus:
        normalized_risk = str(risk_level or "low").strip().lower()
        if self.auto_approve_low_risk and normalized_risk == "low":
            status = ApprovalStatus.AUTO_APPROVED
            self._store_request(
                request_id=request_id,
                session_id=session_id,
                agent_id=agent_id,
                tool_name=tool_name,
                tool_args=tool_args,
                risk_level=normalized_risk,
                timeout_seconds=timeout_seconds,
                status=status,
            )
            return status

        event = asyncio.Event()
        with self._lock:
            self._events[request_id] = event
        self._store_request(
            request_id=request_id,
            session_id=session_id,
            agent_id=agent_id,
            tool_name=tool_name,
            tool_args=tool_args,
            risk_level=normalized_risk,
            timeout_seconds=timeout_seconds,
            status=ApprovalStatus.PENDING,
        )
        try:
            await asyncio.wait_for(event.wait(), timeout=max(float(timeout_seconds or 0.0), 0.001))
        except TimeoutError:
            self._set_status(request_id, ApprovalStatus.TIMED_OUT, decided_by="timeout")
            return ApprovalStatus.TIMED_OUT
        request = self.get(request_id)
        return request.status if request else ApprovalStatus.TIMED_OUT

    def decide(self, *, request_id: str, approved: bool, decided_by: str) -> None:
        self._set_status(
            request_id,
            ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED,
            decided_by=decided_by,
        )
        event = self._events.get(request_id)
        if event is not None:
            event.set()

    def submit_pending(
        self,
        *,
        request_id: str,
        session_id: str,
        agent_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        risk_level: str,
        timeout_seconds: float,
    ) -> ApprovalRequest:
        self._store_request(
            request_id=request_id,
            session_id=session_id,
            agent_id=agent_id,
            tool_name=tool_name,
            tool_args=tool_args,
            risk_level=str(risk_level or "low").strip().lower(),
            timeout_seconds=timeout_seconds,
            status=ApprovalStatus.PENDING,
        )
        request = self.get(request_id)
        if request is None:
            raise KeyError(f"Unknown approval request: {request_id}")
        return request

    def get(self, request_id: str) -> ApprovalRequest | None:
        with self._lock:
            return self._requests.get(request_id)

    def list_pending(self) -> list[ApprovalRequest]:
        self.expire_pending()
        with self._lock:
            return [
                request
                for request in self._requests.values()
                if request.status == ApprovalStatus.PENDING
            ]

    def expire_pending(self) -> int:
        now = time.monotonic()
        expired: list[str] = []
        with self._lock:
            for request_id, request in list(self._requests.items()):
                if request.status == ApprovalStatus.PENDING and request.timeout_at <= now:
                    expired.append(request_id)
                    self._requests[request_id] = replace(
                        request,
                        status=ApprovalStatus.TIMED_OUT,
                        decided_by="timeout",
                    )
            for request_id in expired:
                event = self._events.get(request_id)
                if event is not None:
                    event.set()
        return len(expired)

    def _store_request(
        self,
        *,
        request_id: str,
        session_id: str,
        agent_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        risk_level: str,
        timeout_seconds: float,
        status: ApprovalStatus,
    ) -> None:
        now = time.monotonic()
        request = ApprovalRequest(
            request_id=str(request_id),
            session_id=str(session_id),
            agent_id=str(agent_id),
            tool_name=str(tool_name),
            tool_args=dict(tool_args or {}),
            risk_level=risk_level,
            status=status,
            submitted_at=now,
            timeout_at=now + max(float(timeout_seconds or 0.0), 0.001),
        )
        with self._lock:
            self._requests[request.request_id] = request

    def _set_status(
        self,
        request_id: str,
        status: ApprovalStatus,
        *,
        decided_by: str,
    ) -> None:
        with self._lock:
            request = self._requests.get(request_id)
            if request is None or request.status != ApprovalStatus.PENDING:
                return
            self._requests[request_id] = replace(
                request,
                status=status,
                decided_by=str(decided_by or "unknown"),
            )


class PostgresApprovalQueue:
    """Postgres-backed approval request queue with async polling wait."""

    def __init__(self, database_uri: str, *, poll_interval_seconds: float = 0.25) -> None:
        self.database_uri = database_uri
        self.poll_interval_seconds = max(float(poll_interval_seconds or 0.0), 0.05)

    def _connect(self):
        return psycopg.connect(self.database_uri, row_factory=dict_row)

    async def submit_and_wait(
        self,
        *,
        request_id: str,
        session_id: str,
        agent_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        risk_level: str,
        timeout_seconds: float,
    ) -> ApprovalStatus:
        timeout = max(float(timeout_seconds or 0.0), 0.001)
        timeout_at = datetime.now(UTC) + timedelta(seconds=timeout)
        self._upsert_request(
            request_id=request_id,
            session_id=session_id,
            agent_id=agent_id,
            tool_name=tool_name,
            tool_args=tool_args,
            risk_level=risk_level,
            timeout_at=timeout_at,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            request = self.get(request_id)
            if request is None:
                return ApprovalStatus.TIMED_OUT
            if request.status != ApprovalStatus.PENDING:
                return request.status
            await asyncio.sleep(self.poll_interval_seconds)
        self._set_status(request_id, ApprovalStatus.TIMED_OUT, decided_by="timeout")
        return ApprovalStatus.TIMED_OUT

    def decide(self, *, request_id: str, approved: bool, decided_by: str) -> None:
        self._set_status(
            request_id,
            ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED,
            decided_by=decided_by,
        )

    def submit_pending(
        self,
        *,
        request_id: str,
        session_id: str,
        agent_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        risk_level: str,
        timeout_seconds: float,
    ) -> ApprovalRequest:
        self._upsert_request(
            request_id=request_id,
            session_id=session_id,
            agent_id=agent_id,
            tool_name=tool_name,
            tool_args=tool_args,
            risk_level=risk_level,
            timeout_at=datetime.now(UTC)
            + timedelta(seconds=max(float(timeout_seconds or 0.0), 0.001)),
        )
        request = self.get(request_id)
        if request is None:
            raise KeyError(f"Unknown approval request: {request_id}")
        return request

    def get(self, request_id: str) -> ApprovalRequest | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT request_id, session_id, agent_id, tool_name, tool_args,
                           risk_level, status, created_at, timeout_at, decided_by
                    FROM tool_approval_requests
                    WHERE request_id = %s
                    """,
                    (request_id,),
                )
                row = cur.fetchone()
        return _approval_request_from_row(row) if row else None

    def list_pending(self) -> list[ApprovalRequest]:
        self.expire_pending()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT request_id, session_id, agent_id, tool_name, tool_args,
                           risk_level, status, created_at, timeout_at, decided_by
                    FROM tool_approval_requests
                    WHERE status = %s AND timeout_at > now()
                    ORDER BY created_at, request_id
                    """,
                    (ApprovalStatus.PENDING.value,),
                )
                return [_approval_request_from_row(row) for row in cur.fetchall()]

    def expire_pending(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE tool_approval_requests
                    SET status = %s, decided_by = %s, updated_at = now()
                    WHERE status = %s AND timeout_at <= now()
                    RETURNING request_id
                    """,
                    (
                        ApprovalStatus.TIMED_OUT.value,
                        "timeout",
                        ApprovalStatus.PENDING.value,
                    ),
                )
                return len(cur.fetchall())

    def _upsert_request(
        self,
        *,
        request_id: str,
        session_id: str,
        agent_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        risk_level: str,
        timeout_at: datetime,
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tool_approval_requests (
                        request_id,
                        session_id,
                        agent_id,
                        tool_name,
                        tool_args,
                        risk_level,
                        status,
                        timeout_at,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                    ON CONFLICT (request_id) DO NOTHING
                    """,
                    (
                        str(request_id),
                        str(session_id),
                        str(agent_id),
                        str(tool_name),
                        Jsonb(dict(tool_args or {})),
                        str(risk_level or "low").strip().lower(),
                        ApprovalStatus.PENDING.value,
                        timeout_at,
                    ),
                )

    def _set_status(
        self,
        request_id: str,
        status: ApprovalStatus,
        *,
        decided_by: str,
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE tool_approval_requests
                    SET status = %s, decided_by = %s, updated_at = now()
                    WHERE request_id = %s AND status = %s
                    """,
                    (
                        status.value,
                        str(decided_by or "unknown"),
                        str(request_id),
                        ApprovalStatus.PENDING.value,
                    ),
                )


def _approval_request_from_row(row: dict[str, Any]) -> ApprovalRequest:
    created_at = row.get("created_at")
    timeout_at = row.get("timeout_at")
    return ApprovalRequest(
        request_id=str(row["request_id"]),
        session_id=str(row["session_id"]),
        agent_id=str(row["agent_id"]),
        tool_name=str(row["tool_name"]),
        tool_args=dict(row.get("tool_args") or {}),
        risk_level=str(row.get("risk_level") or "low"),
        status=ApprovalStatus(str(row.get("status") or ApprovalStatus.PENDING.value)),
        submitted_at=created_at.timestamp() if isinstance(created_at, datetime) else 0.0,
        timeout_at=timeout_at.timestamp() if isinstance(timeout_at, datetime) else 0.0,
        decided_by=str(row["decided_by"]) if row.get("decided_by") else None,
    )


__all__ = ["InMemoryApprovalQueue", "PostgresApprovalQueue"]
