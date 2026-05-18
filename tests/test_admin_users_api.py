from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from focus_agent.api.main import create_app
from focus_agent.config import Settings
from focus_agent.repositories.user_repository import InMemoryUserRepository
from focus_agent.security.passwords import verify_password
from focus_agent.security.tokens import create_access_token
from focus_agent.services.auth import AuthService
from focus_agent.services.users import UserService


def _with_stub_frontend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")


def _build_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    auth_enabled: bool = True,
    database_uri: str | None = None,
    app_environment: str = "development",
) -> tuple[TestClient, Settings, UserService, InMemoryUserRepository]:
    _with_stub_frontend(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_ENABLED", "true" if auth_enabled else "false")
    settings = Settings(
        auth_enabled=auth_enabled,
        auth_demo_tokens_enabled=True,
        auth_jwt_secret="admin-users-secret",
        auth_jwt_issuer="focus-agent-test",
        database_uri=database_uri,
        app_environment=app_environment,
    )
    repo = InMemoryUserRepository()
    service = UserService(repo, auth_enabled=auth_enabled)
    app = create_app()
    app.state.runtime = SimpleNamespace(
        settings=settings,
        user_repository=repo,
        user_service=service,
        auth_service=AuthService(repo, settings=settings),
    )
    return TestClient(app), settings, service, repo


def _headers(settings: Settings, user_id: str, *, scopes: list[str] | None = None) -> dict[str, str]:
    token = create_access_token(
        settings=settings,
        user_id=user_id,
        scopes=scopes or ["users:read", "users:create", "users:update"],
    )
    return {"Authorization": f"Bearer {token}"}


def test_admin_user_routes_use_persistent_roles_not_jwt_scopes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, settings, service, _ = _build_client(monkeypatch, tmp_path)
    service.create_user(user_id="admin-1", roles=["admin"])
    service.create_user(user_id="member-1", roles=["member"])

    member_response = client.get(
        "/v1/admin/users",
        headers=_headers(settings, "member-1", scopes=["admin", "users:read"]),
    )
    assert member_response.status_code == 403

    admin_headers = _headers(settings, "admin-1")
    created = client.post(
        "/v1/admin/users",
        headers=admin_headers,
        json={
            "user_id": "member-2",
            "display_name": "Member Two",
            "email": "member-2@example.com",
            "roles": ["member"],
        },
    )
    assert created.status_code == 201
    assert created.json()["user_id"] == "member-2"

    listed = client.get("/v1/admin/users?role=member", headers=admin_headers)
    assert listed.status_code == 200
    assert {item["user_id"] for item in listed.json()["items"]} >= {"member-1", "member-2"}

    patched = client.patch(
        "/v1/admin/users/member-2",
        headers=admin_headers,
        json={"display_name": "Member Renamed", "metadata": {"team": "research"}},
    )
    assert patched.status_code == 200
    assert patched.json()["metadata"] == {"team": "research"}

    roles = client.put(
        "/v1/admin/users/member-2/roles",
        headers=admin_headers,
        json={"roles": ["viewer"], "reason": "access review"},
    )
    assert roles.status_code == 200
    assert roles.json()["roles"] == ["viewer"]

    disabled = client.post(
        "/v1/admin/users/member-2/status",
        headers=admin_headers,
        json={"status": "disabled", "reason": "offboarding"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"

    audit = client.get("/v1/admin/audit-events", headers=admin_headers)
    assert audit.status_code == 200
    assert audit.json()["count"] >= 4


def test_admin_background_jobs_summary_requires_admin_and_reports_warnings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, settings, service, _ = _build_client(monkeypatch, tmp_path)
    service.create_user(user_id="admin-1", roles=["admin"])
    service.create_user(user_id="member-1", roles=["member"])

    class BackgroundWork:
        def snapshot(self):
            return {
                "job_pending_total": 1,
                "job_retrying_total": 2,
                "job_dead_lettered_total": 1,
                "job_oldest_pending_seconds": 1200,
            }

    client.app.state.runtime.background_work = BackgroundWork()
    client.app.state.runtime.settings.background_job_old_pending_seconds = 900.0

    member_response = client.get(
        "/v1/admin/background-jobs/summary",
        headers=_headers(settings, "member-1", scopes=["admin"]),
    )
    assert member_response.status_code == 403

    response = client.get(
        "/v1/admin/background-jobs/summary",
        headers=_headers(settings, "admin-1"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["ready"] is False
    assert body["metrics"]["job_retrying_total"] == 2
    assert body["metrics"]["job_dead_lettered_total"] == 1
    assert "dead_lettered=1" in body["warnings"]
    assert "oldest_pending_seconds=1200" in body["warnings"]


def test_admin_can_reset_password_and_revoke_user_sessions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, settings, service, repo = _build_client(monkeypatch, tmp_path)
    service.create_user(user_id="admin-1", roles=["admin"])
    admin_headers = _headers(settings, "admin-1")
    registered = client.post("/v1/auth/register", json={"username": "target", "password": "secret123"})
    user_id = registered.json()["user"]["user_id"]

    sessions = client.get(f"/v1/admin/users/{user_id}/sessions", headers=admin_headers)
    assert sessions.status_code == 200
    assert sessions.json()["count"] == 1
    session_id = sessions.json()["items"][0]["session_id"]

    revoked = client.post(
        f"/v1/admin/users/{user_id}/sessions/revoke",
        headers=admin_headers,
        json={"session_id": session_id, "reason": "manual review"},
    )
    assert revoked.status_code == 200
    assert repo.get_session(session_id).revoked_at is not None

    reset = client.post(
        f"/v1/admin/users/{user_id}/password",
        headers=admin_headers,
        json={"new_password": "secret456", "reason": "support request"},
    )

    assert reset.status_code == 200
    assert verify_password("secret456", repo.get_user(user_id).password_hash)


def test_auth_me_returns_persistent_user_context_and_rejects_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, settings, service, _ = _build_client(monkeypatch, tmp_path)
    service.create_user(user_id="admin-1", roles=["admin"])
    service.create_user(user_id="member-1", roles=["member"])

    me = client.get("/v1/auth/me", headers=_headers(settings, "admin-1"))

    assert me.status_code == 200
    body = me.json()
    assert body["user_id"] == "admin-1"
    assert body["user"]["user_id"] == "admin-1"
    assert body["roles"] == ["admin"]
    assert "users:read" in body["permissions"]
    assert body["is_admin"] is True

    service.update_user_status("member-1", status="disabled")
    disabled = client.get("/v1/auth/me", headers=_headers(settings, "member-1"))
    assert disabled.status_code == 403


def test_demo_token_bootstraps_first_local_user_as_admin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, _, _, repo = _build_client(monkeypatch, tmp_path)

    response = client.post("/v1/auth/demo-token", json={"user_id": "demo-1"})

    assert response.status_code == 200
    assert repo.get_user("demo-1").roles == ["admin"]


def test_demo_token_bootstraps_first_dev_database_user_as_admin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, _, _, repo = _build_client(
        monkeypatch,
        tmp_path,
        database_uri="postgresql://focus-agent.test/runtime",
    )

    response = client.post("/v1/auth/demo-token", json={"user_id": "demo-db-1"})

    assert response.status_code == 200
    assert repo.get_user("demo-db-1").roles == ["admin"]


def test_demo_token_does_not_implicitly_bootstrap_production_database_user_as_admin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, _, _, repo = _build_client(
        monkeypatch,
        tmp_path,
        database_uri="postgresql://focus-agent.test/runtime",
        app_environment="production",
    )

    response = client.post("/v1/auth/demo-token", json={"user_id": "prod-user-1"})

    assert response.status_code == 200
    assert repo.get_user("prod-user-1").roles == ["member"]


def test_auth_disabled_anonymous_does_not_receive_admin_permissions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, _, _, repo = _build_client(monkeypatch, tmp_path, auth_enabled=False)

    response = client.get("/v1/admin/users")

    assert response.status_code == 403
    anonymous = repo.get_user("anonymous")
    assert anonymous.roles == ["member"]
