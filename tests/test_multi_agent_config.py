from __future__ import annotations

from focus_agent.config import Settings
from focus_agent.config_parts.multi_agent import load_multi_agent_config


def test_multi_agent_config_defaults_are_disabled() -> None:
    defaults = Settings()
    values = load_multi_agent_config({}, defaults)

    assert values["multi_agent_v2_enabled"] is False
    assert values["multi_agent_dag_scheduler_enabled"] is False
    assert values["multi_agent_resource_lock_enabled"] is False
    assert values["multi_agent_message_bus_enabled"] is False
    assert values["multi_agent_async_approval_enabled"] is False
    assert values["multi_agent_failure_handler_enabled"] is False


def test_multi_agent_config_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("MULTI_AGENT_V2_ENABLED", "true")
    monkeypatch.setenv("MULTI_AGENT_DAG_SCHEDULER_ENABLED", "yes")
    monkeypatch.setenv("MULTI_AGENT_ASYNC_APPROVAL_ENABLED", "1")
    monkeypatch.setenv("MULTI_AGENT_RESOURCE_LOCK_TTL_SECONDS", "90")
    monkeypatch.setenv("MULTI_AGENT_ROLE_FALLBACK_MODELS", "backend_executor=openai:gpt-4.1")

    settings = Settings.from_env()

    assert settings.multi_agent_v2_enabled is True
    assert settings.multi_agent_dag_scheduler_enabled is True
    assert settings.multi_agent_async_approval_enabled is True
    assert settings.multi_agent_resource_lock_ttl_seconds == 90.0
    assert settings.multi_agent_role_fallback_models == {
        "backend_executor": "openai:gpt-4.1"
    }
