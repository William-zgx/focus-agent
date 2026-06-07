from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from focus_agent.api.main import create_app
from focus_agent.capabilities.tool_registry import build_tool_registry
from focus_agent.config import Settings, load_model_catalog_toml, load_tool_catalog_document
from focus_agent.engine.graph_builder import build_graph
from focus_agent.repositories.user_repository import InMemoryUserRepository
from focus_agent.security.tokens import create_access_token
from focus_agent.services.auth import AuthService
from focus_agent.services.users import UserService
from focus_agent.skills import SkillRegistry


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
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "plan"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """
---
name: plan
description: Build a concise implementation plan before coding.
triggers: [plan:]
aliases: [方案, planning]
localized_triggers: [计划:, 计划：]
domains: [planning, 项目管理]
intents: [implementation planning, 方案设计]
when_to_use: [The user wants a plan first]
primary_tools: [search_code]
recommended_tools: [read_file]
---
# Plan
Clarify the goal and choose the smallest verifiable path.
""".strip()
        + "\n",
        encoding="utf-8",
    )
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
        workspace_root=str(tmp_path),
        auth_enabled=True,
        auth_demo_tokens_enabled=True,
        auth_jwt_secret="admin-config-secret",
        auth_jwt_issuer="focus-agent-test",
        model=model_catalog.default_model or "openai:gpt-4.1-mini",
        model_catalog=model_catalog,
        model_choices=model_catalog.model_choices,
        tool_catalog=tool_catalog,
        web_search=tool_catalog.web_search,
        skills_enabled=True,
        skill_directories=(str(skill_root),),
        skill_install_directory=str(skill_root),
        skill_sources_enabled=("installed", "project"),
        skill_trusted_sources=("installed", "project", "builtin"),
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
    assert body["skills"]["enabled"] is True
    assert body["skills"]["install_directory"]["exists"] is True
    skill_catalog = {item["skill_id"]: item for item in body["skills"]["catalog"]}
    assert "plan" in skill_catalog
    assert skill_catalog["plan"]["aliases"] == ["方案", "planning"]
    assert skill_catalog["plan"]["localized_triggers"] == ["计划:", "计划："]
    assert skill_catalog["plan"]["domains"] == ["planning", "项目管理"]
    assert skill_catalog["plan"]["intents"] == ["implementation planning", "方案设计"]
    assert skill_catalog["plan"]["primary_tools"] == ["search_code"]
    assert skill_catalog["plan"]["recommended_tools"] == ["read_file"]
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


def test_admin_config_updates_and_refreshes_skills(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, settings, service, _, _, local_env_path = _build_client(monkeypatch, tmp_path)
    service.create_user(user_id="admin-1", roles=["admin"])
    headers = _headers(settings, "admin-1")
    runtime = client.app.state.runtime
    skill_registry = SkillRegistry.from_settings(settings)
    tool_registry = build_tool_registry(settings=settings, skill_registry=skill_registry)
    runtime.skill_registry = skill_registry
    runtime.tool_registry = tool_registry
    runtime.graph = build_graph(
        settings=settings,
        skill_registry=skill_registry,
        tool_registry=tool_registry,
    )
    initial_graph = runtime.graph
    old_skill_root = Path(settings.skill_directories[0])
    old_scripts_dir = old_skill_root / "plan" / "scripts"
    old_scripts_dir.mkdir(parents=True)
    (old_scripts_dir / "probe.py").write_text("print('old-skill-root')\n", encoding="utf-8")
    next_skill_root = tmp_path / "next-skills"
    next_skill_dir = next_skill_root / "review"
    next_scripts_dir = next_skill_dir / "scripts"
    next_scripts_dir.mkdir(parents=True)
    (next_scripts_dir / "probe.py").write_text("print('new-skill-root')\n", encoding="utf-8")
    (next_skill_dir / "SKILL.md").write_text(
        """
---
name: review
description: Review code changes for regressions.
triggers: [review:]
when_to_use: [The user asks for review]
recommended_tools: [search_code]
---
# Review
Look for correctness risks first.
""".strip()
        + "\n",
        encoding="utf-8",
    )

    disable_response = client.patch(
        "/v1/admin/config/skills",
        headers=headers,
        json={
            "reason": "pause skill activation",
            "enabled": False,
            "skill_directories": [str(next_skill_root)],
            "install_directory": str(next_skill_root),
            "sources_enabled": ["installed", "project"],
            "source_locations": [f"community=local:{tmp_path / 'community-skills'}"],
            "trusted_sources": ["installed", "project", "builtin"],
            "semantic_match_enabled": False,
            "semantic_match_threshold": 0.31,
        },
    )

    assert disable_response.status_code == 200
    disabled_body = disable_response.json()
    assert disabled_body["skills"]["enabled"] is False
    disabled_catalog = {item["skill_id"]: item for item in disabled_body["skills"]["catalog"]}
    assert "review" in disabled_catalog
    assert disabled_catalog["review"]["enabled"] is False
    assert settings.skills_enabled is False
    assert settings.skill_directories == (str(next_skill_root),)
    assert settings.skill_install_directory == str(next_skill_root)
    assert settings.skill_semantic_match_enabled is False
    assert settings.skill_semantic_match_threshold == 0.31
    tool = runtime.tool_registry.by_name["run_workspace_command"]
    assert runtime.graph is not initial_graph
    new_payload = json.loads(
        tool.invoke(
            {
                "command": ["python3", "scripts/probe.py"],
                "cwd": "next-skills/review",
            }
        )
    )
    assert new_payload["exit_code"] == 0
    assert "new-skill-root" in new_payload["stdout"]
    with pytest.raises(ValueError, match="not allowlisted"):
        tool.invoke(
            {
                "command": ["python3", "scripts/probe.py"],
                "cwd": "skills/plan",
            }
        )
    local_env = local_env_path.read_text(encoding="utf-8")
    assert "FOCUS_AGENT_SKILLS_ENABLED=false" in local_env
    assert f"FOCUS_AGENT_SKILLS_DIRS={next_skill_root}" in local_env
    assert f"SKILL_INSTALL_DIRECTORY={next_skill_root}" in local_env
    assert "SKILL_SEMANTIC_MATCH_ENABLED=false" in local_env

    enable_response = client.patch(
        "/v1/admin/config/skills",
        headers=headers,
        json={"enabled": True, "reason": "resume skill activation"},
    )

    assert enable_response.status_code == 200
    enabled_body = enable_response.json()
    assert enabled_body["skills"]["enabled"] is True
    assert "review" in {item["skill_id"] for item in enabled_body["skills"]["catalog"]}

    skill_toggle_response = client.patch(
        "/v1/admin/config/skills",
        headers=headers,
        json={
            "reason": "disable noisy review skill",
            "skills": [{"skill_id": "review", "enabled": False}],
        },
    )

    assert skill_toggle_response.status_code == 200
    toggled_body = skill_toggle_response.json()
    toggled_catalog = {item["skill_id"]: item for item in toggled_body["skills"]["catalog"]}
    assert toggled_body["skills"]["disabled_skill_ids"] == ["review"]
    assert toggled_catalog["review"]["enabled"] is False
    assert "SKILL_DISABLED_IDS=review" in local_env_path.read_text(encoding="utf-8")

    refresh_skill_dir = next_skill_root / "debug"
    refresh_skill_dir.mkdir()
    (refresh_skill_dir / "SKILL.md").write_text(
        """
---
name: debug
description: Debug a failing backend test.
---
# Debug
Reproduce the failure and isolate the root cause.
""".strip()
        + "\n",
        encoding="utf-8",
    )

    refresh_response = client.post("/v1/admin/config/skills/refresh", headers=headers)

    assert refresh_response.status_code == 200
    refreshed_body = refresh_response.json()
    refreshed_ids = {item["skill_id"] for item in refreshed_body["skills"]["catalog"]}
    assert {"debug", "review"}.issubset(refreshed_ids)

    audit = client.get("/v1/admin/audit-events", headers=headers)
    assert audit.status_code == 200
    actions = {item["action"] for item in audit.json()["items"]}
    assert {"config.skills.update", "config.skills.refresh"}.issubset(actions)
