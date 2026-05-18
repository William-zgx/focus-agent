from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from focus_agent.core.users import (
    AdminAuditEvent,
    AuditDecision,
    AuditEventListResult,
    User,
    UserListResult,
    UserRole,
    UserStatus,
)
from focus_agent.repositories.user_repository import (
    AuditEventListFilters,
    UserListFilters,
    UserRepository,
)
from focus_agent.security.permissions import ADMIN_ROLE, MEMBER_ROLE, AuthContext, normalize_roles
from focus_agent.security.tokens import Principal


class UserServiceError(ValueError):
    pass


class UserNotFoundError(UserServiceError):
    pass


class UserConflictError(UserServiceError):
    pass


class UserInactiveError(UserServiceError):
    pass


class LastAdminError(UserServiceError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _status_value(status: UserStatus | str) -> str:
    return status.value if isinstance(status, UserStatus) else str(status)


def _normalize_username(username: object) -> str | None:
    if username is None:
        return None
    normalized = str(username).strip().lower()
    return normalized or None


class UserService:
    def __init__(self, repository: UserRepository, *, auth_enabled: bool = True):
        self.repository = repository
        self.auth_enabled = auth_enabled

    def ensure_user_from_principal(
        self,
        principal: Principal,
        *,
        allow_admin_bootstrap: bool = False,
        display_name: str | None = None,
        email: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        bootstrap_admin_user_ids: tuple[str, ...] | set[str] | None = None,
        request_id: str | None = None,
    ) -> User:
        now = _now()
        roles = self._default_roles_for_principal(
            principal,
            allow_admin_bootstrap=allow_admin_bootstrap,
            bootstrap_admin_user_ids=bootstrap_admin_user_ids,
        )
        defaults = User(
            user_id=principal.user_id,
            display_name=display_name or self._display_name_from_principal(principal),
            email=email or self._email_from_principal(principal),
            tenant_id=principal.tenant_id,
            status=UserStatus.ACTIVE,
            roles=list(roles),
            auth_provider="jwt",
            external_subject=principal.user_id,
            created_at=now,
            updated_at=now,
            last_seen_at=now,
            metadata=dict(metadata or {}),
        )
        user = self.repository.ensure_user_from_principal(principal, defaults=defaults)
        if self._principal_is_configured_bootstrap_admin(
            principal,
            bootstrap_admin_user_ids=bootstrap_admin_user_ids,
        ) and ADMIN_ROLE not in set(normalize_roles(user.roles)):
            user = self.repository.save_user(
                user.model_copy(
                    update={
                        "roles": list(normalize_roles((*user.roles, ADMIN_ROLE))),
                        "updated_at": now,
                    }
                )
            )
        self._require_active_for_auth(user)
        if user.last_seen_at != now:
            user = user.model_copy(update={"last_seen_at": now, "updated_at": now})
            user = self.repository.save_user(user)
        return user

    def get_user(self, user_id: str) -> User:
        try:
            return self.repository.get_user(user_id)
        except KeyError as exc:
            raise UserNotFoundError(f"Unknown user: {user_id}") from exc

    def list_users(
        self,
        *,
        filters: UserListFilters | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> UserListResult:
        return self.repository.list_users(
            filters=filters,
            limit=self._bounded_limit(limit),
            offset=max(offset, 0),
        )

    def create_user(
        self,
        *,
        user_id: str,
        username: str | None = None,
        display_name: str | None = None,
        email: str | None = None,
        tenant_id: str | None = None,
        status: UserStatus | str = UserStatus.ACTIVE,
        roles: list[str] | tuple[str, ...] | None = None,
        metadata: Mapping[str, Any] | None = None,
        actor: AuthContext | User | None = None,
        request_id: str | None = None,
    ) -> User:
        now = _now()
        normalized_roles = list(normalize_roles(roles or (UserRole.MEMBER.value,)))
        if not normalized_roles:
            normalized_roles = [MEMBER_ROLE]
        user = User(
            user_id=user_id,
            username=_normalize_username(username),
            display_name=display_name,
            email=email,
            tenant_id=tenant_id,
            status=UserStatus(_status_value(status)),
            roles=normalized_roles,
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
        )
        try:
            created = self.repository.create_user(user)
        except ValueError as exc:
            self._audit(
                actor=actor,
                action="users.create",
                resource_id=user_id,
                decision=AuditDecision.FAILURE,
                reason="user_already_exists",
                request_id=request_id,
            )
            raise UserConflictError(f"User already exists: {user_id}") from exc
        self._audit(
            actor=actor,
            action="users.create",
            resource_id=user_id,
            decision=AuditDecision.SUCCESS,
            metadata={"roles": created.roles, "status": _status_value(created.status)},
            request_id=request_id,
        )
        return created

    def update_user(
        self,
        user_id: str,
        *,
        updates: Mapping[str, Any],
        actor: AuthContext | User | None = None,
        request_id: str | None = None,
    ) -> User:
        user = self.get_user(user_id)
        allowed_updates = {
            key: value
            for key, value in updates.items()
            if key in {"username", "display_name", "email", "tenant_id", "metadata"}
        }
        if not allowed_updates:
            return user
        if "metadata" in allowed_updates and allowed_updates["metadata"] is None:
            allowed_updates["metadata"] = {}
        if "username" in allowed_updates:
            allowed_updates["username"] = _normalize_username(allowed_updates["username"])
        updated = user.model_copy(update={**allowed_updates, "updated_at": _now()})
        try:
            saved = self.repository.save_user(updated)
        except ValueError as exc:
            self._audit(
                actor=actor,
                action="users.update",
                resource_id=user_id,
                decision=AuditDecision.FAILURE,
                reason="user_conflict",
                request_id=request_id,
            )
            raise UserConflictError(
                f"User update conflicts with an existing user: {user_id}"
            ) from exc
        self._audit(
            actor=actor,
            action="users.update",
            resource_id=user_id,
            decision=AuditDecision.SUCCESS,
            metadata={"fields": sorted(allowed_updates)},
            request_id=request_id,
        )
        return saved

    def update_user_status(
        self,
        user_id: str,
        *,
        status: UserStatus | str,
        actor: AuthContext | User | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> User:
        user = self.get_user(user_id)
        next_status = UserStatus(_status_value(status))
        if self._would_remove_active_admin(user, next_status=next_status):
            self._audit_last_admin_denial(
                actor=actor,
                action="users.status",
                resource_id=user_id,
                reason="cannot_disable_last_active_admin",
                request_id=request_id,
            )
            raise LastAdminError("Cannot disable the last active admin user.")
        saved = self.repository.save_user(
            user.model_copy(update={"status": next_status, "updated_at": _now()})
        )
        self._audit(
            actor=actor,
            action="users.status",
            resource_id=user_id,
            decision=AuditDecision.SUCCESS,
            metadata={"status": next_status.value},
            reason=reason,
            request_id=request_id,
        )
        return saved

    def update_user_roles(
        self,
        user_id: str,
        *,
        roles: list[str] | tuple[str, ...],
        actor: AuthContext | User | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> User:
        user = self.get_user(user_id)
        normalized_roles = list(normalize_roles(roles))
        if self._would_remove_last_admin_role(user, normalized_roles):
            self._audit_last_admin_denial(
                actor=actor,
                action="users.roles",
                resource_id=user_id,
                reason="cannot_remove_last_active_admin_role",
                request_id=request_id,
            )
            raise LastAdminError("Cannot remove the last active admin role.")
        saved = self.repository.save_user(
            user.model_copy(update={"roles": normalized_roles, "updated_at": _now()})
        )
        self._audit(
            actor=actor,
            action="users.roles",
            resource_id=user_id,
            decision=AuditDecision.SUCCESS,
            metadata={"roles": normalized_roles},
            reason=reason,
            request_id=request_id,
        )
        return saved

    def record_admin_action(
        self,
        *,
        actor: AuthContext | User | None,
        action: str,
        resource_id: str | None = None,
        decision: AuditDecision = AuditDecision.SUCCESS,
        reason: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        self._audit(
            actor=actor,
            action=action,
            resource_id=resource_id,
            decision=decision,
            reason=reason,
            metadata=metadata,
            request_id=request_id,
        )

    def list_audit_events(
        self,
        *,
        filters: AuditEventListFilters | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AuditEventListResult:
        return self.repository.list_audit_events(
            filters=filters,
            limit=self._bounded_limit(limit),
            offset=max(offset, 0),
        )

    def _default_roles_for_principal(
        self,
        principal: Principal,
        *,
        allow_admin_bootstrap: bool,
        bootstrap_admin_user_ids: tuple[str, ...] | set[str] | None,
    ) -> tuple[str, ...]:
        if self._principal_is_configured_bootstrap_admin(
            principal,
            bootstrap_admin_user_ids=bootstrap_admin_user_ids,
        ):
            return (ADMIN_ROLE,)
        if (
            allow_admin_bootstrap
            and self.auth_enabled
            and principal.user_id != "anonymous"
            and self.repository.list_users(limit=1, offset=0).count == 0
        ):
            return (ADMIN_ROLE,)
        return (MEMBER_ROLE,)

    def _principal_is_configured_bootstrap_admin(
        self,
        principal: Principal,
        *,
        bootstrap_admin_user_ids: tuple[str, ...] | set[str] | None,
    ) -> bool:
        if not self.auth_enabled or principal.user_id == "anonymous":
            return False
        return principal.user_id in set(bootstrap_admin_user_ids or ())

    def _require_active_for_auth(self, user: User) -> None:
        if _status_value(user.status) != UserStatus.ACTIVE.value:
            raise UserInactiveError(f"User {user.user_id} is not active.")

    def _would_remove_active_admin(self, user: User, *, next_status: UserStatus) -> bool:
        if _status_value(user.status) != UserStatus.ACTIVE.value:
            return False
        if ADMIN_ROLE not in set(normalize_roles(user.roles)):
            return False
        if next_status == UserStatus.ACTIVE:
            return False
        return self.repository.count_active_admins() <= 1

    def _would_remove_last_admin_role(self, user: User, next_roles: list[str]) -> bool:
        if _status_value(user.status) != UserStatus.ACTIVE.value:
            return False
        if ADMIN_ROLE not in set(normalize_roles(user.roles)):
            return False
        if ADMIN_ROLE in set(normalize_roles(next_roles)):
            return False
        return self.repository.count_active_admins() <= 1

    def _audit_last_admin_denial(
        self,
        *,
        actor: AuthContext | User | None,
        action: str,
        resource_id: str,
        reason: str,
        request_id: str | None,
    ) -> None:
        self._audit(
            actor=actor,
            action=action,
            resource_id=resource_id,
            decision=AuditDecision.DENY,
            reason=reason,
            request_id=request_id,
        )

    def _audit(
        self,
        *,
        actor: AuthContext | User | None,
        action: str,
        resource_id: str | None = None,
        decision: AuditDecision = AuditDecision.SUCCESS,
        reason: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        actor_user, tenant_id = self._actor_fields(actor)
        self.repository.record_audit_event(
            AdminAuditEvent(
                event_id=str(uuid4()),
                actor_user_id=actor_user,
                tenant_id=tenant_id,
                action=action,
                resource_type="user",
                resource_id=resource_id,
                decision=decision,
                reason=reason,
                metadata=dict(metadata or {}),
                request_id=request_id,
                created_at=_now(),
            )
        )

    @staticmethod
    def _actor_fields(actor: AuthContext | User | None) -> tuple[str | None, str | None]:
        if actor is None:
            return None, None
        if isinstance(actor, AuthContext):
            return actor.user.user_id, actor.user.tenant_id
        return actor.user_id, actor.tenant_id

    @staticmethod
    def _display_name_from_principal(principal: Principal) -> str | None:
        for key in ("name", "preferred_username", "email"):
            value = principal.claims.get(key)
            if value:
                return str(value)
        return None

    @staticmethod
    def _email_from_principal(principal: Principal) -> str | None:
        value = principal.claims.get("email")
        return str(value) if value else None

    @staticmethod
    def _bounded_limit(limit: int) -> int:
        return min(max(limit, 0), 200)


__all__ = [
    "LastAdminError",
    "UserConflictError",
    "UserInactiveError",
    "UserNotFoundError",
    "UserService",
    "UserServiceError",
]
