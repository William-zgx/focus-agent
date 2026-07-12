from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from focus_agent.api.deps import get_current_principal
from focus_agent.api.middleware import (
    CSRF_TOKEN_COOKIE,
    CSRF_TOKEN_HEADER,
    configure_middleware,
)
from focus_agent.config import Settings
from focus_agent.config_parts.auth import _validate_non_development_security
from focus_agent.repositories.user_repository import InMemoryUserRepository
from focus_agent.security.tokens import Principal, create_access_token


def _csrf_app(settings: Settings) -> tuple[TestClient, list[str]]:
    mutations: list[str] = []
    app = FastAPI()
    app.state.runtime = SimpleNamespace(
        settings=settings,
        user_repository=InMemoryUserRepository(),
    )

    @app.api_route("/mutation", methods=["POST", "PUT", "PATCH", "DELETE"])
    def mutation(
        principal: Principal = Depends(get_current_principal),
    ) -> dict[str, str]:
        mutations.append(principal.user_id)
        return {"user_id": principal.user_id}

    configure_middleware(app, settings=settings)
    return TestClient(app), mutations


def _settings(*, environment: str = "production") -> Settings:
    return Settings(
        app_environment=environment,
        auth_enabled=True,
        auth_demo_tokens_enabled=False,
        auth_jwt_secret="csrf-test-secret",
        auth_jwt_issuer="focus-agent-test",
    )


def _access_token(settings: Settings) -> str:
    return create_access_token(settings=settings, user_id="csrf-user")


def test_cookie_mutation_allows_same_origin_then_rejects_malicious_origin() -> None:
    settings = _settings()
    client, mutations = _csrf_app(settings)
    client.cookies.set(settings.auth_access_cookie_name, _access_token(settings))

    same_origin = client.post(
        "/mutation",
        headers={
            "Origin": "http://testserver",
            "Sec-Fetch-Site": "same-origin",
        },
    )
    cross_origin = client.post(
        "/mutation",
        headers={
            "Origin": "https://attacker.example",
            "Sec-Fetch-Site": "cross-site",
        },
    )

    assert same_origin.status_code == 200
    assert cross_origin.status_code == 403
    assert cross_origin.json()["data"]["code"] == "csrf_validation_failed"
    assert mutations == ["csrf-user"]


def test_cross_origin_cookie_mutation_fails_even_with_valid_double_submit_token() -> None:
    settings = _settings()
    client, mutations = _csrf_app(settings)
    client.cookies.set(settings.auth_access_cookie_name, _access_token(settings))
    client.cookies.set(CSRF_TOKEN_COOKIE, "client-generated-token")

    response = client.post(
        "/mutation",
        headers={
            "Origin": "https://attacker.example",
            "Sec-Fetch-Site": "cross-site",
            CSRF_TOKEN_HEADER: "client-generated-token",
        },
    )

    assert response.status_code == 403
    assert mutations == []


def test_conflicting_origin_and_referer_fail_closed() -> None:
    settings = _settings()
    client, mutations = _csrf_app(settings)
    client.cookies.set(settings.auth_access_cookie_name, _access_token(settings))

    response = client.post(
        "/mutation",
        headers={
            "Origin": "http://testserver",
            "Referer": "https://attacker.example/form",
            "Sec-Fetch-Site": "same-origin",
        },
    )

    assert response.status_code == 403
    assert mutations == []


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_all_cookie_authenticated_mutation_methods_reject_cross_origin(method: str) -> None:
    settings = _settings()
    client, mutations = _csrf_app(settings)
    client.cookies.set(settings.auth_access_cookie_name, _access_token(settings))

    response = client.request(
        method,
        "/mutation",
        headers={
            "Origin": "https://attacker.example",
            "Sec-Fetch-Site": "cross-site",
        },
    )

    assert response.status_code == 403
    assert mutations == []


def test_bearer_mutation_is_not_subject_to_cookie_csrf_checks() -> None:
    settings = _settings()
    client, mutations = _csrf_app(settings)
    token = _access_token(settings)

    response = client.post(
        "/mutation",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "https://attacker.example",
            "Sec-Fetch-Site": "cross-site",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": "csrf-user"}
    assert mutations == ["csrf-user"]


def test_invalid_bearer_cannot_bypass_cookie_csrf_checks() -> None:
    settings = _settings()
    client, mutations = _csrf_app(settings)
    client.cookies.set(settings.auth_access_cookie_name, _access_token(settings))

    response = client.post(
        "/mutation",
        headers={
            "Authorization": "Bearer attacker-controlled-invalid-token",
            "Origin": "https://attacker.example",
            "Sec-Fetch-Site": "cross-site",
        },
    )

    assert response.status_code == 403
    assert mutations == []


def test_production_cookie_mutation_without_browser_metadata_requires_double_submit() -> None:
    settings = _settings()
    client, mutations = _csrf_app(settings)
    client.cookies.set(settings.auth_access_cookie_name, _access_token(settings))

    missing_token = client.post("/mutation")
    client.cookies.set(CSRF_TOKEN_COOKIE, "client-generated-token")
    valid_token = client.post(
        "/mutation",
        headers={CSRF_TOKEN_HEADER: "client-generated-token"},
    )

    assert missing_token.status_code == 403
    assert valid_token.status_code == 200
    assert mutations == ["csrf-user"]


def test_local_cookie_mutation_without_browser_metadata_remains_compatible() -> None:
    settings = _settings(environment="local")
    client, mutations = _csrf_app(settings)
    client.cookies.set(settings.auth_access_cookie_name, _access_token(settings))

    response = client.post("/mutation")

    assert response.status_code == 200
    assert mutations == ["csrf-user"]


@pytest.mark.parametrize("same_site", ["none", "Lax", "", "invalid"])
def test_non_development_config_rejects_unsafe_cookie_same_site(same_site: str) -> None:
    settings = Settings(
        app_environment="production",
        auth_enabled=True,
        auth_demo_tokens_enabled=False,
        auth_jwt_secret="secure-production-jwt-secret-32-plus",
        auth_jwt_issuer="https://issuer.example.com",
        auth_cookie_secure=True,
        auth_cookie_samesite=same_site,
        rate_limit_enabled=True,
        cors_allowed_origins=("https://app.example.com",),
    )

    with pytest.raises(ValueError, match="AUTH_COOKIE_SAMESITE must be 'lax' or 'strict'"):
        _validate_non_development_security(settings, {"APP_ENVIRONMENT": "production"})


@pytest.mark.parametrize("same_site", ["lax", "strict"])
def test_non_development_config_accepts_safe_cookie_same_site(same_site: str) -> None:
    settings = Settings(
        app_environment="production",
        auth_enabled=True,
        auth_demo_tokens_enabled=False,
        auth_jwt_secret="secure-production-jwt-secret-32-plus",
        auth_jwt_issuer="https://issuer.example.com",
        auth_cookie_secure=True,
        auth_cookie_samesite=same_site,
        rate_limit_enabled=True,
        cors_allowed_origins=("https://app.example.com",),
    )

    _validate_non_development_security(settings, {"APP_ENVIRONMENT": "production"})
