from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from focus_agent.api.deps import require_roles, require_scopes
from focus_agent.api.main import create_app
from focus_agent.api.middleware import RateLimitMiddleware, REQUEST_ID_HEADER
from focus_agent.config import Settings
from focus_agent.security.rate_limit import SlidingWindowRateLimiter
from focus_agent.security.tokens import Principal, create_access_token


def _with_stub_frontend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")


def test_request_id_header_is_echoed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _with_stub_frontend(monkeypatch, tmp_path)
    app = create_app()
    client = TestClient(app)

    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.headers.get(REQUEST_ID_HEADER)

    readyz = client.get("/readyz")
    metrics = client.get("/metrics")
    assert readyz.status_code == 200
    assert readyz.headers.get(REQUEST_ID_HEADER)
    assert metrics.status_code == 200
    assert metrics.headers.get(REQUEST_ID_HEADER)


def test_request_id_header_is_preserved_from_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _with_stub_frontend(monkeypatch, tmp_path)
    app = create_app()
    client = TestClient(app)

    response = client.get("/healthz", headers={REQUEST_ID_HEADER: "req-abc-123"})
    assert response.headers.get(REQUEST_ID_HEADER) == "req-abc-123"


def test_error_envelope_shape_on_http_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _with_stub_frontend(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    app = create_app()
    client = TestClient(app)

    response = client.get("/v1/conversations")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == 401
    assert body["message"]
    assert "request_id" in body


def test_validation_error_envelope_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _with_stub_frontend(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    app = create_app()
    client = TestClient(app)

    response = client.post("/v1/chat/turns", json={"message": "hi"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == 422
    assert body["data"] and "errors" in body["data"]


def test_cors_headers_applied_when_origin_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _with_stub_frontend(monkeypatch, tmp_path)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    app = create_app()
    client = TestClient(app)

    response = client.get(
        "/healthz",
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin") == "http://localhost:5173"
    )


def _auth_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.state.runtime = SimpleNamespace(settings=settings)

    @app.get("/scope-required")
    def scope_required(
        principal: Principal = Depends(require_scopes("chat:write")),
    ) -> dict[str, str]:
        return {"user_id": principal.user_id}

    @app.get("/role-required")
    def role_required(
        principal: Principal = Depends(require_roles("admin")),
    ) -> dict[str, str]:
        return {"user_id": principal.user_id}

    return app


def _token(
    settings: Settings,
    *,
    user_id: str,
    tenant_id: str | None = None,
    scopes: list[str] | None = None,
) -> str:
    return create_access_token(
        settings=settings,
        user_id=user_id,
        tenant_id=tenant_id,
        scopes=scopes or [],
    )


async def _noop_app(scope, receive, send) -> None:
    del scope, receive, send


def _identity_for(
    settings: Settings,
    authorization: str | None,
    *,
    host: str = "203.0.113.10",
) -> str:
    middleware = RateLimitMiddleware(
        _noop_app,
        default_limit=1,
        chat_limit=1,
        settings=settings,
    )
    headers = {"authorization": authorization} if authorization is not None else {}
    request = SimpleNamespace(headers=headers, client=SimpleNamespace(host=host))
    return middleware._identity(request)


def test_rate_limit_identity_does_not_leak_bearer_token() -> None:
    settings = Settings(auth_jwt_secret="rate-secret", auth_jwt_issuer="focus-agent-test")
    token = _token(settings, user_id="user-1", tenant_id="tenant-a")

    identity = _identity_for(settings, f"Bearer {token}")

    assert identity == "principal:tenant-a:user-1"
    assert token not in identity


def test_rate_limit_identity_uses_valid_principal_user_without_tenant() -> None:
    settings = Settings(auth_jwt_secret="rate-secret", auth_jwt_issuer="focus-agent-test")
    token = _token(settings, user_id="user-1")

    assert _identity_for(settings, f"Bearer {token}") == "principal:user-1"


def test_rate_limit_identity_uses_digest_for_invalid_bearer_token() -> None:
    settings = Settings(auth_jwt_secret="rate-secret", auth_jwt_issuer="focus-agent-test")
    token = "not-a-valid-token"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]

    identity = _identity_for(settings, f"Bearer {token}")

    assert identity == f"bearer-digest:{digest}"
    assert token not in identity


def test_rate_limit_identity_uses_client_host_without_bearer_token() -> None:
    settings = Settings(auth_jwt_secret="rate-secret", auth_jwt_issuer="focus-agent-test")

    assert _identity_for(settings, None, host="198.51.100.7") == "ip:198.51.100.7"


def test_scope_and_role_dependencies_return_403_when_claims_missing() -> None:
    settings = Settings(auth_jwt_secret="authz-secret", auth_jwt_issuer="focus-agent-test")
    client = TestClient(_auth_app(settings))
    headers = {"Authorization": f"Bearer {_token(settings, user_id='user-1')}"}

    scope_response = client.get("/scope-required", headers=headers)
    role_response = client.get("/role-required", headers=headers)

    assert scope_response.status_code == 403
    assert "Missing required scope" in scope_response.json()["detail"]
    assert role_response.status_code == 403
    assert "Missing required role" in role_response.json()["detail"]


def test_auth_disabled_development_mode_allows_required_dependencies_without_token() -> None:
    settings = Settings(
        auth_enabled=False,
        auth_jwt_secret="authz-secret",
        auth_jwt_issuer="focus-agent-test",
    )
    client = TestClient(_auth_app(settings))

    scope_response = client.get("/scope-required")
    role_response = client.get("/role-required")

    assert scope_response.status_code == 200
    assert scope_response.json() == {"user_id": "anonymous"}
    assert role_response.status_code == 200
    assert role_response.json() == {"user_id": "anonymous"}


def test_rate_limiter_blocks_after_threshold() -> None:
    limiter = SlidingWindowRateLimiter(window_seconds=60.0)
    for _ in range(3):
        result = limiter.check(key="user-1:/v1/chat/turns", limit=3)
        assert result.allowed is True
    blocked = limiter.check(key="user-1:/v1/chat/turns", limit=3)
    assert blocked.allowed is False
    assert blocked.retry_after_seconds >= 0.0


def test_rate_limiter_keys_are_independent() -> None:
    limiter = SlidingWindowRateLimiter(window_seconds=60.0)
    limiter.check(key="user-1", limit=1)
    result = limiter.check(key="user-2", limit=1)
    assert result.allowed is True


def test_rate_limit_middleware_returns_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _with_stub_frontend(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    monkeypatch.setenv("RATE_LIMIT_CHAT_PER_MINUTE", "2")
    app = create_app()
    client = TestClient(app)

    responses = [client.get("/healthz") for _ in range(3)]
    assert responses[-1].status_code == 429
    body = responses[-1].json()
    assert body["code"] == 429
    assert body["data"]["retry_after_seconds"] >= 1
    assert responses[-1].headers.get("Retry-After")


def test_readyz_and_metrics_payloads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _with_stub_frontend(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_ENABLED", "false")
    app = create_app()
    app.state.runtime = SimpleNamespace(
        settings=SimpleNamespace(
            auth_enabled=False,
            database_uri="postgresql://example",
            trajectory_enabled=True,
            tracing_enabled=True,
            otel_traces_exporters=("otlp",),
            app_version="9.9.9",
            app_environment="staging",
            deployment_name="focus-agent-blue",
        ),
        graph=object(),
        repo=object(),
        branch_service=object(),
        tool_registry=object(),
        skill_registry=object(),
        otel_runtime=SimpleNamespace(
            ready=True,
            detail="exporting spans via otlp",
            exporter_names=("otlp",),
        ),
        trajectory_recorder=SimpleNamespace(
            list_turns=lambda query: [],
            get_turn=lambda turn_id: None,
            list_steps_by_turn_ids=lambda turn_ids: {},
            get_turn_stats=lambda query: {
                "overview": {"turn_count": 2, "avg_latency_ms": 12.5},
                "by_status": [{"key": "succeeded", "turn_count": 2}],
            },
        ),
    )
    client = TestClient(app)

    readyz = client.get("/readyz")
    metrics = client.get("/metrics")

    assert readyz.status_code == 200
    payload = readyz.json()
    assert payload["status"] == "ok"
    assert payload["ready"] is True
    tracing_check = next(item for item in payload["checks"] if item["name"] == "tracing_exporter")
    assert tracing_check["ready"] is True
    trajectory_check = next(item for item in payload["checks"] if item["name"] == "trajectory_recorder")
    assert trajectory_check["ready"] is True
    assert payload["app_version"] == "9.9.9"
    assert payload["environment"] == "staging"
    assert payload["deployment"] == "focus-agent-blue"

    assert metrics.status_code == 200
    assert "focus_agent_runtime_build_info" in metrics.text
    assert 'version="9.9.9"' in metrics.text
    assert 'environment="staging"' in metrics.text
    assert 'component="tracing_exporter"' in metrics.text
    assert "focus_agent_trajectory_turn_count 2" in metrics.text
