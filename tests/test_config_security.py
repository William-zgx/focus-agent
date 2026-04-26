from __future__ import annotations

import pytest

from focus_agent.config import DEFAULT_AUTH_JWT_SECRET, Settings


_CONFIG_ENV_KEYS = (
    "APP_ENVIRONMENT",
    "ENVIRONMENT",
    "AUTH_ENABLED",
    "AUTH_DEMO_TOKENS_ENABLED",
    "AUTH_JWT_SECRET",
    "RATE_LIMIT_ENABLED",
    "FOCUS_AGENT_LOCAL_ENV_FILE",
    "FOCUS_AGENT_MODEL_CATALOG_DOC",
    "FOCUS_AGENT_TOOL_CATALOG_DOC",
    "BRANCH_DB_PATH",
    "ARTIFACT_DIR",
)


def _isolate_settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    for key in _CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("FOCUS_AGENT_LOCAL_ENV_FILE", str(tmp_path / "missing-local.env"))
    monkeypatch.setenv("FOCUS_AGENT_MODEL_CATALOG_DOC", str(tmp_path / "missing-models.toml"))
    monkeypatch.setenv("FOCUS_AGENT_TOOL_CATALOG_DOC", str(tmp_path / "missing-tools.toml"))


@pytest.mark.parametrize(
    ("env_key", "env_value"),
    [
        ("APP_ENVIRONMENT", "development"),
        ("APP_ENVIRONMENT", "local"),
        ("ENVIRONMENT", "test"),
    ],
)
def test_settings_from_env_allows_development_defaults(monkeypatch, tmp_path, env_key, env_value):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv(env_key, env_value)

    settings = Settings.from_env()

    assert settings.auth_enabled is True
    assert settings.auth_demo_tokens_enabled is True
    assert settings.auth_jwt_secret == DEFAULT_AUTH_JWT_SECRET
    assert settings.rate_limit_enabled is False


def test_settings_from_env_fails_in_production_when_jwt_secret_missing(monkeypatch, tmp_path):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")

    with pytest.raises(ValueError, match="AUTH_JWT_SECRET must be set"):
        Settings.from_env()


def test_settings_from_env_fails_in_prod_when_jwt_secret_is_development_default(
    monkeypatch, tmp_path
):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENVIRONMENT", "prod")
    monkeypatch.setenv("AUTH_JWT_SECRET", DEFAULT_AUTH_JWT_SECRET)
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")

    with pytest.raises(ValueError, match="AUTH_JWT_SECRET must not use"):
        Settings.from_env()


def test_settings_from_env_fails_in_staging_when_demo_tokens_enabled(monkeypatch, tmp_path):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENVIRONMENT", "staging")
    monkeypatch.setenv("AUTH_JWT_SECRET", "staging-secret")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "yes")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")

    with pytest.raises(ValueError, match="AUTH_DEMO_TOKENS_ENABLED must be false"):
        Settings.from_env()


def test_settings_from_env_fails_in_production_when_auth_disabled(monkeypatch, tmp_path):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_JWT_SECRET", "production-secret")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")

    with pytest.raises(ValueError, match="AUTH_ENABLED must be true"):
        Settings.from_env()


def test_settings_from_env_fails_in_preprod_when_rate_limit_disabled(monkeypatch, tmp_path):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ENVIRONMENT", "preprod")
    monkeypatch.setenv("AUTH_JWT_SECRET", "preprod-secret")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")

    with pytest.raises(ValueError, match="RATE_LIMIT_ENABLED must be true"):
        Settings.from_env()


def test_settings_from_env_fails_when_either_environment_is_non_development(
    monkeypatch, tmp_path
):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENVIRONMENT", "local")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_JWT_SECRET", "production-secret")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")

    with pytest.raises(ValueError, match="ENVIRONMENT=production"):
        Settings.from_env()


def test_settings_from_env_allows_staging_with_secure_settings(monkeypatch, tmp_path):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENVIRONMENT", "staging")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_JWT_SECRET", "staging-secret")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "on")

    settings = Settings.from_env()

    assert settings.app_environment == "staging"
    assert settings.auth_enabled is True
    assert settings.auth_jwt_secret == "staging-secret"
    assert settings.auth_demo_tokens_enabled is False
    assert settings.rate_limit_enabled is True
