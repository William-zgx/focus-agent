from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from focus_agent.api.main import create_app
from focus_agent.config import Settings
from focus_agent.repositories.user_repository import InMemoryUserRepository
from focus_agent.security.passwords import PBKDF2_ALGORITHM, verify_password
from focus_agent.services.auth import AuthService
from focus_agent.services.users import UserService


def _refresh_token_hash(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()


def _with_stub_frontend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")
    monkeypatch.setenv("AUTH_ENABLED", "true")


def _build_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[TestClient, InMemoryUserRepository]:
    _with_stub_frontend(monkeypatch, tmp_path)
    settings = Settings(
        auth_enabled=True,
        auth_demo_tokens_enabled=False,
        auth_jwt_secret="auth-accounts-secret",
        auth_jwt_issuer="focus-agent-test",
    )
    repo = InMemoryUserRepository()
    app = create_app()
    app.state.runtime = SimpleNamespace(
        settings=settings,
        user_repository=repo,
        user_service=UserService(repo, auth_enabled=True),
        auth_service=AuthService(repo, settings=settings),
    )
    return TestClient(app), repo


def test_register_hashes_password_sets_cookies_and_me_accepts_cookie(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, repo = _build_client(monkeypatch, tmp_path)

    response = client.post(
        "/v1/auth/register",
        json={"username": "Researcher", "password": "secret123", "display_name": "Researcher"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["user_id"] == "researcher"
    assert "focus_agent_access=" in response.headers["set-cookie"]
    assert "focus_agent_refresh=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    user = repo.get_user_by_username("researcher")
    assert user is not None
    assert user.password_hash is not None
    assert user.password_hash.startswith(f"{PBKDF2_ALGORITHM}$")
    assert verify_password("secret123", user.password_hash)

    me = client.get("/v1/auth/me")

    assert me.status_code == 200
    assert me.json()["user_id"] == "researcher"
    assert me.json()["user"]["user_id"] == "researcher"


def test_login_errors_use_stable_codes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client, _ = _build_client(monkeypatch, tmp_path)

    weak = client.post("/v1/auth/register", json={"username": "weak", "password": "short"})
    assert weak.status_code == 400
    assert weak.json()["data"]["code"] == "weak_password"

    created = client.post("/v1/auth/register", json={"username": "taken", "password": "secret123"})
    assert created.status_code == 201

    duplicate = client.post(
        "/v1/auth/register", json={"username": "TAKEN", "password": "secret123"}
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["data"]["code"] == "username_taken"

    invalid = client.post("/v1/auth/login", json={"username": "taken", "password": "wrong123"})
    assert invalid.status_code == 401
    assert invalid.json()["data"]["code"] == "invalid_credentials"


def test_refresh_logout_and_revoked_session_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, repo = _build_client(monkeypatch, tmp_path)
    registered = client.post(
        "/v1/auth/register", json={"username": "sessioned", "password": "secret123"}
    )
    refresh_token = registered.json()["refresh_token"]

    refreshed = client.post("/v1/auth/refresh", json={})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]

    logout = client.post("/v1/auth/logout", json={})
    assert logout.status_code == 200
    assert repo.get_session(_refresh_token_hash(refresh_token)).revoked_at is not None

    revoked = client.post("/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert revoked.status_code == 401
    assert revoked.json()["data"]["code"] == "session_revoked"


def test_change_password_keeps_current_session_and_revokes_other_sessions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, repo = _build_client(monkeypatch, tmp_path)
    registered = client.post(
        "/v1/auth/register", json={"username": "changer", "password": "secret123"}
    )
    current_refresh_token = registered.json()["refresh_token"]
    other = client.post("/v1/auth/login", json={"username": "changer", "password": "secret123"})
    other_refresh_token = other.json()["refresh_token"]

    mismatch = client.post(
        "/v1/auth/change-password",
        json={"current_password": "wrong123", "new_password": "secret456"},
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["data"]["code"] == "password_mismatch"

    changed = client.post(
        "/v1/auth/change-password",
        cookies={"focus_agent_refresh": current_refresh_token},
        json={"current_password": "secret123", "new_password": "secret456"},
    )
    assert changed.status_code == 200
    assert repo.get_session(_refresh_token_hash(current_refresh_token)).revoked_at is None
    assert repo.get_session(_refresh_token_hash(other_refresh_token)).revoked_at is not None

    old_login = client.post("/v1/auth/login", json={"username": "changer", "password": "secret123"})
    assert old_login.status_code == 401
    new_login = client.post("/v1/auth/login", json={"username": "changer", "password": "secret456"})
    assert new_login.status_code == 200


def test_auth_sessions_api_lists_and_revokes_current_user_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, repo = _build_client(monkeypatch, tmp_path)
    registered = client.post(
        "/v1/auth/register", json={"username": "sessions", "password": "secret123"}
    )
    refresh_token = registered.json()["refresh_token"]
    session_id = _refresh_token_hash(refresh_token)

    listed = client.get("/v1/auth/sessions")

    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["items"][0]["session_id"] == session_id
    assert listed.json()["items"][0]["current"] is True

    revoked = client.post(f"/v1/auth/sessions/{session_id}/revoke")

    assert revoked.status_code == 200
    assert repo.get_session(session_id).revoked_at is not None
