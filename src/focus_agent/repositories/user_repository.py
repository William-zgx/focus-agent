from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from focus_agent.core.users import (
    AdminAuditEvent,
    AuditEventListResult,
    User,
    UserListResult,
    UserSession,
)
from focus_agent.security.tokens import Principal


@dataclass(frozen=True, slots=True)
class UserListFilters:
    status: str | None = None
    role: str | None = None
    tenant_id: str | None = None
    query: str | None = None


@dataclass(frozen=True, slots=True)
class AuditEventListFilters:
    actor_user_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    decision: str | None = None


class UserRepository(ABC):
    @abstractmethod
    def create_user(self, user: User) -> User:
        raise NotImplementedError

    @abstractmethod
    def save_user(self, user: User) -> User:
        raise NotImplementedError

    @abstractmethod
    def get_user(self, user_id: str) -> User:
        raise NotImplementedError

    @abstractmethod
    def get_user_or_none(self, user_id: str) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def get_user_by_username(self, username: str) -> User | None:
        raise NotImplementedError

    @abstractmethod
    def list_users(
        self,
        *,
        filters: UserListFilters | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> UserListResult:
        raise NotImplementedError

    @abstractmethod
    def ensure_user_from_principal(self, principal: Principal, *, defaults: User) -> User:
        raise NotImplementedError

    @abstractmethod
    def count_active_admins(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def create_session(self, session: UserSession) -> UserSession:
        raise NotImplementedError

    @abstractmethod
    def save_session(self, session: UserSession) -> UserSession:
        raise NotImplementedError

    @abstractmethod
    def get_session(self, session_id: str) -> UserSession:
        raise NotImplementedError

    @abstractmethod
    def list_sessions(
        self,
        *,
        user_id: str | None = None,
        include_revoked: bool = False,
    ) -> list[UserSession]:
        raise NotImplementedError

    @abstractmethod
    def revoke_session(self, session_id: str, *, revoked_at: str) -> UserSession:
        raise NotImplementedError

    @abstractmethod
    def revoke_other_sessions(
        self,
        *,
        user_id: str,
        current_session_id: str,
        revoked_at: str,
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    def record_audit_event(self, event: AdminAuditEvent) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_audit_events(
        self,
        *,
        filters: AuditEventListFilters | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AuditEventListResult:
        raise NotImplementedError


class InMemoryUserRepository(UserRepository):
    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._sessions: dict[str, UserSession] = {}
        self._audit_events: list[AdminAuditEvent] = []

    def create_user(self, user: User) -> User:
        if user.user_id in self._users:
            raise ValueError(f"User already exists: {user.user_id}")
        if user.username and self.get_user_by_username(user.username) is not None:
            raise ValueError(f"Username already exists: {user.username}")
        self._users[user.user_id] = user
        return user

    def save_user(self, user: User) -> User:
        if user.user_id not in self._users:
            raise KeyError(f"Unknown user: {user.user_id}")
        existing = self.get_user_by_username(user.username or "")
        if existing is not None and existing.user_id != user.user_id:
            raise ValueError(f"Username already exists: {user.username}")
        self._users[user.user_id] = user
        return user

    def get_user(self, user_id: str) -> User:
        user = self.get_user_or_none(user_id)
        if user is None:
            raise KeyError(f"Unknown user: {user_id}")
        return user

    def get_user_or_none(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def get_user_by_username(self, username: str) -> User | None:
        normalized = username.lower()
        return next(
            (
                user
                for user in self._users.values()
                if user.username is not None and user.username.lower() == normalized
            ),
            None,
        )

    def list_users(
        self,
        *,
        filters: UserListFilters | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> UserListResult:
        items = list(self._users.values())
        items = _filter_users(items, filters)
        items.sort(key=lambda user: (user.created_at, user.user_id), reverse=True)
        return UserListResult(items=items[offset : offset + limit], count=len(items), limit=limit, offset=offset)

    def ensure_user_from_principal(self, principal: Principal, *, defaults: User) -> User:
        existing = self.get_user_or_none(principal.user_id)
        if existing is not None:
            return existing
        return self.create_user(defaults)

    def count_active_admins(self) -> int:
        return sum(
            1
            for user in self._users.values()
            if user.status == "active" and "admin" in set(user.roles)
        )

    def create_session(self, session: UserSession) -> UserSession:
        if session.session_id in self._sessions:
            raise ValueError(f"User session already exists: {session.session_id}")
        self._sessions[session.session_id] = session
        return session

    def save_session(self, session: UserSession) -> UserSession:
        if session.session_id not in self._sessions:
            raise KeyError(f"Unknown user session: {session.session_id}")
        self._sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> UserSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Unknown user session: {session_id}")
        return session

    def list_sessions(
        self,
        *,
        user_id: str | None = None,
        include_revoked: bool = False,
    ) -> list[UserSession]:
        sessions = list(self._sessions.values())
        if user_id is not None:
            sessions = [session for session in sessions if session.user_id == user_id]
        if not include_revoked:
            sessions = [session for session in sessions if session.revoked_at is None]
        sessions.sort(key=lambda session: (session.created_at, session.session_id), reverse=True)
        return sessions

    def revoke_session(self, session_id: str, *, revoked_at: str) -> UserSession:
        session = self.get_session(session_id)
        revoked = session.model_copy(update={"revoked_at": session.revoked_at or revoked_at})
        self._sessions[session_id] = revoked
        return revoked

    def revoke_other_sessions(
        self,
        *,
        user_id: str,
        current_session_id: str,
        revoked_at: str,
    ) -> int:
        revoked = 0
        for session_id, session in list(self._sessions.items()):
            if (
                session.user_id == user_id
                and session.session_id != current_session_id
                and session.revoked_at is None
            ):
                self._sessions[session_id] = session.model_copy(update={"revoked_at": revoked_at})
                revoked += 1
        return revoked

    def record_audit_event(self, event: AdminAuditEvent) -> None:
        self._audit_events.append(event)

    def list_audit_events(
        self,
        *,
        filters: AuditEventListFilters | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AuditEventListResult:
        items = list(self._audit_events)
        items = _filter_audit_events(items, filters)
        items.sort(key=lambda event: (event.created_at, event.event_id), reverse=True)
        return AuditEventListResult(
            items=items[offset : offset + limit],
            count=len(items),
            limit=limit,
            offset=offset,
        )


def _filter_users(items: list[User], filters: UserListFilters | None) -> list[User]:
    if filters is None:
        return items
    filtered = items
    if filters.status:
        filtered = [user for user in filtered if user.status == filters.status]
    if filters.role:
        filtered = [user for user in filtered if filters.role in set(user.roles)]
    if filters.tenant_id:
        filtered = [user for user in filtered if user.tenant_id == filters.tenant_id]
    if filters.query:
        query = filters.query.lower()
        filtered = [
            user
            for user in filtered
            if query in user.user_id.lower()
            or query in (user.username or "").lower()
            or query in (user.display_name or "").lower()
            or query in (user.email or "").lower()
        ]
    return filtered


def _filter_audit_events(
    items: list[AdminAuditEvent], filters: AuditEventListFilters | None
) -> list[AdminAuditEvent]:
    if filters is None:
        return items
    filtered = items
    if filters.actor_user_id:
        filtered = [event for event in filtered if event.actor_user_id == filters.actor_user_id]
    if filters.resource_type:
        filtered = [event for event in filtered if event.resource_type == filters.resource_type]
    if filters.resource_id:
        filtered = [event for event in filtered if event.resource_id == filters.resource_id]
    if filters.decision:
        filtered = [event for event in filtered if event.decision == filters.decision]
    return filtered


__all__ = [
    "AuditEventListFilters",
    "InMemoryUserRepository",
    "UserListFilters",
    "UserRepository",
]
