from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from focus_agent.core.users import AdminAuditEvent, AuditDecision, User, UserSession, UserStatus
from focus_agent.repositories.sqlite_user_repository import SQLiteUserRepository
from focus_agent.repositories.user_repository import (
    AuditEventListFilters,
    InMemoryUserRepository,
    LastActiveAdminError,
    UserListFilters,
    UserRepository,
)
from focus_agent.security.tokens import Principal


def _user(user_id: str, *, roles: list[str] | None = None, status: str = "active") -> User:
    return User(
        user_id=user_id,
        username=user_id.replace("-", "_"),
        display_name=f"User {user_id}",
        email=f"{user_id}@example.com",
        tenant_id="tenant-a",
        status=UserStatus(status),
        roles=roles or ["member"],
        created_at=f"2026-04-29T00:00:0{len(user_id)}Z",
        updated_at=f"2026-04-29T00:00:0{len(user_id)}Z",
        metadata={"source": "test"},
    )


def _repo(kind: str, tmp_path: Path) -> UserRepository:
    if kind == "sqlite":
        return SQLiteUserRepository(str(tmp_path / "users.sqlite3"))
    return InMemoryUserRepository()


def _session(session_id: str, *, user_id: str = "user-1", created_suffix: str = "1") -> UserSession:
    return UserSession(
        session_id=session_id,
        user_id=user_id,
        refresh_token_hash=f"hash-{session_id}",
        created_at=f"2026-04-29T00:10:0{created_suffix}Z",
        updated_at=f"2026-04-29T00:10:0{created_suffix}Z",
        expires_at="2026-04-30T00:00:00Z",
        last_seen_at=f"2026-04-29T00:10:0{created_suffix}Z",
        user_agent="pytest",
        ip_address="127.0.0.1",
        metadata={"source": "test"},
    )


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_user_repository_crud_filters_and_admin_count(kind: str, tmp_path: Path) -> None:
    repo = _repo(kind, tmp_path)

    admin = repo.create_user(_user("admin-1", roles=["admin"]))
    member = repo.create_user(_user("member-1"))
    repo.save_user(member.model_copy(update={"display_name": "Member Renamed"}))

    assert repo.get_user(admin.user_id).roles == ["admin"]
    assert repo.get_user("member-1").display_name == "Member Renamed"
    assert repo.get_user_by_username("MEMBER_1").user_id == "member-1"
    assert repo.list_users(filters=UserListFilters(role="admin")).count == 1
    assert repo.list_users(filters=UserListFilters(query="renamed")).items[0].user_id == "member-1"
    assert repo.list_users(filters=UserListFilters(query="member_1")).items[0].user_id == "member-1"
    assert repo.count_active_admins() == 1


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_user_repository_concurrent_admin_demotion_preserves_one_admin(
    kind: str, tmp_path: Path
) -> None:
    repo = _repo(kind, tmp_path)
    repo.create_user(_user("admin-1", roles=["admin"]))
    repo.create_user(_user("admin-2", roles=["admin"]))
    barrier = Barrier(2)

    def demote(user_id: str, *, disable: bool) -> User | LastActiveAdminError:
        user = repo.get_user(user_id)
        update = {"status": UserStatus.DISABLED} if disable else {"roles": ["member"]}
        barrier.wait()
        try:
            return repo.save_user_preserving_last_active_admin(user.model_copy(update=update))
        except LastActiveAdminError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            executor.submit(demote, "admin-1", disable=True),
            executor.submit(demote, "admin-2", disable=False),
        ]
        outcomes = [result.result() for result in results]

    assert sum(isinstance(outcome, User) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, LastActiveAdminError) for outcome in outcomes) == 1
    assert repo.count_active_admins() == 1


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_user_repository_ensure_from_principal_and_audit_filters(kind: str, tmp_path: Path) -> None:
    repo = _repo(kind, tmp_path)
    principal = Principal(user_id="new-user", tenant_id="tenant-b")
    ensured = repo.ensure_user_from_principal(
        principal,
        defaults=_user("new-user", roles=["member"]),
    )

    assert ensured.user_id == "new-user"
    assert repo.ensure_user_from_principal(principal, defaults=_user("ignored")) == ensured

    repo.record_audit_event(
        AdminAuditEvent(
            event_id="audit-1",
            actor_user_id="admin-1",
            tenant_id="tenant-b",
            action="users.create",
            resource_type="user",
            resource_id="new-user",
            decision=AuditDecision.SUCCESS,
            created_at="2026-04-29T00:01:00Z",
        )
    )
    repo.record_audit_event(
        AdminAuditEvent(
            event_id="audit-2",
            actor_user_id="admin-1",
            tenant_id="tenant-b",
            action="users.status",
            resource_type="user",
            resource_id="new-user",
            decision=AuditDecision.DENY,
            reason="last_admin",
            created_at="2026-04-29T00:02:00Z",
        )
    )

    denied = repo.list_audit_events(filters=AuditEventListFilters(decision="deny"))

    assert denied.count == 1
    assert denied.items[0].event_id == "audit-2"


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_user_repository_sessions_create_save_list_and_revoke(kind: str, tmp_path: Path) -> None:
    repo = _repo(kind, tmp_path)
    repo.create_user(_user("user-1"))
    repo.create_user(_user("user-2"))

    older = repo.create_session(_session("session-older", created_suffix="1"))
    current = repo.create_session(_session("session-current", created_suffix="2"))
    repo.create_session(_session("session-other", user_id="user-2", created_suffix="3"))

    saved = repo.save_session(older.model_copy(update={"last_seen_at": "2026-04-29T00:11:00Z"}))

    assert saved.last_seen_at == "2026-04-29T00:11:00Z"
    assert repo.get_session("session-older").last_seen_at == "2026-04-29T00:11:00Z"
    assert [item.session_id for item in repo.list_sessions(user_id="user-1")] == [
        current.session_id,
        older.session_id,
    ]

    revoked_count = repo.revoke_other_sessions(
        user_id="user-1",
        current_session_id="session-current",
        revoked_at="2026-04-29T00:12:00Z",
    )

    assert revoked_count == 1
    assert [item.session_id for item in repo.list_sessions(user_id="user-1")] == ["session-current"]
    assert repo.get_session("session-older").revoked_at == "2026-04-29T00:12:00Z"
    assert [
        item.session_id for item in repo.list_sessions(user_id="user-1", include_revoked=True)
    ] == [
        current.session_id,
        older.session_id,
    ]

    revoked_current = repo.revoke_session(
        "session-current",
        revoked_at="2026-04-29T00:13:00Z",
    )

    assert revoked_current.revoked_at == "2026-04-29T00:13:00Z"
    assert repo.list_sessions(user_id="user-1") == []
