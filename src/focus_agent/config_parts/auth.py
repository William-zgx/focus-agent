from __future__ import annotations

import base64
import json
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any

from .common import _coerce_bool, _normalize_optional_string

DEFAULT_AUTH_JWT_SECRET = "focus-agent-dev-secret"
_INSECURE_AUTH_JWT_SECRETS = {
    DEFAULT_AUTH_JWT_SECRET,
    "change-me-before-sharing",
    "change-me-in-shared-env",
}
_DEVELOPMENT_ENVIRONMENT_NAMES = {"dev", "development", "local", "test", "testing", "ci"}


@dataclass(frozen=True, slots=True)
class AuthJwtKey:
    kid: str
    secret: str
    active: bool = True


def _b64url_decode_string(raw: str) -> str | None:
    try:
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        return decoded.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _coerce_auth_jwt_key(raw: object, *, default_kid: str | None = None) -> AuthJwtKey | None:
    if not isinstance(raw, dict):
        secret = _normalize_optional_string(raw)
        kid = _normalize_optional_string(default_kid)
        if kid is None or secret is None:
            return None
        return AuthJwtKey(kid=kid, secret=secret)

    kid = _normalize_optional_string(raw.get("kid") or raw.get("id") or default_kid)
    secret = _normalize_optional_string(
        raw.get("secret") or raw.get("value") or raw.get("shared_secret")
    )
    if secret is None:
        jwk_secret = _normalize_optional_string(raw.get("k"))
        if jwk_secret is not None:
            secret = _b64url_decode_string(jwk_secret) or jwk_secret
    if kid is None or secret is None:
        return None

    active = _coerce_bool(raw.get("active"))
    if active is None:
        status = (_normalize_optional_string(raw.get("status")) or "active").lower()
        active = status not in {"disabled", "inactive", "retired", "revoked"}
    return AuthJwtKey(kid=kid, secret=secret, active=active)


def _dedupe_auth_jwt_keys(keys: list[AuthJwtKey]) -> tuple[AuthJwtKey, ...]:
    deduped: dict[str, AuthJwtKey] = {}
    for key in keys:
        deduped[key.kid] = key
    return tuple(deduped.values())


def _parse_auth_jwt_key_object(raw: object) -> tuple[AuthJwtKey, ...]:
    keys: list[AuthJwtKey] = []
    if isinstance(raw, list):
        for item in raw:
            key = _coerce_auth_jwt_key(item)
            if key is not None:
                keys.append(key)
        return _dedupe_auth_jwt_keys(keys)

    if not isinstance(raw, dict):
        return ()

    jwks_keys = raw.get("keys")
    if isinstance(jwks_keys, list):
        for item in jwks_keys:
            key = _coerce_auth_jwt_key(item)
            if key is not None:
                keys.append(key)

    for kid, value in raw.items():
        if kid in {"keys", "current_kid", "currentKid"}:
            continue
        key = _coerce_auth_jwt_key(value, default_kid=str(kid))
        if key is not None:
            keys.append(key)

    return _dedupe_auth_jwt_keys(keys)


def _parse_auth_jwt_keys(raw: object) -> tuple[AuthJwtKey, ...]:
    text = _normalize_optional_string(raw)
    if text is None:
        return ()

    if text[0] in "[{":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("AUTH_JWT_KEYS must be valid JSON or kid=secret CSV.") from exc
        return _parse_auth_jwt_key_object(parsed)

    keys: list[AuthJwtKey] = []
    for item in text.split(","):
        part = item.strip()
        if not part:
            continue
        if "=" in part:
            kid, secret = part.split("=", 1)
        elif ":" in part:
            kid, secret = part.split(":", 1)
        else:
            continue
        key = _coerce_auth_jwt_key(secret, default_kid=kid)
        if key is not None:
            keys.append(key)
    return _dedupe_auth_jwt_keys(keys)


def _auth_jwt_keys_from_env(env: MutableMapping[str, str]) -> tuple[AuthJwtKey, ...]:
    keys: list[AuthJwtKey] = []
    for env_key in ("AUTH_JWT_KEYS", "AUTH_JWT_SECRETS", "AUTH_JWT_JWKS"):
        keys.extend(_parse_auth_jwt_keys(env.get(env_key)))
    return _dedupe_auth_jwt_keys(keys)


def _configured_single_auth_secret(
    settings: Any, env: MutableMapping[str, str]
) -> str | None:
    if _normalize_optional_string(env.get("AUTH_JWT_SECRET")) is None:
        return None
    return _normalize_optional_string(settings.auth_jwt_secret)


def _current_auth_jwt_secret(settings: Any, env: MutableMapping[str, str]) -> str | None:
    if settings.auth_jwt_key_id:
        for key in settings.auth_jwt_keys:
            if key.active and key.kid == settings.auth_jwt_key_id:
                return key.secret
        return _configured_single_auth_secret(settings, env)

    for key in settings.auth_jwt_keys:
        if key.active:
            return key.secret
    return _configured_single_auth_secret(settings, env)


def _non_development_environment_sources(env: MutableMapping[str, str]) -> tuple[str, ...]:
    sources: list[str] = []
    for key in ("APP_ENVIRONMENT", "ENVIRONMENT"):
        value = _normalize_optional_string(env.get(key))
        if value is None:
            continue
        if value.lower() not in _DEVELOPMENT_ENVIRONMENT_NAMES:
            sources.append(f"{key}={value}")
    return tuple(sources)


def _validate_non_development_security(settings: Any, env: MutableMapping[str, str]) -> None:
    environment_sources = _non_development_environment_sources(env)
    if not environment_sources:
        return

    failures: list[str] = []
    jwt_secret = _normalize_optional_string(env.get("AUTH_JWT_SECRET"))
    current_secret = _current_auth_jwt_secret(settings, env)
    if jwt_secret in _INSECURE_AUTH_JWT_SECRETS:
        failures.append("AUTH_JWT_SECRET must not use a development or demo default")
    elif current_secret is None:
        failures.append("AUTH_JWT_SECRET must be set or AUTH_JWT_KEYS must provide a signing key")
    elif current_secret in _INSECURE_AUTH_JWT_SECRETS:
        failures.append("AUTH_JWT_KEYS must not use a development or demo default")
    if (
        settings.auth_jwt_key_id
        and settings.auth_jwt_keys
        and not any(
            key.active and key.kid == settings.auth_jwt_key_id for key in settings.auth_jwt_keys
        )
    ):
        failures.append("AUTH_JWT_KEY_ID must match an active AUTH_JWT_KEYS entry")
    if not _normalize_optional_string(settings.auth_jwt_issuer):
        failures.append("AUTH_JWT_ISSUER must be set")
    if settings.auth_access_token_ttl_seconds <= 0:
        failures.append("AUTH_ACCESS_TOKEN_TTL_SECONDS must be greater than 0")
    if not settings.auth_enabled:
        failures.append("AUTH_ENABLED must be true")
    if settings.auth_demo_tokens_enabled:
        failures.append("AUTH_DEMO_TOKENS_ENABLED must be false")
    if not settings.rate_limit_enabled:
        failures.append("RATE_LIMIT_ENABLED must be true")
    if settings.rate_limit_per_minute <= 0:
        failures.append("RATE_LIMIT_PER_MINUTE must be greater than 0")
    if settings.rate_limit_chat_per_minute <= 0:
        failures.append("RATE_LIMIT_CHAT_PER_MINUTE must be greater than 0")
    if not settings.cors_allowed_origins:
        failures.append("CORS_ALLOWED_ORIGINS must be explicitly set")
    if "*" in settings.cors_allowed_origins and settings.cors_allow_credentials:
        failures.append(
            "CORS_ALLOW_CREDENTIALS must be false when CORS_ALLOWED_ORIGINS contains '*'"
        )
    if failures:
        raise ValueError(
            "Unsafe security configuration for non-development environment "
            f"({', '.join(environment_sources)}): {'; '.join(failures)}"
        )
