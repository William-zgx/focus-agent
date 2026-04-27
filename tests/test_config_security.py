from __future__ import annotations

import json

import pytest

from focus_agent.config import DEFAULT_AUTH_JWT_SECRET, Settings, ensure_runtime_directories


_CONFIG_ENV_KEYS = (
    "APP_ENVIRONMENT",
    "ENVIRONMENT",
    "AUTH_ENABLED",
    "AUTH_DEMO_TOKENS_ENABLED",
    "AUTH_JWT_SECRET",
    "AUTH_JWT_KEY_ID",
    "AUTH_JWT_CURRENT_KID",
    "AUTH_JWT_KEYS",
    "AUTH_JWT_SECRETS",
    "AUTH_JWT_JWKS",
    "AUTH_JWT_ISSUER",
    "AUTH_JWT_AUDIENCE",
    "AUTH_ACCESS_TOKEN_TTL_SECONDS",
    "RATE_LIMIT_ENABLED",
    "RATE_LIMIT_PER_MINUTE",
    "RATE_LIMIT_CHAT_PER_MINUTE",
    "CORS_ALLOWED_ORIGINS",
    "CORS_ALLOW_CREDENTIALS",
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


def _set_secure_non_development_env(monkeypatch: pytest.MonkeyPatch, *, environment: str = "production") -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", environment)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_JWT_SECRET", "production-secret")
    monkeypatch.setenv("AUTH_JWT_ISSUER", "https://issuer.example.com")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")


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


def test_settings_from_env_is_side_effect_free_for_runtime_directories(monkeypatch, tmp_path):
    _isolate_settings_env(monkeypatch, tmp_path)
    branch_db_path = tmp_path / "runtime" / "db" / "branches.sqlite3"
    artifact_dir = tmp_path / "runtime" / "artifacts"
    monkeypatch.setenv("BRANCH_DB_PATH", str(branch_db_path))
    monkeypatch.setenv("ARTIFACT_DIR", str(artifact_dir))

    settings = Settings.from_env()

    assert settings.branch_db_path == str(branch_db_path)
    assert settings.artifact_dir == str(artifact_dir)
    assert not branch_db_path.parent.exists()
    assert not artifact_dir.exists()


def test_ensure_runtime_directories_creates_runtime_paths(tmp_path):
    branch_db_path = tmp_path / "runtime" / "db" / "branches.sqlite3"
    artifact_dir = tmp_path / "runtime" / "artifacts"
    settings = Settings(branch_db_path=str(branch_db_path), artifact_dir=str(artifact_dir))

    ensure_runtime_directories(settings)

    assert branch_db_path.parent.is_dir()
    assert artifact_dir.is_dir()

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
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")

    with pytest.raises(ValueError, match="AUTH_JWT_SECRET must not use"):
        Settings.from_env()


def test_settings_from_env_fails_in_staging_when_demo_tokens_enabled(monkeypatch, tmp_path):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENVIRONMENT", "staging")
    monkeypatch.setenv("AUTH_JWT_SECRET", "staging-secret")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "yes")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")

    with pytest.raises(ValueError, match="AUTH_DEMO_TOKENS_ENABLED must be false"):
        Settings.from_env()


def test_settings_from_env_fails_in_production_when_auth_disabled(monkeypatch, tmp_path):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("AUTH_JWT_SECRET", "production-secret")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")

    with pytest.raises(ValueError, match="AUTH_ENABLED must be true"):
        Settings.from_env()


def test_settings_from_env_fails_in_preprod_when_rate_limit_disabled(monkeypatch, tmp_path):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ENVIRONMENT", "preprod")
    monkeypatch.setenv("AUTH_JWT_SECRET", "preprod-secret")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")

    with pytest.raises(ValueError, match="RATE_LIMIT_ENABLED must be true"):
        Settings.from_env()


@pytest.mark.parametrize(
    ("env_key", "env_value", "message"),
    [
        ("AUTH_JWT_ISSUER", "", "AUTH_JWT_ISSUER must be set"),
        ("AUTH_ACCESS_TOKEN_TTL_SECONDS", "0", "AUTH_ACCESS_TOKEN_TTL_SECONDS must be greater than 0"),
    ],
)
def test_settings_from_env_fails_in_production_when_token_lifecycle_is_invalid(
    monkeypatch, tmp_path, env_key, env_value, message
):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_JWT_SECRET", "production-secret")
    monkeypatch.setenv("AUTH_JWT_ISSUER", "https://issuer.example.com")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_TTL_SECONDS", "900")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.setenv(env_key, env_value)

    with pytest.raises(ValueError, match=message):
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
    monkeypatch.setenv("AUTH_JWT_AUDIENCE", "focus-agent-web")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "on")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://staging.example.com")

    settings = Settings.from_env()

    assert settings.app_environment == "staging"
    assert settings.auth_enabled is True
    assert settings.auth_jwt_secret == "staging-secret"
    assert settings.auth_jwt_audience == "focus-agent-web"
    assert settings.auth_demo_tokens_enabled is False
    assert settings.rate_limit_enabled is True
    assert settings.cors_allowed_origins == ("https://staging.example.com",)


def test_settings_from_env_parses_jwt_key_rotation_config(monkeypatch, tmp_path):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_JWT_KEY_ID", "current")
    monkeypatch.setenv(
        "AUTH_JWT_KEYS",
        json.dumps(
            {
                "keys": [
                    {"kid": "current", "secret": "current-secret"},
                    {"kid": "previous", "secret": "previous-secret"},
                ]
            }
        ),
    )

    settings = Settings.from_env()

    assert settings.auth_jwt_key_id == "current"
    assert [(key.kid, key.secret, key.active) for key in settings.auth_jwt_keys] == [
        ("current", "current-secret", True),
        ("previous", "previous-secret", True),
    ]


def test_settings_from_env_allows_production_with_jwt_key_set_without_single_secret(
    monkeypatch, tmp_path
):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_JWT_KEY_ID", "current")
    monkeypatch.setenv(
        "AUTH_JWT_KEYS",
        "current=production-secret,previous=previous-secret",
    )
    monkeypatch.setenv("AUTH_JWT_ISSUER", "https://issuer.example.com")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")

    settings = Settings.from_env()

    assert settings.auth_jwt_secret == DEFAULT_AUTH_JWT_SECRET
    assert settings.auth_jwt_key_id == "current"
    assert settings.auth_jwt_keys[0].secret == "production-secret"


def test_settings_from_env_fails_in_production_when_current_jwt_kid_is_missing(
    monkeypatch, tmp_path
):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_JWT_KEY_ID", "current")
    monkeypatch.setenv("AUTH_JWT_KEYS", "previous=previous-secret")
    monkeypatch.setenv("AUTH_JWT_ISSUER", "https://issuer.example.com")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")

    with pytest.raises(ValueError, match="AUTH_JWT_KEY_ID must match"):
        Settings.from_env()


def test_settings_from_env_fails_when_jwt_key_id_misses_key_set_even_with_single_secret(
    monkeypatch, tmp_path
):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_JWT_SECRET", "fallback-production-secret")
    monkeypatch.setenv("AUTH_JWT_KEY_ID", "current")
    monkeypatch.setenv("AUTH_JWT_KEYS", "previous=previous-secret")
    monkeypatch.setenv("AUTH_JWT_ISSUER", "https://issuer.example.com")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")

    with pytest.raises(ValueError, match="AUTH_JWT_KEY_ID must match"):
        Settings.from_env()


@pytest.mark.parametrize(
    ("env_key", "env_value", "message"),
    [
        ("RATE_LIMIT_PER_MINUTE", "0", "RATE_LIMIT_PER_MINUTE must be greater than 0"),
        ("RATE_LIMIT_CHAT_PER_MINUTE", "0", "RATE_LIMIT_CHAT_PER_MINUTE must be greater than 0"),
    ],
)
def test_settings_from_env_fails_in_production_when_rate_limit_threshold_is_invalid(
    monkeypatch, tmp_path, env_key, env_value, message
):
    _isolate_settings_env(monkeypatch, tmp_path)
    _set_secure_non_development_env(monkeypatch)
    monkeypatch.setenv(env_key, env_value)

    with pytest.raises(ValueError, match=message):
        Settings.from_env()


def test_settings_from_env_fails_in_production_when_cors_missing(monkeypatch, tmp_path):
    _isolate_settings_env(monkeypatch, tmp_path)
    _set_secure_non_development_env(monkeypatch)
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    with pytest.raises(ValueError, match="CORS_ALLOWED_ORIGINS must be explicitly set"):
        Settings.from_env()


def test_settings_from_env_fails_in_production_when_wildcard_cors_allows_credentials(
    monkeypatch, tmp_path
):
    _isolate_settings_env(monkeypatch, tmp_path)
    _set_secure_non_development_env(monkeypatch)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")

    with pytest.raises(ValueError, match="CORS_ALLOW_CREDENTIALS must be false"):
        Settings.from_env()


def test_settings_from_env_allows_production_wildcard_cors_without_credentials(
    monkeypatch, tmp_path
):
    _isolate_settings_env(monkeypatch, tmp_path)
    _set_secure_non_development_env(monkeypatch)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "false")

    settings = Settings.from_env()

    assert settings.cors_allowed_origins == ("*",)
    assert settings.cors_allow_credentials is False


def test_settings_from_env_fails_in_production_when_demo_secret_is_configured(
    monkeypatch, tmp_path
):
    _isolate_settings_env(monkeypatch, tmp_path)
    _set_secure_non_development_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_SECRET", "change-me-before-sharing")

    with pytest.raises(ValueError, match="AUTH_JWT_SECRET must not use"):
        Settings.from_env()


def test_settings_from_env_preserves_external_jwt_issuer_audience_and_ttl(
    monkeypatch, tmp_path
):
    _isolate_settings_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_JWT_SECRET", "production-secret")
    monkeypatch.setenv("AUTH_JWT_ISSUER", "https://issuer.example.com")
    monkeypatch.setenv("AUTH_JWT_AUDIENCE", "focus-agent-web")
    monkeypatch.setenv("AUTH_ACCESS_TOKEN_TTL_SECONDS", "900")
    monkeypatch.setenv("AUTH_DEMO_TOKENS_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")

    settings = Settings.from_env()

    assert settings.auth_jwt_issuer == "https://issuer.example.com"
    assert settings.auth_jwt_audience == "focus-agent-web"
    assert settings.auth_access_token_ttl_seconds == 900
