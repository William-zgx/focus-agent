from __future__ import annotations

from collections.abc import MutableSequence
from dataclasses import dataclass
from typing import Any, Literal, NoReturn, Protocol


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
OwnershipAuditExport = dict[str, Any]


class OwnershipAuditExportSink(list[OwnershipAuditEvent]):
    def export(self) -> list[OwnershipAuditExport]:
        return export_ownership_audit_events(self)


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


def ownership_audit_event_to_export(event: OwnershipAuditEvent) -> OwnershipAuditExport:
    runtime = {
        "event_type": "ownership.audit",
        "user_id": event.user_id,
        "principal": event.principal,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "action": event.action,
        "decision": event.decision,
        "reason": event.reason,
        "request_id": event.request_id,
    }
    return {
        "tool": "ownership.audit",
        "args": {
            "resource_type": event.resource_type,
            "resource_id": event.resource_id,
            "action": event.action,
            "request_id": event.request_id,
        },
        "observation": (
            f"{event.decision} ownership {event.action} "
            f"{event.resource_type} {event.resource_id}: {event.reason}"
        ),
        "duration_ms": 0.0,
        "error": event.reason if event.decision == "deny" else None,
        "cache_hit": False,
        "fallback_used": False,
        "fallback_group": None,
        "parallel_batch_size": None,
        "runtime": runtime,
        "observation_truncated": False,
    }


def export_ownership_audit_events(
    events: MutableSequence[OwnershipAuditEvent],
) -> list[OwnershipAuditExport]:
    return [ownership_audit_event_to_export(event) for event in events]


__all__ = [
    "OwnershipAuditEvent",
    "OwnershipAuditExport",
    "OwnershipAuditExportSink",
    "OwnershipAuditTrail",
    "allow_ownership",
    "assert_owner",
    "deny_ownership",
    "export_ownership_audit_events",
    "ownership_audit_event_to_export",
]
