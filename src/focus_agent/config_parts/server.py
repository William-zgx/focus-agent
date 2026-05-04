from __future__ import annotations

from typing import Any, MutableMapping

from .common import _env_bool, _split_csv


def load_server_config(env: MutableMapping[str, str], defaults: Any) -> dict[str, object]:
    return {
        "api_host": env.get("API_HOST", defaults.api_host),
        "api_port": int(env.get("API_PORT", str(defaults.api_port))),
        "api_reload": _env_bool(env, "API_RELOAD", default=defaults.api_reload),
        "app_version": env.get("APP_VERSION", defaults.app_version),
        "app_environment": (
            env.get("APP_ENVIRONMENT") or env.get("ENVIRONMENT") or defaults.app_environment
        ),
        "deployment_name": env.get("DEPLOYMENT_NAME") or defaults.deployment_name,
        "web_app_dist_dir": env.get("WEB_APP_DIST_DIR") or None,
        "web_app_dev_server_url": env.get("WEB_APP_DEV_SERVER_URL") or None,
        "sse_heartbeat_seconds": float(
            env.get("SSE_HEARTBEAT_SECONDS", str(defaults.sse_heartbeat_seconds))
        ),
        "cors_allowed_origins": _split_csv(env.get("CORS_ALLOWED_ORIGINS")),
        "cors_allow_credentials": _env_bool(
            env, "CORS_ALLOW_CREDENTIALS", default=defaults.cors_allow_credentials
        ),
        "rate_limit_enabled": _env_bool(
            env, "RATE_LIMIT_ENABLED", default=defaults.rate_limit_enabled
        ),
        "rate_limit_per_minute": int(
            env.get("RATE_LIMIT_PER_MINUTE", str(defaults.rate_limit_per_minute))
        ),
        "rate_limit_chat_per_minute": int(
            env.get("RATE_LIMIT_CHAT_PER_MINUTE", str(defaults.rate_limit_chat_per_minute))
        ),
    }
