from __future__ import annotations

from typing import Any, MutableMapping

from .auth import _auth_jwt_keys_from_env
from .common import _env_bool, _split_csv


def load_auth_config(env: MutableMapping[str, str], defaults: Any) -> dict[str, object]:
    return {
        "auth_enabled": _env_bool(env, "AUTH_ENABLED", default=defaults.auth_enabled),
        "auth_demo_tokens_enabled": _env_bool(
            env, "AUTH_DEMO_TOKENS_ENABLED", default=defaults.auth_demo_tokens_enabled
        ),
        "auth_jwt_secret": env.get("AUTH_JWT_SECRET", defaults.auth_jwt_secret),
        "auth_jwt_key_id": (
            env.get("AUTH_JWT_KEY_ID")
            or env.get("AUTH_JWT_CURRENT_KID")
            or defaults.auth_jwt_key_id
        ),
        "auth_jwt_keys": _auth_jwt_keys_from_env(env),
        "auth_jwt_issuer": env.get("AUTH_JWT_ISSUER", defaults.auth_jwt_issuer),
        "auth_jwt_audience": env.get("AUTH_JWT_AUDIENCE") or defaults.auth_jwt_audience,
        "auth_access_token_ttl_seconds": int(
            env.get(
                "AUTH_ACCESS_TOKEN_TTL_SECONDS",
                str(defaults.auth_access_token_ttl_seconds),
            )
        ),
        "auth_bootstrap_admin_user_ids": (
            _split_csv(env.get("AUTH_BOOTSTRAP_ADMIN_USER_IDS"))
            if env.get("AUTH_BOOTSTRAP_ADMIN_USER_IDS") is not None
            else defaults.auth_bootstrap_admin_user_ids
        ),
        "auth_access_cookie_name": env.get(
            "AUTH_ACCESS_COOKIE_NAME", defaults.auth_access_cookie_name
        ),
        "auth_refresh_cookie_name": env.get(
            "AUTH_REFRESH_COOKIE_NAME", defaults.auth_refresh_cookie_name
        ),
        "auth_refresh_token_ttl_seconds": int(
            env.get(
                "AUTH_REFRESH_TOKEN_TTL_SECONDS",
                str(defaults.auth_refresh_token_ttl_seconds),
            )
        ),
        "auth_cookie_secure": _env_bool(
            env, "AUTH_COOKIE_SECURE", default=defaults.auth_cookie_secure
        ),
        "auth_cookie_samesite": env.get("AUTH_COOKIE_SAMESITE", defaults.auth_cookie_samesite),
    }
