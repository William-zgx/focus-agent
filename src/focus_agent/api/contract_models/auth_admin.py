from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from focus_agent.core.users import AdminAuditEvent, User, UserSession, UserStatusValue


class DemoTokenRequest(BaseModel):
    user_id: str = 'researcher-1'
    tenant_id: str | None = None
    scopes: list[str] = Field(default_factory=lambda: ['chat', 'branches'])


class AuthRegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class AuthLoginRequest(BaseModel):
    username: str
    password: str


class AuthRefreshRequest(BaseModel):
    refresh_token: str | None = None


class AuthLogoutRequest(BaseModel):
    refresh_token: str | None = None


class AuthChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AdminResetPasswordRequest(BaseModel):
    new_password: str
    reason: str


class AuthErrorResponse(BaseModel):
    code: str
    message: str


class UserResponse(BaseModel):
    user_id: str
    username: str | None = None
    display_name: str | None = None
    email: str | None = None
    tenant_id: str | None = None
    status: UserStatusValue = "active"
    roles: list[str] = Field(default_factory=list)
    auth_provider: str = "local"
    created_at: str
    updated_at: str
    last_seen_at: str | None = None
    last_login_at: str | None = None
    password_updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        payload = user.model_dump(mode="json")
        return cls.model_validate(payload)


class UserListResponse(BaseModel):
    items: list[UserResponse] = Field(default_factory=list)
    count: int = 0
    limit: int = 50
    offset: int = 0


class UserSessionResponse(BaseModel):
    session_id: str
    user_id: str
    created_at: str
    updated_at: str
    expires_at: str
    revoked_at: str | None = None
    last_seen_at: str | None = None
    user_agent: str | None = None
    ip_address: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    current: bool = False

    @classmethod
    def from_session(
        cls,
        session: UserSession,
        *,
        current_session_id: str | None = None,
    ) -> "UserSessionResponse":
        payload = session.model_dump(mode="json")
        payload["current"] = bool(current_session_id and session.session_id == current_session_id)
        return cls.model_validate(payload)


class UserSessionListResponse(BaseModel):
    items: list[UserSessionResponse] = Field(default_factory=list)
    count: int = 0


class RevokeUserSessionRequest(BaseModel):
    session_id: str
    reason: str | None = None


class CreateUserRequest(BaseModel):
    user_id: str
    username: str | None = None
    display_name: str | None = None
    email: str | None = None
    tenant_id: str | None = None
    status: UserStatusValue = "active"
    roles: list[str] = Field(default_factory=lambda: ["member"])
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateUserRequest(BaseModel):
    username: str | None = None
    display_name: str | None = None
    email: str | None = None
    tenant_id: str | None = None
    metadata: dict[str, Any] | None = None


class UpdateUserStatusRequest(BaseModel):
    status: UserStatusValue
    reason: str | None = None


class UpdateUserRolesRequest(BaseModel):
    roles: list[str] = Field(default_factory=list)
    reason: str | None = None


class AuditEventResponse(BaseModel):
    event_id: str
    actor_user_id: str | None = None
    tenant_id: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    decision: str = "success"
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    created_at: str

    @classmethod
    def from_event(cls, event: AdminAuditEvent) -> "AuditEventResponse":
        return cls.model_validate(event.model_dump(mode="json"))


class AuditEventListResponse(BaseModel):
    items: list[AuditEventResponse] = Field(default_factory=list)
    count: int = 0
    limit: int = 50
    offset: int = 0


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_in_seconds: int
    issuer: str


class AuthTokenResponse(TokenResponse):
    refresh_token: str
    user: UserResponse


class PrincipalResponse(BaseModel):
    user_id: str
    tenant_id: str | None = None
    scopes: list[str] = Field(default_factory=list)
    auth_enabled: bool = True
    user: UserResponse | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    is_admin: bool = False


__all__ = [
    "DemoTokenRequest",
    "AuthRegisterRequest",
    "AuthLoginRequest",
    "AuthRefreshRequest",
    "AuthLogoutRequest",
    "AuthChangePasswordRequest",
    "AdminResetPasswordRequest",
    "AuthErrorResponse",
    "UserResponse",
    "UserListResponse",
    "UserSessionResponse",
    "UserSessionListResponse",
    "RevokeUserSessionRequest",
    "CreateUserRequest",
    "UpdateUserRequest",
    "UpdateUserStatusRequest",
    "UpdateUserRolesRequest",
    "AuditEventResponse",
    "AuditEventListResponse",
    "TokenResponse",
    "AuthTokenResponse",
    "PrincipalResponse",
]
