from __future__ import annotations

from focus_agent.config import Settings


def test_multi_agent_coordination_defaults() -> None:
    settings = Settings()

    assert settings.multi_agent_v2_enabled is False
    assert settings.multi_agent_async_approval_enabled is False
    assert settings.multi_agent_message_ttl_seconds == 300.0
    assert settings.multi_agent_approval_timeout_seconds == 60.0


def test_multi_agent_coordination_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("MULTI_AGENT_V2_ENABLED", "true")
    monkeypatch.setenv("MULTI_AGENT_ASYNC_APPROVAL_ENABLED", "1")
    monkeypatch.setenv("MULTI_AGENT_MESSAGE_TTL_SECONDS", "120")
    monkeypatch.setenv("MULTI_AGENT_APPROVAL_TIMEOUT_SECONDS", "45")

    settings = Settings.from_env()

    assert settings.multi_agent_v2_enabled is True
    assert settings.multi_agent_async_approval_enabled is True
    assert settings.multi_agent_message_ttl_seconds == 120.0
    assert settings.multi_agent_approval_timeout_seconds == 45.0
