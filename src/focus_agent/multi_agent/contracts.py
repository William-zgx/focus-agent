"""Shared public contracts for Focus Agent multi-agent coordination."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class LockMode(StrEnum):
    EXCLUSIVE = "exclusive"
    SHARED = "shared"


@dataclass(frozen=True, slots=True)
class ResourceClaim:
    claim_id: str
    resource_id: str
    agent_id: str
    session_id: str
    mode: LockMode
    expires_at: float
    tenant_id: str | None = None
    resource_namespace: str | None = None
    fence_token: int | None = None
    canonical_resource_key: str | None = None

    @property
    def is_cross_session(self) -> bool:
        return self.canonical_resource_key is not None


class ResourceLockPort(Protocol):
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
    ) -> ResourceClaim | None: ...

    def heartbeat(self, claim: ResourceClaim, *, ttl_seconds: float) -> bool: ...

    def release(self, claim: ResourceClaim) -> None: ...

    def cleanup_expired(self) -> int: ...

    def detect_deadlocks(self) -> list[list[str]]: ...


class AgentMessageType(StrEnum):
    PROGRESS = "progress"
    CHECKPOINT = "checkpoint"
    HELP_REQUEST = "help_request"
    DIRECTIVE = "directive"
    CONFLICT_ALERT = "conflict_alert"


@dataclass(frozen=True, slots=True)
class AgentMessage:
    message_id: str
    session_id: str
    source_agent: str
    target_agent: str | None
    message_type: AgentMessageType
    payload: dict[str, Any]
    created_at: float
    expires_at: float | None
    acked_at: float | None = None


class MessageStream(Protocol):
    def poll(self) -> list[AgentMessage]: ...

    def ack(self, message_id: str) -> None: ...

    def __iter__(self) -> Iterable[AgentMessage]: ...


class MessageBusPort(Protocol):
    def publish(
        self,
        *,
        session_id: str,
        source_agent: str,
        target_agent: str | None,
        message_type: AgentMessageType,
        payload: dict[str, Any],
    ) -> str: ...

    def subscribe(self, *, session_id: str, agent_id: str) -> MessageStream: ...

    def cleanup_expired(self) -> int: ...


class FailureStrategy(StrEnum):
    RETRY = "retry"
    REASSIGN = "reassign"
    DEGRADE = "degrade"
    ESCALATE = "escalate"


class FailureHandlerPort(Protocol):
    def decide(self, *, task_id: str, error_category: str, attempt: int) -> FailureStrategy: ...


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    request_id: str
    session_id: str
    agent_id: str
    tool_name: str
    tool_args: dict[str, Any]
    risk_level: str
    status: ApprovalStatus
    submitted_at: float
    timeout_at: float
    decided_by: str | None = None


class ApprovalQueuePort(Protocol):
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
    ) -> ApprovalStatus: ...

    def decide(self, *, request_id: str, approved: bool, decided_by: str) -> None: ...

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
    ) -> ApprovalRequest: ...

    def list_pending(self) -> list[ApprovalRequest]: ...

    def get(self, request_id: str) -> ApprovalRequest | None: ...

    def expire_pending(self) -> int: ...


__all__ = [
    "AgentMessage",
    "AgentMessageType",
    "ApprovalQueuePort",
    "ApprovalRequest",
    "ApprovalStatus",
    "FailureHandlerPort",
    "FailureStrategy",
    "LockMode",
    "MessageBusPort",
    "MessageStream",
    "ResourceClaim",
    "ResourceLockPort",
]
