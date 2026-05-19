from __future__ import annotations

import logging

import pytest

from focus_agent import config as config_module
from focus_agent.config import Settings

_SECURE_JWT_SECRET = "secure-local-auth-jwt-secret-32-plus"


def _isolate_settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    for key in (
        "APP_ENVIRONMENT",
        "ENVIRONMENT",
        "AUTH_ENABLED",
        "AUTH_JWT_SECRET",
        "AUTH_JWT_KEYS",
        "AUTH_JWT_SECRETS",
        "AUTH_JWT_JWKS",
        "FOCUS_AGENT_LOCAL_ENV_FILE",
        "FOCUS_AGENT_MODEL_CATALOG_DOC",
        "FOCUS_AGENT_TOOL_CATALOG_DOC",
        "FOCUS_AGENT_SECRET_PROVIDER",
        "LANGSMITH_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("FOCUS_AGENT_LOCAL_ENV_FILE", str(tmp_path / "missing-local.env"))
    monkeypatch.setenv("FOCUS_AGENT_MODEL_CATALOG_DOC", str(tmp_path / "missing-models.toml"))
    monkeypatch.setenv("FOCUS_AGENT_TOOL_CATALOG_DOC", str(tmp_path / "missing-tools.toml"))


@pytest.mark.parametrize(
    "secret",
    [
        "change-me",
        "replace-with-a-local-secret-that-is-long-enough",
        "example-local-secret-that-is-long-enough",
    ],
)
def test_settings_from_env_rejects_placeholder_jwt_secret_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path, secret: str
) -> None:
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_JWT_SECRET", secret)

    with pytest.raises(ValueError, match="AUTH_ENABLED=true"):
        Settings.from_env()


def test_settings_from_env_rejects_short_jwt_secret_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_JWT_SECRET", "short-secret")

    with pytest.raises(ValueError, match="AUTH_JWT_SECRET must be at least 32 characters"):
        Settings.from_env()


def test_settings_from_env_allows_strong_jwt_secret_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_JWT_SECRET", _SECURE_JWT_SECRET)

    settings = Settings.from_env()

    assert settings.auth_jwt_secret == _SECURE_JWT_SECRET


def test_secret_provider_resolution_logs_redacted_secret_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path, caplog: pytest.LogCaptureFixture
) -> None:
    class FakeSecretProvider:
        values = {
            "LANGSMITH_API_KEY": "langsmith-secret-value",
            "OPENAI_API_KEY": "openai-secret-value",
        }

        def get(self, key: str) -> str:
            value = self.values.get(key)
            if not value:
                raise KeyError(key)
            return value

        def reload(self) -> None:
            return None

    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("FOCUS_AGENT_SECRET_PROVIDER", "fake")
    monkeypatch.setattr(
        config_module.secret_runtime,
        "build_secret_provider",
        lambda kind=None: FakeSecretProvider(),
    )
    caplog.set_level(logging.DEBUG, logger="focus_agent.config")

    settings = Settings.from_env()

    assert settings.resolved_env["LANGSMITH_API_KEY"] == "langsmith-secret-value"
    assert settings.resolved_env["OPENAI_API_KEY"] == "openai-secret-value"
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "langsmith-secret-value" not in messages
    assert "openai-secret-value" not in messages
    assert "[REDACTED]" in messages
