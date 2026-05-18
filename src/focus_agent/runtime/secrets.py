from __future__ import annotations

import os
from typing import Protocol


class SecretProvider(Protocol):
    def get(self, key: str) -> str: ...
    def reload(self) -> None: ...


class EnvSecretProvider:
    def get(self, key: str) -> str:
        value = os.environ.get(key)
        if value is None or value == "":
            raise KeyError(f"Secret {key} not configured")
        return value

    def reload(self) -> None:
        return None


class VaultSecretProvider:
    def get(self, key: str) -> str:
        raise NotImplementedError(f"Vault secret provider is not configured for {key}")

    def reload(self) -> None:
        return None


class AwsSecretsManagerProvider:
    def get(self, key: str) -> str:
        raise NotImplementedError(f"AWS Secrets Manager provider is not configured for {key}")

    def reload(self) -> None:
        return None


def build_secret_provider(kind: str | None = None) -> SecretProvider:
    normalized = (kind or os.environ.get("FOCUS_AGENT_SECRET_PROVIDER") or "env").strip().lower()
    if normalized == "env":
        return EnvSecretProvider()
    if normalized == "vault":
        return VaultSecretProvider()
    if normalized in {"aws_sm", "aws-secrets-manager", "aws"}:
        return AwsSecretsManagerProvider()
    raise ValueError(f"Unsupported secret provider: {normalized}")


def try_get_secret(provider: SecretProvider, key: str) -> str | None:
    try:
        return provider.get(key)
    except KeyError:
        return None


def validate_secrets(provider: SecretProvider, environment: str) -> None:
    env = str(environment or "dev").strip().lower()
    required = ["AUTH_JWT_SECRET", "DATABASE_URI"]
    provider_keys = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
    missing = [key for key in required if try_get_secret(provider, key) is None]
    if missing and env not in {"dev", "development", "local", "test"}:
        raise SystemExit(f"Missing secrets: {', '.join(missing)}")
    if env not in {"dev", "development", "local", "test"} and not any(
        try_get_secret(provider, key) for key in provider_keys
    ):
        raise SystemExit("No LLM provider key configured")


__all__ = [
    "AwsSecretsManagerProvider",
    "EnvSecretProvider",
    "SecretProvider",
    "VaultSecretProvider",
    "build_secret_provider",
    "try_get_secret",
    "validate_secrets",
]
