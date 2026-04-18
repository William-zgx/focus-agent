from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from focus_agent.api.main import create_app
from focus_agent.api.middleware import REQUEST_ID_HEADER
from focus_agent.security.rate_limit import SlidingWindowRateLimiter


def _with_stub_frontend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")


def test_request_id_header_is_echoed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _with_stub_frontend(monkeypatch, tmp_path)
    app = create_app()
    client = TestClient(app)

    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.headers.get(REQUEST_ID_HEADER)


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
