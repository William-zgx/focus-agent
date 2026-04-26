from __future__ import annotations

from collections.abc import MutableSequence
from dataclasses import dataclass
from typing import Literal, NoReturn, Protocol


OwnershipDecision = Literal["allow", "deny"]


class PrincipalIdentity(Protocol):
    user_id: str


PrincipalRef = str | PrincipalIdentity


@dataclass(frozen=True, slots=True)
class OwnershipAuditEvent:
    user_id: str
    resource_type: str
    resource_id: str
    action: str
    decision: OwnershipDecision
    reason: str
    request_id: str | None = None

    @property
    def principal(self) -> str:
        return self.user_id


OwnershipAuditTrail = list[OwnershipAuditEvent]


def _principal_user_id(principal: PrincipalRef) -> str:
    if isinstance(principal, str):
        user_id = principal
    else:
        user_id = getattr(principal, "user_id", "")
    if not user_id:
        raise ValueError("Ownership audit principal must include a user_id.")
    return str(user_id)


def _append_event(
    events: MutableSequence[OwnershipAuditEvent],
    *,
    principal: PrincipalRef,
    resource_type: str,
    resource_id: str,
    action: str,
    decision: OwnershipDecision,
    reason: str,
    request_id: str | None = None,
) -> OwnershipAuditEvent:
    event = OwnershipAuditEvent(
        user_id=_principal_user_id(principal),
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        decision=decision,
        reason=reason,
        request_id=request_id,
    )
    events.append(event)
    return event


def allow_ownership(
    events: MutableSequence[OwnershipAuditEvent],
    *,
    principal: PrincipalRef,
    resource_type: str,
    resource_id: str,
    action: str,
    reason: str = "owner_match",
    request_id: str | None = None,
) -> OwnershipAuditEvent:
    return _append_event(
        events,
        principal=principal,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        decision="allow",
        reason=reason,
        request_id=request_id,
    )


def deny_ownership(
    events: MutableSequence[OwnershipAuditEvent],
    *,
    principal: PrincipalRef,
    resource_type: str,
    resource_id: str,
    action: str,
    reason: str = "owner_mismatch",
    request_id: str | None = None,
    message: str | None = None,
) -> NoReturn:
    event = _append_event(
        events,
        principal=principal,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        decision="deny",
        reason=reason,
        request_id=request_id,
    )
    raise PermissionError(
        message or f"User {event.user_id} cannot {action} {resource_type} {resource_id}."
    )


def assert_owner(
    events: MutableSequence[OwnershipAuditEvent],
    *,
    principal: PrincipalRef,
    owner_user_id: str,
    resource_type: str,
    resource_id: str,
    action: str,
    request_id: str | None = None,
    allow_reason: str = "owner_match",
    deny_reason: str = "owner_mismatch",
) -> OwnershipAuditEvent:
    user_id = _principal_user_id(principal)
    if user_id == owner_user_id:
        return allow_ownership(
            events,
            principal=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            reason=allow_reason,
            request_id=request_id,
        )
    return deny_ownership(
        events,
        principal=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        reason=deny_reason,
        request_id=request_id,
    )


__all__ = [
    "OwnershipAuditEvent",
    "OwnershipAuditTrail",
    "allow_ownership",
    "assert_owner",
    "deny_ownership",
]
