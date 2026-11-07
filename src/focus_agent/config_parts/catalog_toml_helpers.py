from __future__ import annotations

import math
from collections.abc import Callable

from ..core.coercion import optional_str
from .catalog_config_types import (
    CommandHookConfig,
    HooksConfig,
    PermissionRuleConfig,
    PermissionsConfig,
)

_CatalogError = Callable[[str, str], ValueError]
_PERMISSION_ACTIONS = frozenset({"allow", "ask", "deny"})
_PERMISSION_RULE_KEYS = frozenset({"action", "tool", "command", "agent", "reason"})
_COMMAND_HOOK_KEYS = frozenset({"matcher", "command", "timeout_seconds"})


def load_tool_governance_configs(
    raw: dict[str, object],
    *,
    source: str,
    error: _CatalogError,
) -> dict[str, object]:
    permissions = raw.get("permissions")
    if permissions is not None and not isinstance(permissions, dict):
        raise error(source, "permissions must be a TOML table.")
    permissions = permissions or {}
    unknown = set(permissions) - {"rules"}
    if unknown:
        raise error(source, f"permissions has unsupported keys: {_unknown_keys(unknown)}.")

    hooks = raw.get("hooks")
    if hooks is not None and not isinstance(hooks, dict):
        raise error(source, "hooks must be a TOML table.")
    hooks = hooks or {}
    unknown = set(hooks) - {"pre_tool_use", "post_tool_use"}
    if unknown:
        raise error(source, f"hooks has unsupported keys: {_unknown_keys(unknown)}.")

    return {
        "permissions": PermissionsConfig(
            rules=_load_permission_rules(
                permissions.get("rules"),
                source=source,
                error=error,
            )
        ),
        "hooks": HooksConfig(
            pre_tool_use=_load_command_hooks(
                hooks.get("pre_tool_use"),
                section="pre_tool_use",
                source=source,
                error=error,
            ),
            post_tool_use=_load_command_hooks(
                hooks.get("post_tool_use"),
                section="post_tool_use",
                source=source,
                error=error,
            ),
        ),
    }


def _load_permission_rules(
    raw: object,
    *,
    source: str,
    error: _CatalogError,
) -> tuple[PermissionRuleConfig, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise error(source, "permissions.rules must be an array of TOML tables.")
    rules: list[PermissionRuleConfig] = []
    for index, item in enumerate(raw):
        location = f"permissions.rules[{index}]"
        if not isinstance(item, dict):
            raise error(source, f"{location} must be a TOML table.")
        unknown = set(item) - _PERMISSION_RULE_KEYS
        if unknown:
            raise error(source, f"{location} has unsupported keys: {_unknown_keys(unknown)}.")
        action = (optional_str(item.get("action")) or "").lower()
        if action not in _PERMISSION_ACTIONS:
            allowed = ", ".join(sorted(_PERMISSION_ACTIONS))
            raise error(source, f"{location}.action must be one of: {allowed}.")
        rules.append(
            PermissionRuleConfig(
                action=action,
                tool=optional_str(item.get("tool")) or "*",
                command=optional_str(item.get("command")),
                agent=optional_str(item.get("agent")) or "*",
                reason=optional_str(item.get("reason")),
            )
        )
    return tuple(rules)


def _load_command_hooks(
    raw: object,
    *,
    section: str,
    source: str,
    error: _CatalogError,
) -> tuple[CommandHookConfig, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise error(source, f"hooks.{section} must be an array of TOML tables.")
    hooks: list[CommandHookConfig] = []
    for index, item in enumerate(raw):
        location = f"hooks.{section}[{index}]"
        if not isinstance(item, dict):
            raise error(source, f"{location} must be a TOML table.")
        unknown = set(item) - _COMMAND_HOOK_KEYS
        if unknown:
            raise error(source, f"{location} has unsupported keys: {_unknown_keys(unknown)}.")
        raw_command = item.get("command")
        if (
            not isinstance(raw_command, list)
            or not raw_command
            or not all(isinstance(part, str) and part.strip() for part in raw_command)
        ):
            raise error(source, f"{location}.command must be a non-empty array of strings.")
        timeout_raw = item.get("timeout_seconds", 10.0)
        try:
            timeout_seconds = float(timeout_raw)
        except (TypeError, ValueError) as exc:
            raise error(source, f"{location}.timeout_seconds must be a number.") from exc
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise error(source, f"{location}.timeout_seconds must be finite and positive.")
        hooks.append(
            CommandHookConfig(
                command=tuple(part.strip() for part in raw_command),
                matcher=optional_str(item.get("matcher")) or "*",
                timeout_seconds=timeout_seconds,
            )
        )
    return tuple(hooks)


def _unknown_keys(keys: set[str]) -> str:
    return ", ".join(sorted(str(key) for key in keys))


def _load_string_mapping(
    raw: object,
    *,
    source: str,
    location: str,
    error: _CatalogError,
) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise error(source, f"{location} environment mappings must be TOML tables.")
    values: dict[str, str] = {}
    for key, value in raw.items():
        if not str(key).strip() or not isinstance(value, str):
            raise error(
                source,
                f"{location} environment mapping keys must be non-empty and values must be strings.",
            )
        values[str(key)] = value
    return values


__all__ = ["_load_string_mapping", "load_tool_governance_configs"]
