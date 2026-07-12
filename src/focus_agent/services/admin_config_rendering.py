from __future__ import annotations

import importlib
import re
from dataclasses import fields, is_dataclass, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from focus_agent.api.contract_models.admin_config import (
        AdminModelConfigPayload,
        AdminModelProviderConfigPayload,
        AdminToolConfigPayload,
        AdminToolConfigUpdateRequest,
    )

from focus_agent.config import (
    ConfiguredModel,
    ModelCatalogConfig,
    ProviderConfig,
    ToolCatalogConfig,
)

from .admin_config_fields import ConfigFieldSpec


def _admin_config_contracts():
    return importlib.import_module("focus_agent.api.contract_models.admin_config")


def _admin_config_error(message: str) -> ValueError:
    from .admin_config import AdminConfigError

    return AdminConfigError(message)


def _provider_payloads(
    payloads: list[AdminModelProviderConfigPayload] | None,
    current: tuple[ProviderConfig, ...],
) -> list[ProviderConfig]:
    if payloads is None:
        return [replace(provider, api_key_default=None) for provider in current]
    providers: list[ProviderConfig] = []
    for payload in payloads:
        api_key_default = _provider_api_key_default(payload)
        providers.append(
            ProviderConfig(
                id=payload.id,
                label=payload.label,
                backend_provider=payload.backend_provider,
                aliases=tuple(payload.aliases),
                logo_slug=payload.logo_slug,
                logo_letter=payload.logo_letter,
                base_url_env=payload.base_url_env,
                base_url_default=payload.base_url_default,
                api_key_env=payload.api_key_env,
                api_key_default=api_key_default,
            )
        )
    return providers


def _provider_api_key_default(
    payload: AdminModelProviderConfigPayload,
) -> str | None:
    if payload.api_key_default is None:
        return None
    if str(payload.api_key_default).strip():
        raise _admin_config_error(
            "api_key_default cannot be persisted by Admin config; use api_key_env instead."
        )
    return None


def _model_payloads(
    payloads: list[AdminModelConfigPayload] | None,
    current: tuple[ConfiguredModel, ...],
) -> list[ConfiguredModel]:
    if payloads is None:
        return list(current)
    return [
        ConfiguredModel(
            id=payload.id,
            label=payload.label,
            supports_thinking=payload.supports_thinking,
            default_thinking_enabled=payload.default_thinking_enabled,
            request_kwargs=dict(payload.request_kwargs),
            thinking_enabled_request_kwargs=dict(payload.thinking_enabled_request_kwargs),
            thinking_disabled_request_kwargs=dict(payload.thinking_disabled_request_kwargs),
            thinking_disabled_model_name=payload.thinking_disabled_model_name,
            reasoning_effort=payload.reasoning_effort,
            no_temperature=payload.no_temperature,
            thinking_enable_extra_body_type=payload.thinking_enable_extra_body_type,
            thinking_disable_extra_body_type=payload.thinking_disable_extra_body_type,
            thinking_disable_switch_model=payload.thinking_disable_switch_model,
        )
        for payload in payloads
    ]


def _render_model_catalog_toml(catalog: ModelCatalogConfig) -> str:
    lines: list[str] = []
    _append_toml_key(lines, "default_model", catalog.default_model)
    _append_toml_key(lines, "helper_model", catalog.helper_model)
    _append_toml_key(lines, "model_choices", list(catalog.model_choices))
    if lines:
        lines.append("")

    for provider in catalog.providers:
        lines.append("[[providers]]")
        for key, value in _dataclass_values(provider).items():
            _append_toml_key(lines, key, value)
        lines.append("")

    for model in catalog.models:
        lines.append("[[models]]")
        for key, value in _dataclass_values(model).items():
            _append_toml_key(lines, key, value)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _render_tool_catalog_toml(
    current: ToolCatalogConfig,
    payload: AdminToolConfigUpdateRequest,
) -> str:
    tools_by_name = {
        name: _tool_payload_from_current(name, getattr(current, name), current)
        for name in current.section_names
        if hasattr(current, name)
    }
    for item in payload.tools or []:
        if item.name not in tools_by_name:
            raise _admin_config_error(f"Unsupported tool config section: {item.name}")
        tools_by_name[item.name] = _merge_tool_payload(
            item,
            existing=getattr(current, item.name),
        )

    contracts = _admin_config_contracts()
    providers = [
        contracts.AdminToolProviderConfigPayload(
            id=provider.id,
            enabled=provider.enabled,
            order=provider.order,
            metadata=dict(provider.metadata),
            overrides=list(provider.overrides),
        )
        for provider in current.providers
    ]
    if payload.providers is not None:
        providers = payload.providers

    lines: list[str] = []
    for name, tool in tools_by_name.items():
        lines.append(f"[{name}]")
        _append_toml_key(lines, "enabled", tool.enabled)
        _append_toml_key(lines, "label", tool.label)
        _append_toml_key(lines, "description", tool.description)
        for key, value in tool.settings.items():
            _append_toml_key(lines, key, value)
        _append_toml_key(lines, "metadata", tool.metadata)
        lines.append("")

    for provider in providers:
        lines.append("[[providers]]")
        _append_toml_key(lines, "id", provider.id)
        _append_toml_key(lines, "enabled", provider.enabled)
        _append_toml_key(lines, "order", provider.order)
        _append_toml_key(lines, "metadata", provider.metadata)
        _append_toml_key(lines, "overrides", provider.overrides)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _tool_payload_from_current(
    name: str,
    config: Any,
    catalog: ToolCatalogConfig,
) -> AdminToolConfigPayload:
    values = _dataclass_values(config)
    contracts = _admin_config_contracts()
    return contracts.AdminToolConfigPayload(
        name=name,
        enabled=bool(values.pop("enabled", True)),
        label=str(values.pop("label", name)),
        description=str(values.pop("description", "")),
        settings={key: value for key, value in values.items() if value is not None},
        metadata=catalog.metadata_overlay_for(name),
    )


def _merge_tool_payload(
    payload: AdminToolConfigPayload,
    *,
    existing: Any,
) -> AdminToolConfigPayload:
    existing_values = _dataclass_values(existing)
    allowed_settings = set(existing_values) - {"enabled", "label", "description"}
    unknown_settings = set(payload.settings) - allowed_settings
    if unknown_settings:
        unknown = ", ".join(sorted(unknown_settings))
        raise _admin_config_error(f"{payload.name} has unsupported setting keys: {unknown}")

    settings = {
        key: value
        for key, value in existing_values.items()
        if key in allowed_settings and value is not None
    }
    settings.update(payload.settings)
    contracts = _admin_config_contracts()
    return contracts.AdminToolConfigPayload(
        name=payload.name,
        enabled=payload.enabled
        if payload.enabled is not None
        else bool(existing_values.get("enabled", True)),
        label=payload.label or str(existing_values.get("label") or payload.name),
        description=payload.description or str(existing_values.get("description") or ""),
        settings=settings,
        metadata=dict(payload.metadata),
    )


def _field_or_existing(payload: Any, field_name: str, existing: Any) -> Any:
    fields_set = getattr(payload, "model_fields_set", set())
    return getattr(payload, field_name) if field_name in fields_set else existing


def _dataclass_values(value: Any) -> dict[str, Any]:
    if not is_dataclass(value):
        return {}
    return {field.name: getattr(value, field.name) for field in fields(value)}


def _append_toml_key(lines: list[str], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, (tuple, list, dict)) and not value:
        return
    lines.append(f"{key} = {_toml_value(value)}")


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
        )
        return f'"{escaped}"'
    if isinstance(value, tuple | list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        items = [
            f"{_toml_bare_or_quoted_key(str(key))} = {_toml_value(item)}"
            for key, item in value.items()
            if item is not None
        ]
        return "{ " + ", ".join(items) + " }"
    return _toml_value(str(value))


def _toml_bare_or_quoted_key(key: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return key
    return _toml_value(key)


def _coerce_config_value(value: Any, spec: ConfigFieldSpec) -> object:
    if value is None:
        raise _admin_config_error(f"{spec.key} cannot be null.")
    if spec.value_type == "boolean":
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise _admin_config_error(f"{spec.key} must be a boolean.")
    if spec.value_type == "integer":
        return int(value)
    if spec.value_type == "float":
        return float(value)
    if spec.value_type == "string":
        text = str(value).strip()
        if spec.options and text not in spec.options:
            allowed = ", ".join(spec.options)
            raise _admin_config_error(f"{spec.key} must be one of: {allowed}.")
        return text
    raise _admin_config_error(f"{spec.key} has unsupported type {spec.value_type}.")
