from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from focus_agent.api.routers.productivity import router
from focus_agent.config import Settings
from focus_agent.repositories.productivity_repository import InMemoryProductivityRepository
from focus_agent.repositories.user_repository import InMemoryUserRepository
from focus_agent.security.tokens import create_access_token
from focus_agent.services.auth import AuthService, SessionRevokedError
from focus_agent.services.productivity import ProductivityService
from focus_agent.services.users import UserService


def _client(
    *, auth_enabled: bool = True
) -> tuple[
    TestClient,
    UserService | None,
    AuthService | None,
    InMemoryUserRepository | None,
]:
    settings = Settings(
        auth_enabled=auth_enabled,
        auth_jwt_secret="disabled-access-token-secret",
        auth_jwt_issuer="focus-agent-disabled-token-test",
    )
    productivity_repository = InMemoryProductivityRepository()
    runtime = SimpleNamespace(
        settings=settings,
        productivity_repository=productivity_repository,
        productivity_service=ProductivityService(productivity_repository),
    )
    user_service = None
    auth_service = None
    user_repository = None
    if auth_enabled:
        user_repository = InMemoryUserRepository()
        user_service = UserService(user_repository, auth_enabled=True)
        auth_service = AuthService(user_repository, settings=settings)
        runtime.user_repository = user_repository
        runtime.user_service = user_service
        runtime.auth_service = auth_service

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    return TestClient(app), user_service, auth_service, user_repository


def test_disabled_users_existing_access_token_is_rejected_and_refresh_sessions_are_revoked() -> (
    None
):
    client, user_service, auth_service, user_repository = _client()
    assert user_service is not None
    assert auth_service is not None
    assert user_repository is not None
    token_pair = auth_service.register(username="member", password="secret123")
    other_token_pair = auth_service.login(username="member", password="secret123")
    headers = {"Authorization": f"Bearer {token_pair.access_token}"}

    before_disable = client.post(
        "/v1/notes",
        headers=headers,
        json={"title": "before", "content": "allowed"},
    )

    assert before_disable.status_code == 201
    user_service.update_user_status("member", status="disabled", reason="offboarding")
    assert user_repository.get_session(token_pair.session.session_id).revoked_at is not None
    assert user_repository.get_session(other_token_pair.session.session_id).revoked_at is not None

    after_disable = client.post(
        "/v1/notes",
        headers=headers,
        json={"title": "after", "content": "must be denied"},
    )

    assert after_disable.status_code == 403
    assert after_disable.json()["detail"] == "User member is not active."
    with pytest.raises(SessionRevokedError):
        auth_service.refresh(token_pair.refresh_token)
    with pytest.raises(SessionRevokedError):
        auth_service.refresh(other_token_pair.refresh_token)


def test_auth_disabled_local_mode_keeps_anonymous_protected_route_compatibility() -> None:
    client, user_service, auth_service, user_repository = _client(auth_enabled=False)

    response = client.post(
        "/v1/notes",
        json={"title": "local", "content": "anonymous mode"},
    )

    assert response.status_code == 201
    assert response.json()["note"]["user_id"] == "anonymous"
    assert user_service is None
    assert auth_service is None
    assert user_repository is None


def test_local_demo_style_access_token_still_bootstraps_persistent_user() -> None:
    client, user_service, _, user_repository = _client()
    assert user_service is not None
    assert user_repository is not None
    token = create_access_token(
        settings=client.app.state.runtime.settings,
        user_id="demo-user",
        scopes=["chat"],
    )

    response = client.post(
        "/v1/notes",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "demo", "content": "compatible"},
    )

    assert response.status_code == 201
    assert user_repository.get_user("demo-user").status == "active"


def test_production_auth_fails_closed_without_persistent_user_state() -> None:
    settings = Settings(
        auth_enabled=True,
        auth_jwt_secret="disabled-access-token-secret",
        auth_jwt_issuer="focus-agent-disabled-token-test",
        app_environment="production",
        database_uri="postgresql://focus-agent.test/runtime",
    )
    productivity_repository = InMemoryProductivityRepository()
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(
        settings=settings,
        productivity_repository=productivity_repository,
        productivity_service=ProductivityService(productivity_repository),
    )
    token = create_access_token(settings=settings, user_id="user-without-auth-state")

    response = TestClient(app).post(
        "/v1/notes",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "denied", "content": "fail closed"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "User authorization state is unavailable."
