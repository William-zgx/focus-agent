from __future__ import annotations

import pytest

from focus_agent.repositories.user_repository import AuditEventListFilters, InMemoryUserRepository
from focus_agent.security.tokens import Principal
from focus_agent.services.users import LastAdminError, UserInactiveError, UserService


def test_demo_bootstrap_grants_admin_only_to_first_authenticated_user() -> None:
    repo = InMemoryUserRepository()
    service = UserService(repo, auth_enabled=True)

    first = service.ensure_user_from_principal(
        Principal(user_id="demo-admin"),
        allow_admin_bootstrap=True,
    )
    second = service.ensure_user_from_principal(
        Principal(user_id="demo-member"),
        allow_admin_bootstrap=True,
    )

    assert first.roles == ["admin"]
    assert second.roles == ["member"]


def test_configured_bootstrap_admin_id_is_honored_after_users_exist() -> None:
    repo = InMemoryUserRepository()
    service = UserService(repo, auth_enabled=True)
    service.ensure_user_from_principal(Principal(user_id="member-1"))

    admin = service.ensure_user_from_principal(
        Principal(user_id="ops-admin"),
        bootstrap_admin_user_ids=("ops-admin",),
    )

    assert admin.roles == ["admin"]
    assert repo.count_active_admins() == 1


def test_auth_disabled_anonymous_does_not_bootstrap_admin() -> None:
    repo = InMemoryUserRepository()
    service = UserService(repo, auth_enabled=False)

    anonymous = service.ensure_user_from_principal(
        Principal(user_id="anonymous"),
        allow_admin_bootstrap=True,
    )

    assert anonymous.roles == ["member"]
    assert repo.count_active_admins() == 0


def test_disabled_user_is_rejected_for_auth_context() -> None:
    repo = InMemoryUserRepository()
    service = UserService(repo)
    service.ensure_user_from_principal(Principal(user_id="member-1"))
    service.update_user_status("member-1", status="disabled")

    with pytest.raises(UserInactiveError):
        service.ensure_user_from_principal(Principal(user_id="member-1"))


def test_service_rejects_disabling_last_active_admin() -> None:
    repo = InMemoryUserRepository()
    service = UserService(repo)
    service.create_user(user_id="admin-1", roles=["admin"])

    with pytest.raises(LastAdminError):
        service.update_user_status("admin-1", status="disabled")

    denied = service.list_audit_events(filters=AuditEventListFilters(decision="deny"))
    assert denied.count == 1
    assert denied.items[0].reason == "cannot_disable_last_active_admin"

    service.create_user(user_id="admin-2", roles=["admin"])
    disabled = service.update_user_status("admin-1", status="disabled")
    assert disabled.status == "disabled"
    assert repo.count_active_admins() == 1


def test_service_rejects_removing_last_active_admin_role() -> None:
    repo = InMemoryUserRepository()
    service = UserService(repo)
    service.create_user(user_id="admin-1", roles=["admin"])

    with pytest.raises(LastAdminError):
        service.update_user_roles("admin-1", roles=["member"])

    denied = service.list_audit_events(filters=AuditEventListFilters(decision="deny"))
    assert denied.count == 1
    assert denied.items[0].reason == "cannot_remove_last_active_admin_role"

    service.create_user(user_id="admin-2", roles=["admin"])
    updated = service.update_user_roles("admin-1", roles=["member"])
    assert updated.roles == ["member"]
    assert repo.count_active_admins() == 1
