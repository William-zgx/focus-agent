from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from focus_agent.api.main import create_app
from focus_agent.config import Settings, load_model_catalog_toml, load_tool_catalog_document
from focus_agent.repositories.user_repository import InMemoryUserRepository
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
) -> tuple[TestClient, Settings, UserService, Path, Path, Path]:
    _with_stub_frontend(monkeypatch, tmp_path)
    model_path = tmp_path / "models.toml"
    tool_path = tmp_path / "tools.toml"
    local_env_path = tmp_path / "local.env"
    monkeypatch.setenv("FOCUS_AGENT_MODEL_CATALOG_DOC", str(model_path))
    monkeypatch.setenv("FOCUS_AGENT_TOOL_CATALOG_DOC", str(tool_path))
    monkeypatch.setenv("FOCUS_AGENT_LOCAL_ENV_FILE", str(local_env_path))
    model_path.write_text(
        """
default_model = "openai:gpt-4.1-mini"
model_choices = ["openai:gpt-4.1-mini"]

[[providers]]
id = "openai"
label = "OpenAI"
backend_provider = "openai"
api_key_env = "OPENAI_API_KEY"

[[models]]
id = "openai:gpt-4.1-mini"
label = "GPT-4.1 Mini"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    tool_path.write_text(
        """
[read_file]
enabled = true
label = "Read File"
description = "Read repository files."
max_lines = 400

[[providers]]
id = "builtin"
enabled = true
order = 0
""".strip()
        + "\n",
        encoding="utf-8",
    )
    model_catalog = load_model_catalog_toml(model_path.read_text(encoding="utf-8"))
    tool_catalog = load_tool_catalog_document(tool_path)
    settings = Settings(
        auth_enabled=True,
        auth_demo_tokens_enabled=True,
        auth_jwt_secret="admin-config-secret",
        auth_jwt_issuer="focus-agent-test",
        model=model_catalog.default_model or "openai:gpt-4.1-mini",
        model_catalog=model_catalog,
        model_choices=model_catalog.model_choices,
        tool_catalog=tool_catalog,
        web_search=tool_catalog.web_search,
        database_uri="postgresql://secret@example.test/focus",
        resolved_env={
            "FOCUS_AGENT_MODEL_CATALOG_DOC": str(model_path),
            "FOCUS_AGENT_TOOL_CATALOG_DOC": str(tool_path),
            "FOCUS_AGENT_LOCAL_ENV_FILE": str(local_env_path),
            "OPENAI_API_KEY": "test-api-key",
        },
    )
    repo = InMemoryUserRepository()
    service = UserService(repo, auth_enabled=True)
    app = create_app()
    app.state.runtime = SimpleNamespace(
        settings=settings,
        user_repository=repo,
        user_service=service,
        auth_service=AuthService(repo, settings=settings),
        background_work=None,
        durable_background_worker=None,
        coordination_backend=SimpleNamespace(job_deduper=None),
    )
    return TestClient(app), settings, service, model_path, tool_path, local_env_path


def _headers(settings: Settings, user_id: str) -> dict[str, str]:
    token = create_access_token(
        settings=settings,
        user_id=user_id,
        scopes=["users:read", "users:update"],
    )
    return {"Authorization": f"Bearer {token}"}


def test_admin_config_requires_admin_and_masks_sensitive_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, settings, service, _, _, _ = _build_client(monkeypatch, tmp_path)
    service.create_user(user_id="admin-1", roles=["admin"])
    service.create_user(user_id="member-1", roles=["member"])

    denied = client.get("/v1/admin/config", headers=_headers(settings, "member-1"))
    assert denied.status_code == 403

    response = client.get("/v1/admin/config", headers=_headers(settings, "admin-1"))

    assert response.status_code == 200
    body = response.json()
    assert body["models"]["default_model"] == "openai:gpt-4.1-mini"
    assert body["models"]["providers"][0]["api_key_configured"] is True
    system_by_key = {item["key"]: item for item in body["system"]["items"]}
    assert system_by_key["database_uri"]["sensitive"] is True
    assert system_by_key["database_uri"]["configured"] is True
    assert system_by_key["database_uri"]["value"] is None
    assert "test-api-key" not in response.text


def test_admin_config_updates_models_tools_and_policies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, settings, service, model_path, tool_path, local_env_path = _build_client(
        monkeypatch, tmp_path
    )
    service.create_user(user_id="admin-1", roles=["admin"])
    headers = _headers(settings, "admin-1")

    model_response = client.patch(
        "/v1/admin/config/models",
        headers=headers,
        json={
            "reason": "switch model",
            "default_model": "openai:gpt-4.1",
            "model_choices": ["openai:gpt-4.1", "openai:gpt-4.1-mini"],
            "providers": [
                {
                    "id": "openai",
                    "label": "OpenAI",
                    "backend_provider": "openai",
                    "api_key_env": "OPENAI_API_KEY",
                }
            ],
            "models": [
                {"id": "openai:gpt-4.1", "label": "GPT-4.1"},
                {"id": "openai:gpt-4.1-mini", "label": "GPT-4.1 Mini"},
            ],
        },
    )
    assert model_response.status_code == 200
    assert settings.model == "openai:gpt-4.1"
    assert 'default_model = "openai:gpt-4.1"' in model_path.read_text(encoding="utf-8")

    tool_response = client.patch(
        "/v1/admin/config/tools",
        headers=headers,
        json={
            "reason": "limit file reads",
            "tools": [
                {
                    "name": "read_file",
                    "enabled": False,
                    "settings": {"max_lines": 120},
                }
            ],
        },
    )
    assert tool_response.status_code == 200
    assert settings.tool_catalog.read_file.enabled is False
    assert settings.tool_catalog.read_file.max_lines == 120
    tool_text = tool_path.read_text(encoding="utf-8")
    assert "[read_file]" in tool_text
    assert "max_lines = 120" in tool_text

    policy_response = client.patch(
        "/v1/admin/config/policies",
        headers=headers,
        json={
            "reason": "enable delegation",
            "values": {
                "agent_delegation_enabled": True,
                "agent_delegation_execution_mode": "inline",
                "agent_branch_decision_rate_limit_per_hour": 5,
            },
        },
    )
    assert policy_response.status_code == 200
    assert settings.agent_delegation_enabled is True
    assert settings.agent_delegation_execution_mode == "inline"
    local_env = local_env_path.read_text(encoding="utf-8")
    assert "AGENT_DELEGATION_ENABLED=true" in local_env
    assert "AGENT_DELEGATION_EXECUTION_MODE=inline" in local_env
    assert "AGENT_BRANCH_DECISION_RATE_LIMIT_PER_HOUR=5" in local_env

    audit = client.get("/v1/admin/audit-events", headers=headers)
    assert audit.status_code == 200
    actions = {item["action"] for item in audit.json()["items"]}
    assert {
        "config.models.update",
        "config.tools.update",
        "config.policies.update",
    }.issubset(actions)
