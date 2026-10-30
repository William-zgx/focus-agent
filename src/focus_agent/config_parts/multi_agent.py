from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from .common import _parse_key_value_json_or_csv
from .env import env_bool, env_float


def load_multi_agent_config(env: MutableMapping[str, str], defaults: Any) -> dict[str, object]:
    return {
        "multi_agent_v2_enabled": env_bool(
            env,
            "MULTI_AGENT_V2_ENABLED",
            default=defaults.multi_agent_v2_enabled,
        ),
        "multi_agent_dag_scheduler_enabled": env_bool(
            env,
            "MULTI_AGENT_DAG_SCHEDULER_ENABLED",
            default=defaults.multi_agent_dag_scheduler_enabled,
        ),
        "multi_agent_resource_lock_enabled": env_bool(
            env,
            "MULTI_AGENT_RESOURCE_LOCK_ENABLED",
            default=defaults.multi_agent_resource_lock_enabled,
        ),
        "multi_agent_message_bus_enabled": env_bool(
            env,
            "MULTI_AGENT_MESSAGE_BUS_ENABLED",
            default=defaults.multi_agent_message_bus_enabled,
        ),
        "multi_agent_async_approval_enabled": env_bool(
            env,
            "MULTI_AGENT_ASYNC_APPROVAL_ENABLED",
            default=defaults.multi_agent_async_approval_enabled,
        ),
        "multi_agent_failure_handler_enabled": env_bool(
            env,
            "MULTI_AGENT_FAILURE_HANDLER_ENABLED",
            default=defaults.multi_agent_failure_handler_enabled,
        ),
        "multi_agent_resource_lock_ttl_seconds": env_float(
            env,
            "MULTI_AGENT_RESOURCE_LOCK_TTL_SECONDS",
            defaults.multi_agent_resource_lock_ttl_seconds,
        ),
        "multi_agent_resource_lock_heartbeat_seconds": env_float(
            env,
            "MULTI_AGENT_RESOURCE_LOCK_HEARTBEAT_SECONDS",
            defaults.multi_agent_resource_lock_heartbeat_seconds,
        ),
        "multi_agent_message_ttl_seconds": env_float(
            env, "MULTI_AGENT_MESSAGE_TTL_SECONDS", defaults.multi_agent_message_ttl_seconds
        ),
        "multi_agent_approval_timeout_seconds": env_float(
            env,
            "MULTI_AGENT_APPROVAL_TIMEOUT_SECONDS",
            defaults.multi_agent_approval_timeout_seconds,
        ),
        "multi_agent_deadlock_check_interval_seconds": env_float(
            env,
            "MULTI_AGENT_DEADLOCK_CHECK_INTERVAL_SECONDS",
            defaults.multi_agent_deadlock_check_interval_seconds,
        ),
        "multi_agent_role_fallback_models": (
            _parse_key_value_json_or_csv(env.get("MULTI_AGENT_ROLE_FALLBACK_MODELS"))
            if env.get("MULTI_AGENT_ROLE_FALLBACK_MODELS") is not None
            else defaults.multi_agent_role_fallback_models
        ),
    }


__all__ = ["load_multi_agent_config"]
