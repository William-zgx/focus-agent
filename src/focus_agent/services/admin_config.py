from __future__ import annotations

import importlib
import os
import re
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from focus_agent.api.contract_models.admin_config import (
        AdminConfigModelSectionResponse,
        AdminConfigPolicySectionResponse,
        AdminConfigResponse,
        AdminConfigSkillResponse,
        AdminConfigSkillSectionResponse,
        AdminConfigSourceResponse,
        AdminConfigSystemSectionResponse,
        AdminConfigToolResponse,
        AdminConfigToolSectionResponse,
        AdminConfigValueResponse,
        AdminModelConfigPayload,
        AdminModelConfigUpdateRequest,
        AdminModelProviderConfigPayload,
        AdminPolicyConfigUpdateRequest,
        AdminSkillConfigUpdateRequest,
        AdminToolConfigPayload,
        AdminToolConfigUpdateRequest,
    )

from focus_agent.config import (
    DEFAULT_LOCAL_ENV_FILE,
    DEFAULT_MODEL_CATALOG_DOC,
    DEFAULT_TOOL_CATALOG_DOC,
    ConfiguredModel,
    ModelCatalogConfig,
    ModelCatalogValidationError,
    ProviderConfig,
    ToolCatalogConfig,
    load_model_catalog_toml,
    load_tool_catalog_document,
)
from focus_agent.engine.runtime import AppRuntime
from focus_agent.skills.registry import SkillRegistry
from focus_agent.skills.registry_paths import _normalize_skill_id

from .admin_config_fields import (
    _POLICY_FIELD_SPECS,
    _SENSITIVE_FIELD_NAMES,
    _SYSTEM_FIELD_SPECS,
    ConfigFieldSpec,
)

_ENV_ASSIGNMENT_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=\s*(.*)$")
_SKILLS_ENABLED_ENV = "FOCUS_AGENT_SKILLS_ENABLED"
_SKILL_DIRECTORIES_ENV = "FOCUS_AGENT_SKILLS_DIRS"
_SKILL_INSTALL_DIRECTORY_ENV = "SKILL_INSTALL_DIRECTORY"
_SKILL_SOURCES_ENABLED_ENV = "SKILL_SOURCES_ENABLED"
_SKILL_SOURCE_LOCATIONS_ENV = "SKILL_SOURCE_LOCATIONS"
_SKILL_TRUSTED_SOURCES_ENV = "SKILL_TRUSTED_SOURCES"
_SKILL_SEMANTIC_MATCH_ENABLED_ENV = "SKILL_SEMANTIC_MATCH_ENABLED"
_SKILL_SEMANTIC_MATCH_THRESHOLD_ENV = "SKILL_SEMANTIC_MATCH_THRESHOLD"
_SKILL_DISABLED_IDS_ENV = "SKILL_DISABLED_IDS"


def _admin_config_contracts():
    return importlib.import_module("focus_agent.api.contract_models.admin_config")


class AdminConfigError(ValueError):
    """Raised when an administrator submits an invalid configuration payload."""


def read_admin_config(
    runtime: AppRuntime,
    *,
    message: str | None = None,
    updated_by: str | None = None,
) -> AdminConfigResponse:
    settings = runtime.settings
    contracts = _admin_config_contracts()
    return contracts.AdminConfigResponse(
        models=_build_model_section(settings),
        tools=_build_tool_section(settings),
        skills=_build_skill_section(runtime),
        policies=_build_policy_section(settings),
        system=_build_system_section(settings),
        updated_by=updated_by,
        message=message,
    )


def update_admin_model_config(
    runtime: AppRuntime,
    payload: AdminModelConfigUpdateRequest,
    *,
    updated_by: str | None = None,
) -> AdminConfigResponse:
    settings = runtime.settings
    current = getattr(settings, "model_catalog", ModelCatalogConfig())
    updated_catalog = ModelCatalogConfig(
        default_model=_field_or_existing(payload, "default_model", current.default_model),
        helper_model=_field_or_existing(payload, "helper_model", current.helper_model),
        model_choices=tuple(
            _field_or_existing(payload, "model_choices", current.model_choices) or ()
        ),
        providers=tuple(_provider_payloads(payload.providers, current.providers)),
        models=tuple(_model_payloads(payload.models, current.models)),
    )
    content = _render_model_catalog_toml(updated_catalog)
    loaded = load_model_catalog_toml(content, source=str(_model_catalog_path(settings)))
    _write_text_atomic(_model_catalog_path(settings), content)

    settings.model_catalog = loaded
    settings.model = loaded.default_model or getattr(settings, "model", None)
    settings.helper_model = loaded.helper_model
    settings.model_choices = loaded.model_choices
    return read_admin_config(
        runtime,
        message="Model configuration saved.",
        updated_by=updated_by,
    )


def update_admin_tool_config(
    runtime: AppRuntime,
    payload: AdminToolConfigUpdateRequest,
    *,
    updated_by: str | None = None,
) -> AdminConfigResponse:
    settings = runtime.settings
    current = getattr(settings, "tool_catalog", ToolCatalogConfig())
    content = _render_tool_catalog_toml(current, payload)
    path = _tool_catalog_path(settings)
    _write_text_atomic(path, content)
    loaded = load_tool_catalog_document(path, environ=_settings_env(settings))

    settings.tool_catalog = loaded
    settings.web_search = loaded.web_search
    return read_admin_config(
        runtime,
        message="Tool configuration saved. Restart the API to rebuild registered tools.",
        updated_by=updated_by,
    )


def update_admin_skill_config(
    runtime: AppRuntime,
    payload: AdminSkillConfigUpdateRequest,
    *,
    updated_by: str | None = None,
) -> AdminConfigResponse:
    settings = runtime.settings
    updates: dict[str, object | None] = {}

    if payload.enabled is not None:
        settings.skills_enabled = bool(payload.enabled)
        updates[_SKILLS_ENABLED_ENV] = settings.skills_enabled
    if payload.skill_directories is not None:
        settings.skill_directories = _coerce_string_tuple(
            payload.skill_directories,
            field_name="skill_directories",
            allow_empty=False,
        )
        updates[_SKILL_DIRECTORIES_ENV] = _csv_env_value(settings.skill_directories)
    if payload.install_directory is not None:
        install_directory = str(payload.install_directory).strip()
        if not install_directory:
            raise AdminConfigError("install_directory cannot be empty.")
        settings.skill_install_directory = install_directory
        updates[_SKILL_INSTALL_DIRECTORY_ENV] = install_directory
    if payload.sources_enabled is not None:
        settings.skill_sources_enabled = _coerce_string_tuple(
            payload.sources_enabled,
            field_name="sources_enabled",
            normalize=True,
        )
        updates[_SKILL_SOURCES_ENABLED_ENV] = _csv_env_value(settings.skill_sources_enabled)
    if payload.source_locations is not None:
        settings.skill_source_locations = _coerce_string_tuple(
            payload.source_locations,
            field_name="source_locations",
        )
        updates[_SKILL_SOURCE_LOCATIONS_ENV] = _csv_env_value(settings.skill_source_locations)
    if payload.trusted_sources is not None:
        settings.skill_trusted_sources = _coerce_string_tuple(
            payload.trusted_sources,
            field_name="trusted_sources",
            normalize=True,
        )
        updates[_SKILL_TRUSTED_SOURCES_ENV] = _csv_env_value(settings.skill_trusted_sources)
    if payload.disabled_skill_ids is not None:
        settings.skill_disabled_ids = _coerce_disabled_skill_ids(
            runtime,
            payload.disabled_skill_ids,
        )
        updates[_SKILL_DISABLED_IDS_ENV] = _csv_env_value(settings.skill_disabled_ids)
    if payload.skills is not None:
        disabled_ids = set(getattr(settings, "skill_disabled_ids", ()) or ())
        known_ids = _known_skill_ids(runtime)
        for item in payload.skills:
            skill_id = _normalize_skill_id(item.skill_id)
            if not skill_id:
                raise AdminConfigError("skill_id cannot be empty.")
            if known_ids and skill_id not in known_ids:
                raise AdminConfigError(f"Unknown skill: {item.skill_id}")
            if item.enabled:
                disabled_ids.discard(skill_id)
            else:
                disabled_ids.add(skill_id)
        settings.skill_disabled_ids = tuple(sorted(disabled_ids))
        updates[_SKILL_DISABLED_IDS_ENV] = _csv_env_value(settings.skill_disabled_ids)
    if payload.semantic_match_enabled is not None:
        settings.skill_semantic_match_enabled = bool(payload.semantic_match_enabled)
        updates[_SKILL_SEMANTIC_MATCH_ENABLED_ENV] = settings.skill_semantic_match_enabled
    if payload.semantic_match_threshold is not None:
        threshold = float(payload.semantic_match_threshold)
        if threshold < 0:
            raise AdminConfigError("semantic_match_threshold must be greater than or equal to 0.")
        settings.skill_semantic_match_threshold = threshold
        updates[_SKILL_SEMANTIC_MATCH_THRESHOLD_ENV] = threshold

    if updates:
        _write_local_env_updates(_local_env_path(settings), updates)
        for key, value in updates.items():
            if value is None:
                settings.resolved_env.pop(key, None)
            else:
                settings.resolved_env[key] = _format_env_value(value)

    refresh_result = _reload_runtime_skill_registry(runtime)
    if payload.refresh and not updates:
        refresh_result = _refresh_runtime_skill_registry(runtime)

    return read_admin_config(
        runtime,
        message=_skill_update_message(bool(updates), refresh_result),
        updated_by=updated_by,
    )


def refresh_admin_skill_config(
    runtime: AppRuntime,
    *,
    updated_by: str | None = None,
) -> AdminConfigResponse:
    refresh_result = _refresh_runtime_skill_registry(runtime)
    return read_admin_config(
        runtime,
        message=f"Skill index refreshed. {refresh_result.get('count', 0)} skills available.",
        updated_by=updated_by,
    )


def update_admin_policy_config(
    runtime: AppRuntime,
    payload: AdminPolicyConfigUpdateRequest,
    *,
    updated_by: str | None = None,
) -> AdminConfigResponse:
    if not payload.values:
        return read_admin_config(
            runtime,
            message="No policy values changed.",
            updated_by=updated_by,
        )

    settings = runtime.settings
    spec_by_key = {spec.key: spec for spec in _POLICY_FIELD_SPECS}
    updates: dict[str, object | None] = {}
    for key, raw_value in payload.values.items():
        spec = spec_by_key.get(key)
        if spec is None:
            raise AdminConfigError(f"Unsupported policy config key: {key}")
        value = _coerce_config_value(raw_value, spec)
        updates[spec.env_key] = value
        setattr(settings, spec.key, value)
        settings.resolved_env[spec.env_key] = _format_env_value(value)

    _write_local_env_updates(_local_env_path(settings), updates)
    return read_admin_config(
        runtime,
        message="Policy configuration saved. Restart the API for startup-time policies.",
        updated_by=updated_by,
    )


def _build_model_section(settings: Any) -> AdminConfigModelSectionResponse:
    catalog = getattr(settings, "model_catalog", ModelCatalogConfig())
    env = _settings_env(settings)
    source = _source_response(_model_catalog_path(settings))
    contracts = _admin_config_contracts()
    return contracts.AdminConfigModelSectionResponse(
        source=source,
        default_model=getattr(settings, "model", None) or catalog.default_model,
        helper_model=getattr(settings, "helper_model", None) or catalog.helper_model,
        model_choices=list(getattr(settings, "model_choices", ()) or catalog.model_choices),
        providers=[
            contracts.AdminConfigProviderResponse(
                id=provider.id,
                label=provider.label,
                backend_provider=provider.backend_provider,
                aliases=list(provider.aliases),
                logo_slug=provider.logo_slug,
                logo_letter=provider.logo_letter,
                base_url_env=provider.base_url_env,
                base_url_default=provider.base_url_default,
                base_url_configured=_configured_env_value(
                    env, provider.base_url_env, provider.base_url_default
                ),
                api_key_env=provider.api_key_env,
                api_key_configured=_configured_env_value(
                    env, provider.api_key_env, provider.api_key_default
                ),
            )
            for provider in catalog.providers
        ],
        models=[
            contracts.AdminConfigModelResponse(
                id=model.id,
                label=model.label,
                supports_thinking=model.supports_thinking,
                default_thinking_enabled=model.default_thinking_enabled,
                request_kwargs=dict(model.request_kwargs),
                thinking_enabled_request_kwargs=dict(model.thinking_enabled_request_kwargs),
                thinking_disabled_request_kwargs=dict(model.thinking_disabled_request_kwargs),
                thinking_disabled_model_name=model.thinking_disabled_model_name,
                reasoning_effort=model.reasoning_effort,
                no_temperature=model.no_temperature,
                thinking_enable_extra_body_type=model.thinking_enable_extra_body_type,
                thinking_disable_extra_body_type=model.thinking_disable_extra_body_type,
                thinking_disable_switch_model=model.thinking_disable_switch_model,
            )
            for model in catalog.models
        ],
    )


def _build_tool_section(settings: Any) -> AdminConfigToolSectionResponse:
    catalog = getattr(settings, "tool_catalog", ToolCatalogConfig())
    contracts = _admin_config_contracts()
    return contracts.AdminConfigToolSectionResponse(
        source=_source_response(_tool_catalog_path(settings)),
        tools=[
            _tool_response(name, getattr(catalog, name), catalog.metadata_overlay_for(name))
            for name in catalog.section_names
            if hasattr(catalog, name)
        ],
        providers=[
            contracts.AdminConfigToolProviderResponse(
                id=provider.id,
                enabled=provider.enabled,
                order=provider.order,
                metadata=dict(provider.metadata),
                overrides=list(provider.overrides),
            )
            for provider in catalog.providers
        ],
    )


def _build_skill_section(runtime: AppRuntime) -> AdminConfigSkillSectionResponse:
    settings = runtime.settings
    registry = _skill_registry_for_response(runtime)
    skills = registry.all_skills()
    contracts = _admin_config_contracts()
    return contracts.AdminConfigSkillSectionResponse(
        source=_source_response(_local_env_path(settings)),
        enabled=bool(getattr(settings, "skills_enabled", True)),
        install_directory=_source_response(
            Path(
                getattr(settings, "skill_install_directory", ".focus_agent/skills")
                or ".focus_agent/skills"
            ).expanduser()
        ),
        skill_directories=[
            _source_response(Path(path).expanduser())
            for path in getattr(settings, "skill_directories", ()) or ()
            if str(path).strip()
        ],
        disabled_skill_ids=list(getattr(settings, "skill_disabled_ids", ()) or ()),
        sources_enabled=list(getattr(settings, "skill_sources_enabled", ()) or ()),
        source_locations=list(getattr(settings, "skill_source_locations", ()) or ()),
        trusted_sources=list(getattr(settings, "skill_trusted_sources", ()) or ()),
        sources=[
            contracts.AdminConfigSkillSourceResponse(
                source_id=str(source.get("source_id") or ""),
                source_type=str(source.get("source_type") or ""),
                label=str(source.get("label") or source.get("source_id") or ""),
                enabled=bool(source.get("enabled", True)),
                trusted=bool(source.get("trusted", True)),
                location=source.get("location"),
                metadata=dict(source.get("metadata") or {}),
            )
            for source in registry.list_sources()
        ],
        catalog=[_skill_response(skill, registry=registry) for skill in skills],
        semantic_match_enabled=bool(getattr(settings, "skill_semantic_match_enabled", True)),
        semantic_match_threshold=float(getattr(settings, "skill_semantic_match_threshold", 0.22)),
        refresh=contracts.AdminConfigSkillRefreshResponse(
            available=True,
            refreshed=False,
            count=len(skills),
        ),
        requires_restart=False,
    )


def _build_policy_section(settings: Any) -> AdminConfigPolicySectionResponse:
    contracts = _admin_config_contracts()
    return contracts.AdminConfigPolicySectionResponse(
        source=_source_response(_local_env_path(settings)),
        items=[_value_response(settings, spec, editable=True) for spec in _POLICY_FIELD_SPECS],
    )


def _build_system_section(settings: Any) -> AdminConfigSystemSectionResponse:
    contracts = _admin_config_contracts()
    return contracts.AdminConfigSystemSectionResponse(
        source=_source_response(_local_env_path(settings)),
        items=[
            _value_response(
                settings,
                spec,
                editable=False,
                sensitive=spec.key in _SENSITIVE_FIELD_NAMES,
            )
            for spec in _SYSTEM_FIELD_SPECS
        ],
    )


def _value_response(
    settings: Any,
    spec: ConfigFieldSpec,
    *,
    editable: bool,
    sensitive: bool = False,
) -> AdminConfigValueResponse:
    value = getattr(settings, spec.key, None)
    configured = None
    if sensitive:
        configured = bool(value)
        value = None
    contracts = _admin_config_contracts()
    return contracts.AdminConfigValueResponse(
        key=spec.key,
        env_key=spec.env_key,
        label=spec.label,
        value=value,
        value_type=spec.value_type,
        source="local_env",
        editable=editable,
        sensitive=sensitive,
        configured=configured,
        requires_restart=spec.requires_restart,
        description=spec.description,
        options=list(spec.options),
    )


def _tool_response(
    name: str,
    config: Any,
    metadata: dict[str, object],
) -> AdminConfigToolResponse:
    values = _dataclass_values(config)
    label = str(values.pop("label", name.replace("_", " ").title()))
    description = str(values.pop("description", ""))
    enabled = bool(values.pop("enabled", True))
    settings = {
        key: value
        for key, value in values.items()
        if key not in _SENSITIVE_FIELD_NAMES and value is not None
    }
    contracts = _admin_config_contracts()
    return contracts.AdminConfigToolResponse(
        name=name,
        label=label,
        description=description,
        enabled=enabled,
        settings=settings,
        metadata=dict(metadata),
    )


def _skill_response(skill: Any, *, registry: Any) -> AdminConfigSkillResponse:
    contracts = _admin_config_contracts()
    prompt_mode = getattr(skill, "prompt_mode", None)
    return contracts.AdminConfigSkillResponse(
        skill_id=str(getattr(skill, "skill_id", "")),
        description=str(getattr(skill, "description", "")),
        enabled=bool(registry.is_skill_enabled(getattr(skill, "skill_id", ""))),
        triggers=list(getattr(skill, "triggers", ()) or ()),
        when_to_use=list(getattr(skill, "when_to_use", ()) or ()),
        recommended_tools=list(getattr(skill, "recommended_tools", ()) or ()),
        prompt_mode=getattr(prompt_mode, "value", None),
        path=str(getattr(skill, "path", "")),
        source_id=str(getattr(skill, "source_id", "")),
        source_type=str(getattr(skill, "source_type", "")),
        version=getattr(skill, "version", None),
        trust_level=str(getattr(skill, "trust_level", "trusted")),
        install_state=str(getattr(skill, "install_state", "installed")),
        provenance=getattr(skill, "provenance", None),
        checksum=getattr(skill, "checksum", None),
        capability_requirements=list(getattr(skill, "capability_requirements", ()) or ()),
    )


def _skill_registry_for_response(runtime: AppRuntime) -> SkillRegistry:
    registry = getattr(runtime, "skill_registry", None)
    if isinstance(registry, SkillRegistry):
        return registry
    return SkillRegistry.from_settings(runtime.settings)


def _known_skill_ids(runtime: AppRuntime) -> set[str]:
    registries = [_skill_registry_for_response(runtime), SkillRegistry.from_settings(runtime.settings)]
    return {
        _normalize_skill_id(skill.skill_id)
        for registry in registries
        for skill in registry.all_skills()
    }


def _coerce_disabled_skill_ids(
    runtime: AppRuntime,
    values: list[str],
) -> tuple[str, ...]:
    known_ids = _known_skill_ids(runtime)
    disabled_ids: set[str] = set()
    for raw_value in values:
        skill_id = _normalize_skill_id(raw_value)
        if not skill_id:
            continue
        if known_ids and skill_id not in known_ids:
            raise AdminConfigError(f"Unknown skill: {raw_value}")
        disabled_ids.add(skill_id)
    return tuple(sorted(disabled_ids))


def _coerce_string_tuple(
    values: list[str],
    *,
    field_name: str,
    allow_empty: bool = True,
    normalize: bool = False,
) -> tuple[str, ...]:
    items: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item:
            continue
        items.append(item.lower() if normalize else item)
    if not allow_empty and not items:
        raise AdminConfigError(f"{field_name} cannot be empty.")
    return tuple(dict.fromkeys(items))


def _csv_env_value(values: tuple[str, ...]) -> str:
    return ",".join(values)


def _reload_runtime_skill_registry(runtime: AppRuntime) -> dict[str, Any]:
    registry = getattr(runtime, "skill_registry", None)
    if isinstance(registry, SkillRegistry):
        return registry.reload_from_settings(runtime.settings)
    registry = SkillRegistry.from_settings(runtime.settings)
    try:
        runtime.skill_registry = registry
    except Exception:
        pass
    return {
        "success": True,
        "enabled": registry.enabled,
        "previous_count": 0,
        "count": len(registry.all_skills()),
        "sources": registry.list_sources(),
    }


def _refresh_runtime_skill_registry(runtime: AppRuntime) -> dict[str, Any]:
    registry = getattr(runtime, "skill_registry", None)
    if isinstance(registry, SkillRegistry):
        return registry.refresh_index()
    return _reload_runtime_skill_registry(runtime)


def _skill_update_message(changed: bool, refresh_result: dict[str, Any]) -> str:
    count = int(refresh_result.get("count") or 0)
    if changed:
        return f"Skill configuration saved. {count} skills available."
    return f"Skill index refreshed. {count} skills available."


def _provider_payloads(
    payloads: list[AdminModelProviderConfigPayload] | None,
    current: tuple[ProviderConfig, ...],
) -> list[ProviderConfig]:
    if payloads is None:
        return list(current)
    current_by_id = {provider.id: provider for provider in current}
    providers: list[ProviderConfig] = []
    for payload in payloads:
        existing = current_by_id.get(payload.id)
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
                api_key_default=payload.api_key_default
                if payload.api_key_default is not None
                else (existing.api_key_default if existing is not None else None),
            )
        )
    return providers


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
            raise AdminConfigError(f"Unsupported tool config section: {item.name}")
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
        raise AdminConfigError(f"{payload.name} has unsupported setting keys: {unknown}")

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
        raise AdminConfigError(f"{spec.key} cannot be null.")
    if spec.value_type == "boolean":
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise AdminConfigError(f"{spec.key} must be a boolean.")
    if spec.value_type == "integer":
        return int(value)
    if spec.value_type == "float":
        return float(value)
    if spec.value_type == "string":
        text = str(value).strip()
        if spec.options and text not in spec.options:
            allowed = ", ".join(spec.options)
            raise AdminConfigError(f"{spec.key} must be one of: {allowed}.")
        return text
    raise AdminConfigError(f"{spec.key} has unsupported type {spec.value_type}.")


def _write_local_env_updates(path: Path, updates: dict[str, object | None]) -> None:
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in existing_lines:
        match = _ENV_ASSIGNMENT_RE.match(line.strip())
        if match and match.group(1) in updates:
            key = match.group(1)
            seen.add(key)
            value = updates[key]
            if value is not None:
                next_lines.append(f"{key}={_format_env_value(value)}")
            continue
        next_lines.append(line)

    missing = [(key, value) for key, value in updates.items() if key not in seen]
    if missing and next_lines and next_lines[-1].strip():
        next_lines.append("")
    if missing and not existing_lines:
        next_lines.append("# Managed by Focus Agent admin config.")
    for key, value in missing:
        if value is not None:
            next_lines.append(f"{key}={_format_env_value(value)}")

    _write_text_atomic(path, "\n".join(next_lines).rstrip() + "\n")


def _format_env_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _settings_env(settings: Any) -> dict[str, str]:
    return dict(getattr(settings, "resolved_env", {}) or {})


def _configured_env_value(
    env: dict[str, str],
    env_key: str | None,
    default_value: str | None,
) -> bool:
    return bool(default_value or (env_key and (env.get(env_key) or os.environ.get(env_key))))


def _model_catalog_path(settings: Any) -> Path:
    env = _settings_env(settings)
    return Path(
        env.get("FOCUS_AGENT_MODEL_CATALOG_DOC")
        or os.environ.get("FOCUS_AGENT_MODEL_CATALOG_DOC")
        or DEFAULT_MODEL_CATALOG_DOC
    ).expanduser()


def _tool_catalog_path(settings: Any) -> Path:
    env = _settings_env(settings)
    return Path(
        env.get("FOCUS_AGENT_TOOL_CATALOG_DOC")
        or os.environ.get("FOCUS_AGENT_TOOL_CATALOG_DOC")
        or DEFAULT_TOOL_CATALOG_DOC
    ).expanduser()


def _local_env_path(settings: Any) -> Path:
    env = _settings_env(settings)
    return Path(
        env.get("FOCUS_AGENT_LOCAL_ENV_FILE")
        or os.environ.get("FOCUS_AGENT_LOCAL_ENV_FILE")
        or DEFAULT_LOCAL_ENV_FILE
    ).expanduser()


def _source_response(path: Path) -> AdminConfigSourceResponse:
    contracts = _admin_config_contracts()
    return contracts.AdminConfigSourceResponse(
        path=str(path),
        exists=path.exists(),
        writable=_path_writable(path),
    )


def _path_writable(path: Path) -> bool:
    if path.exists():
        return os.access(path, os.W_OK)
    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    return os.access(parent, os.W_OK)


__all__ = [
    "AdminConfigError",
    "ModelCatalogValidationError",
    "read_admin_config",
    "refresh_admin_skill_config",
    "update_admin_model_config",
    "update_admin_policy_config",
    "update_admin_skill_config",
    "update_admin_tool_config",
]
