from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class UserStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    INVITED = "invited"
    DELETED = "deleted"


class UserRole(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class User(BaseModel):
    user_id: str
    username: str | None = None
    display_name: str | None = None
    email: str | None = None
    tenant_id: str | None = None
    status: UserStatus = UserStatus.ACTIVE
    roles: list[str] = Field(default_factory=lambda: [UserRole.MEMBER.value])
    password_hash: str | None = None
    auth_provider: str = "local"
    external_subject: str | None = None
    failed_login_count: int = 0
    locked_until: str | None = None
    created_at: str
    updated_at: str
    last_seen_at: str | None = None
    last_login_at: str | None = None
    password_updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserSession(BaseModel):
    session_id: str
    user_id: str
    refresh_token_hash: str
    created_at: str
    updated_at: str
    expires_at: str
    revoked_at: str | None = None
    last_seen_at: str | None = None
    user_agent: str | None = None
    ip_address: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UserSessionListResult(BaseModel):
    items: list[UserSession] = Field(default_factory=list)
    count: int = 0
    limit: int = 50
    offset: int = 0


class UserListResult(BaseModel):
    items: list[User] = Field(default_factory=list)
    count: int = 0
    limit: int = 50
    offset: int = 0


class AuditDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    SUCCESS = "success"
    FAILURE = "failure"


class AdminAuditEvent(BaseModel):
    event_id: str
    actor_user_id: str | None = None
    tenant_id: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    decision: AuditDecision = AuditDecision.SUCCESS
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    created_at: str


class AuditEventListResult(BaseModel):
    items: list[AdminAuditEvent] = Field(default_factory=list)
    count: int = 0
    limit: int = 50
    offset: int = 0


UserStatusValue = Literal["active", "disabled", "invited", "deleted"]


__all__ = [
    "AdminAuditEvent",
    "AuditDecision",
    "AuditEventListResult",
    "User",
    "UserListResult",
    "UserRole",
    "UserSession",
    "UserSessionListResult",
    "UserStatus",
    "UserStatusValue",
]
