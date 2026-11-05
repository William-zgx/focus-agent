"""Recoverable, executor-agnostic approvals for paused Agent Team invocations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from enum import StrEnum
from threading import Lock
from time import time
from typing import Any, Protocol


class AgentTeamApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    VOIDED = "voided"


class AgentTeamApprovalAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class PendingAgentTeamInvocation:
    """Internal-only input that retains the original tool arguments and checkpoint."""

    approval_id: str
    session_id: str
    task_id: str
    invocation_id: str
    tool_name: str
    raw_args: Mapping[str, Any]
    checkpoint: Mapping[str, Any]
    expires_at: float
    sensitive_arg_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentTeamApprovalDisplay:
    """Safe approval projection for API and UI callers; it never contains raw args."""

    approval_id: str
    session_id: str
    task_id: str
    invocation_id: str
    tool_name: str
    display_args: Mapping[str, Any]
    status: AgentTeamApprovalStatus
    created_at: float
    expires_at: float
    decided_at: float | None = None
    decided_by: str | None = None
    reason: str | None = None
    resume_job_id: str | None = None


@dataclass(frozen=True, slots=True)
class AgentTeamApprovalDecision:
    """Result of an approval action without executor-only invocation data."""

    approval: AgentTeamApprovalDisplay
    created_resume_job: bool = False


@dataclass(frozen=True, slots=True)
class AgentTeamApprovalResumeJob:
    """Executor-only resume payload, kept separate from display DTOs."""

    job_id: str
    idempotency_key: str
    approval_id: str
    session_id: str
    task_id: str
    invocation_id: str
    tool_name: str
    raw_args: Mapping[str, Any]
    checkpoint: Mapping[str, Any]
    created_at: float


class AgentTeamApprovalTaskStatePort(Protocol):
    """Minimal lifecycle view needed to avoid reviving obsolete Agent Team work."""

    def is_cancelled(self, task_id: str) -> bool: ...

    def is_superseded(self, task_id: str) -> bool: ...


class AgentTeamApprovalResumeStore(Protocol):
    """Persistence port. Conditional writes must be atomic for durable adapters."""

    def save_pending_if_absent(
        self,
        approval: _StoredApproval,
    ) -> tuple[_StoredApproval, bool]: ...

    def get_approval(self, approval_id: str) -> _StoredApproval | None: ...

    def transition_pending(
        self,
        approval_id: str,
        *,
        status: AgentTeamApprovalStatus,
        decided_at: float,
        decided_by: str | None,
        reason: str | None,
    ) -> _StoredApproval | None: ...

    def save_resume_job_if_absent(
        self,
        job: AgentTeamApprovalResumeJob,
    ) -> tuple[AgentTeamApprovalResumeJob, bool]: ...

    def get_resume_job(self, approval_id: str) -> AgentTeamApprovalResumeJob | None: ...

    def list_resume_jobs(self) -> tuple[AgentTeamApprovalResumeJob, ...]: ...

    def list_pending_approvals(self) -> tuple[_StoredApproval, ...]: ...


class AgentTeamApprovalResumeExecutorPort(Protocol):
    """Future executor seam; callers can submit jobs returned by this service."""

    def resume(self, job: AgentTeamApprovalResumeJob) -> None: ...


@dataclass(frozen=True, slots=True)
class _StoredApproval:
    approval_id: str
    session_id: str
    task_id: str
    invocation_id: str
    tool_name: str
    raw_args: Mapping[str, Any]
    display_args: Mapping[str, Any]
    checkpoint: Mapping[str, Any]
    status: AgentTeamApprovalStatus
    created_at: float
    expires_at: float
    decided_at: float | None = None
    decided_by: str | None = None
    reason: str | None = None


class InMemoryAgentTeamApprovalResumeStore:
    """Thread-safe reference store for tests and local composition."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._approvals: dict[str, _StoredApproval] = {}
        self._resume_jobs: dict[str, AgentTeamApprovalResumeJob] = {}

    def save_pending_if_absent(
        self,
        approval: _StoredApproval,
    ) -> tuple[_StoredApproval, bool]:
        with self._lock:
            existing = self._approvals.get(approval.approval_id)
            if existing is not None:
                return _copy_stored_approval(existing), False
            self._approvals[approval.approval_id] = _copy_stored_approval(approval)
            return _copy_stored_approval(approval), True

    def get_approval(self, approval_id: str) -> _StoredApproval | None:
        with self._lock:
            approval = self._approvals.get(approval_id)
            return _copy_stored_approval(approval) if approval is not None else None

    def transition_pending(
        self,
        approval_id: str,
        *,
        status: AgentTeamApprovalStatus,
        decided_at: float,
        decided_by: str | None,
        reason: str | None,
    ) -> _StoredApproval | None:
        with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None or approval.status is not AgentTeamApprovalStatus.PENDING:
                return _copy_stored_approval(approval) if approval is not None else None
            updated = replace(
                approval,
                status=status,
                decided_at=decided_at,
                decided_by=decided_by,
                reason=reason,
            )
            self._approvals[approval_id] = updated
            return _copy_stored_approval(updated)

    def save_resume_job_if_absent(
        self,
        job: AgentTeamApprovalResumeJob,
    ) -> tuple[AgentTeamApprovalResumeJob, bool]:
        with self._lock:
            existing = self._resume_jobs.get(job.approval_id)
            if existing is not None:
                return _copy_resume_job(existing), False
            self._resume_jobs[job.approval_id] = _copy_resume_job(job)
            return _copy_resume_job(job), True

    def get_resume_job(self, approval_id: str) -> AgentTeamApprovalResumeJob | None:
        with self._lock:
            job = self._resume_jobs.get(approval_id)
            return _copy_resume_job(job) if job is not None else None

    def list_resume_jobs(self) -> tuple[AgentTeamApprovalResumeJob, ...]:
        with self._lock:
            return tuple(_copy_resume_job(job) for job in self._resume_jobs.values())

    def list_pending_approvals(self) -> tuple[_StoredApproval, ...]:
        with self._lock:
            return tuple(
                _copy_stored_approval(approval)
                for approval in self._approvals.values()
                if approval.status is AgentTeamApprovalStatus.PENDING
            )


class InMemoryAgentTeamApprovalTaskState:
    """Mutable task lifecycle adapter useful while a durable task repository is absent."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._cancelled: set[str] = set()
        self._superseded: set[str] = set()

    def cancel(self, task_id: str) -> None:
        with self._lock:
            self._cancelled.add(_required_string(task_id, "task_id"))

    def supersede(self, task_id: str) -> None:
        with self._lock:
            self._superseded.add(_required_string(task_id, "task_id"))

    def is_cancelled(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._cancelled

    def is_superseded(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._superseded


class AgentTeamApprovalResumeService:
    """State machine for pausing, deciding, and safely resuming tool invocations."""

    def __init__(
        self,
        *,
        store: AgentTeamApprovalResumeStore | None = None,
        task_state: AgentTeamApprovalTaskStatePort | None = None,
        clock: Callable[[], float] = time,
    ) -> None:
        self._store = store or InMemoryAgentTeamApprovalResumeStore()
        self._task_state = task_state
        self._clock = clock

    def save_pending_invocation(
        self,
        invocation: PendingAgentTeamInvocation,
    ) -> AgentTeamApprovalDisplay:
        created_at = self._clock()
        approval = _StoredApproval(
            approval_id=_required_string(invocation.approval_id, "approval_id"),
            session_id=_required_string(invocation.session_id, "session_id"),
            task_id=_required_string(invocation.task_id, "task_id"),
            invocation_id=_required_string(invocation.invocation_id, "invocation_id"),
            tool_name=_required_string(invocation.tool_name, "tool_name"),
            raw_args=_copy_mapping(invocation.raw_args),
            display_args=redact_agent_team_approval_args(
                invocation.raw_args,
                sensitive_arg_names=invocation.sensitive_arg_names,
            ),
            checkpoint=_copy_mapping(invocation.checkpoint),
            status=AgentTeamApprovalStatus.PENDING,
            created_at=created_at,
            expires_at=float(invocation.expires_at),
        )
        existing, created = self._store.save_pending_if_absent(approval)
        if not created and not _same_pending_invocation(existing, approval):
            raise ValueError(
                f"approval_id already belongs to a different invocation: {approval.approval_id}"
            )
        return self._display(existing)

    def get_approval(self, approval_id: str) -> AgentTeamApprovalDisplay | None:
        approval = self._get_with_expiry(approval_id)
        return self._display(approval) if approval is not None else None

    def approve(
        self,
        approval_id: str,
        *,
        decided_by: str,
        reason: str | None = None,
    ) -> AgentTeamApprovalDecision:
        return self._decide(
            approval_id,
            action=AgentTeamApprovalAction.APPROVE,
            decided_by=decided_by,
            reason=reason,
        )

    def reject(
        self,
        approval_id: str,
        *,
        decided_by: str,
        reason: str | None = None,
    ) -> AgentTeamApprovalDecision:
        return self._decide(
            approval_id,
            action=AgentTeamApprovalAction.REJECT,
            decided_by=decided_by,
            reason=reason,
        )

    def expire_pending(self) -> int:
        expired = 0
        for approval in self._pending_approvals():
            if self._expire_if_due(approval) is not approval:
                expired += 1
        return expired

    def void_pending(
        self,
        approval_id: str,
        *,
        reason: str = "invocation_voided",
    ) -> AgentTeamApprovalDisplay | None:
        approval = self._get_with_expiry(approval_id)
        if approval is None:
            return None
        if approval.status is AgentTeamApprovalStatus.PENDING:
            approval = (
                self._store.transition_pending(
                    approval.approval_id,
                    status=AgentTeamApprovalStatus.VOIDED,
                    decided_at=self._clock(),
                    decided_by=None,
                    reason=reason,
                )
                or approval
            )
        return self._display(approval)

    def get_resume_job_for_executor(
        self,
        approval_id: str,
    ) -> AgentTeamApprovalResumeJob | None:
        """Return a raw resume payload only while its task remains recoverable."""

        approval = self._get_with_expiry(approval_id)
        if approval is None or approval.status is not AgentTeamApprovalStatus.APPROVED:
            return None
        if not self._task_can_resume(approval.task_id):
            return None
        return self._store.get_resume_job(approval.approval_id)

    def list_resume_jobs_for_executor(self) -> tuple[AgentTeamApprovalResumeJob, ...]:
        return tuple(
            job
            for job in self._store.list_resume_jobs()
            if self.get_resume_job_for_executor(job.approval_id) is not None
        )

    def _decide(
        self,
        approval_id: str,
        *,
        action: AgentTeamApprovalAction,
        decided_by: str,
        reason: str | None,
    ) -> AgentTeamApprovalDecision:
        approval = self._get_with_expiry(approval_id)
        if approval is None:
            raise KeyError(f"unknown approval: {approval_id}")
        if approval.status is AgentTeamApprovalStatus.PENDING:
            if action is AgentTeamApprovalAction.APPROVE and not self._task_can_resume(
                approval.task_id
            ):
                next_status = AgentTeamApprovalStatus.VOIDED
                next_reason = reason or "task_cancelled_or_superseded"
            else:
                next_status = (
                    AgentTeamApprovalStatus.APPROVED
                    if action is AgentTeamApprovalAction.APPROVE
                    else AgentTeamApprovalStatus.REJECTED
                )
                next_reason = reason
            approval = (
                self._store.transition_pending(
                    approval.approval_id,
                    status=next_status,
                    decided_at=self._clock(),
                    decided_by=_required_string(decided_by, "decided_by"),
                    reason=next_reason,
                )
                or approval
            )

        created_resume_job = False
        if (
            action is AgentTeamApprovalAction.APPROVE
            and approval.status is AgentTeamApprovalStatus.APPROVED
            and self._task_can_resume(approval.task_id)
        ):
            _, created_resume_job = self._store.save_resume_job_if_absent(
                _resume_job_from_approval(approval)
            )
        return AgentTeamApprovalDecision(
            approval=self._display(approval),
            created_resume_job=created_resume_job,
        )

    def _get_with_expiry(self, approval_id: str) -> _StoredApproval | None:
        approval = self._store.get_approval(_required_string(approval_id, "approval_id"))
        return self._expire_if_due(approval) if approval is not None else None

    def _expire_if_due(self, approval: _StoredApproval) -> _StoredApproval:
        if (
            approval.status is AgentTeamApprovalStatus.PENDING
            and approval.expires_at <= self._clock()
        ):
            return (
                self._store.transition_pending(
                    approval.approval_id,
                    status=AgentTeamApprovalStatus.EXPIRED,
                    decided_at=self._clock(),
                    decided_by="timeout",
                    reason="approval_expired",
                )
                or approval
            )
        return approval

    def _pending_approvals(self) -> tuple[_StoredApproval, ...]:
        return self._store.list_pending_approvals()

    def _task_can_resume(self, task_id: str) -> bool:
        return self._task_state is None or (
            not self._task_state.is_cancelled(task_id)
            and not self._task_state.is_superseded(task_id)
        )

    def _display(self, approval: _StoredApproval) -> AgentTeamApprovalDisplay:
        resume_job = self._store.get_resume_job(approval.approval_id)
        return AgentTeamApprovalDisplay(
            approval_id=approval.approval_id,
            session_id=approval.session_id,
            task_id=approval.task_id,
            invocation_id=approval.invocation_id,
            tool_name=approval.tool_name,
            display_args=_copy_mapping(approval.display_args),
            status=approval.status,
            created_at=approval.created_at,
            expires_at=approval.expires_at,
            decided_at=approval.decided_at,
            decided_by=approval.decided_by,
            reason=approval.reason,
            resume_job_id=resume_job.job_id if resume_job is not None else None,
        )


def redact_agent_team_approval_args(
    args: Mapping[str, Any],
    *,
    sensitive_arg_names: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return a display-safe deep copy that masks declared and conventional secrets."""

    declared_sensitive = {
        str(name).strip().lower() for name in sensitive_arg_names if str(name).strip()
    }
    return {
        str(key): _redact_value(
            key=str(key),
            value=value,
            declared_sensitive=declared_sensitive,
        )
        for key, value in args.items()
    }


def _redact_value(*, key: str, value: Any, declared_sensitive: set[str]) -> Any:
    if key.strip().lower() in declared_sensitive or _looks_sensitive(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(nested_key): _redact_value(
                key=str(nested_key),
                value=nested_value,
                declared_sensitive=declared_sensitive,
            )
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [
            _redact_value(key=key, value=item, declared_sensitive=declared_sensitive)
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _redact_value(key=key, value=item, declared_sensitive=declared_sensitive)
            for item in value
        )
    return deepcopy(value)


def _looks_sensitive(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    return any(
        marker in normalized
        for marker in (
            "token",
            "secret",
            "password",
            "passwd",
            "credential",
            "authorization",
            "api_key",
            "apikey",
            "private_key",
            "cookie",
        )
    )


def _resume_job_from_approval(approval: _StoredApproval) -> AgentTeamApprovalResumeJob:
    job_id = f"agent-team-approval-resume:{approval.approval_id}"
    return AgentTeamApprovalResumeJob(
        job_id=job_id,
        idempotency_key=job_id,
        approval_id=approval.approval_id,
        session_id=approval.session_id,
        task_id=approval.task_id,
        invocation_id=approval.invocation_id,
        tool_name=approval.tool_name,
        raw_args=_copy_mapping(approval.raw_args),
        checkpoint=_copy_mapping(approval.checkpoint),
        created_at=approval.decided_at or approval.created_at,
    )


def _same_pending_invocation(left: _StoredApproval, right: _StoredApproval) -> bool:
    return (
        left.session_id,
        left.task_id,
        left.invocation_id,
        left.tool_name,
        left.raw_args,
        left.checkpoint,
        left.expires_at,
    ) == (
        right.session_id,
        right.task_id,
        right.invocation_id,
        right.tool_name,
        right.raw_args,
        right.checkpoint,
        right.expires_at,
    )


def _copy_stored_approval(approval: _StoredApproval) -> _StoredApproval:
    return replace(
        approval,
        raw_args=_copy_mapping(approval.raw_args),
        display_args=_copy_mapping(approval.display_args),
        checkpoint=_copy_mapping(approval.checkpoint),
    )


def _copy_resume_job(job: AgentTeamApprovalResumeJob) -> AgentTeamApprovalResumeJob:
    return replace(
        job,
        raw_args=_copy_mapping(job.raw_args),
        checkpoint=_copy_mapping(job.checkpoint),
    )


def _copy_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(value))


def _required_string(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


__all__ = [
    "AgentTeamApprovalAction",
    "AgentTeamApprovalDecision",
    "AgentTeamApprovalDisplay",
    "AgentTeamApprovalResumeExecutorPort",
    "AgentTeamApprovalResumeJob",
    "AgentTeamApprovalResumeService",
    "AgentTeamApprovalResumeStore",
    "AgentTeamApprovalStatus",
    "AgentTeamApprovalTaskStatePort",
    "InMemoryAgentTeamApprovalResumeStore",
    "InMemoryAgentTeamApprovalTaskState",
    "PendingAgentTeamInvocation",
    "redact_agent_team_approval_args",
]
