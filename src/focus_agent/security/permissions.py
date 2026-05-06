from __future__ import annotations

from dataclasses import dataclass

from focus_agent.core.users import User
from focus_agent.security.tokens import Principal


ADMIN_ROLE = "admin"
MEMBER_ROLE = "member"
VIEWER_ROLE = "viewer"

ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    ADMIN_ROLE: (
        "app:use",
        "users:read",
        "users:create",
        "users:update",
        "users:status",
        "users:roles",
        "audit:read",
        "memory:read",
        "memory:audit",
        "memory:forget",
    ),
    MEMBER_ROLE: ("app:use",),
    VIEWER_ROLE: ("app:read",),
}


@dataclass(frozen=True, slots=True)
class AuthContext:
    principal: Principal
    user: User
    permissions: tuple[str, ...]
    is_admin: bool = False


def normalize_roles(roles: list[str] | tuple[str, ...] | set[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_role in roles:
        role = str(raw_role).strip().lower()
        if role and role not in normalized:
            normalized.append(role)
    return tuple(normalized)


def permissions_for_roles(roles: list[str] | tuple[str, ...] | set[str]) -> tuple[str, ...]:
    permissions: list[str] = []
    for role in normalize_roles(roles):
        for permission in ROLE_PERMISSIONS.get(role, ()):
            if permission not in permissions:
                permissions.append(permission)
    return tuple(permissions)


def is_admin_role(roles: list[str] | tuple[str, ...] | set[str]) -> bool:
    return ADMIN_ROLE in normalize_roles(roles)


__all__ = [
    "ADMIN_ROLE",
    "AuthContext",
    "MEMBER_ROLE",
    "ROLE_PERMISSIONS",
    "VIEWER_ROLE",
    "is_admin_role",
    "normalize_roles",
    "permissions_for_roles",
]
