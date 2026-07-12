from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from focus_agent.api.contract_models.admin_config import (
        AdminConfigModelSectionResponse,
        AdminConfigPolicySectionResponse,
        AdminConfigResponse,
        AdminConfigSkillResponse,
        AdminConfigSkillSectionResponse,
        AdminConfigSystemSectionResponse,
        AdminConfigToolResponse,
        AdminConfigToolSectionResponse,
        AdminConfigValueResponse,
        AdminModelConfigUpdateRequest,
        AdminPolicyConfigUpdateRequest,
        AdminSkillConfigUpdateRequest,
        AdminToolConfigUpdateRequest,
    )

from focus_agent.capabilities.tool_registry import build_tool_registry as build_tool_registry
from focus_agent.config import (
    ModelCatalogConfig,
    ModelCatalogValidationError,
    ToolCatalogConfig,
    load_model_catalog_toml,
    load_tool_catalog_document,
)
from focus_agent.engine.runtime import AppRuntime
from focus_agent.skills.registry import SkillRegistry
from focus_agent.skills.registry_paths import _normalize_skill_id

from . import admin_config_io as _admin_config_io
from . import admin_config_rendering as _admin_config_rendering
from . import admin_config_runtime as _admin_config_runtime
from .admin_config_fields import (
    _POLICY_FIELD_SPECS,
    _SENSITIVE_FIELD_NAMES,
    _SYSTEM_FIELD_SPECS,
    ConfigFieldSpec,
)

_configured_env_value = _admin_config_io._configured_env_value
_format_env_value = _admin_config_io._format_env_value
_local_env_path = _admin_config_io._local_env_path
_model_catalog_path = _admin_config_io._model_catalog_path
_path_writable = _admin_config_io._path_writable
_settings_env = _admin_config_io._settings_env
_source_response = _admin_config_io._source_response
_tool_catalog_path = _admin_config_io._tool_catalog_path
_write_local_env_updates = _admin_config_io._write_local_env_updates
_write_text_atomic = _admin_config_io._write_text_atomic

_append_toml_key = _admin_config_rendering._append_toml_key
_coerce_config_value = _admin_config_rendering._coerce_config_value
_dataclass_values = _admin_config_rendering._dataclass_values
_field_or_existing = _admin_config_rendering._field_or_existing
_merge_tool_payload = _admin_config_rendering._merge_tool_payload
_model_payloads = _admin_config_rendering._model_payloads
_provider_api_key_default = _admin_config_rendering._provider_api_key_default
_provider_payloads = _admin_config_rendering._provider_payloads
_render_model_catalog_toml = _admin_config_rendering._render_model_catalog_toml
_render_tool_catalog_toml = _admin_config_rendering._render_tool_catalog_toml
_toml_bare_or_quoted_key = _admin_config_rendering._toml_bare_or_quoted_key
_toml_value = _admin_config_rendering._toml_value
_tool_payload_from_current = _admin_config_rendering._tool_payload_from_current

_refresh_runtime_skill_registry = _admin_config_runtime._refresh_runtime_skill_registry
_reload_runtime_graph = _admin_config_runtime._reload_runtime_graph
_reload_runtime_skill_registry = _admin_config_runtime._reload_runtime_skill_registry
_reload_runtime_tool_registry = _admin_config_runtime._reload_runtime_tool_registry
_sync_runtime_graph_dependents = _admin_config_runtime._sync_runtime_graph_dependents

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
        settings.skill_directories = _coerce_skill_path_tuple(
            settings,
            payload.skill_directories,
            field_name="skill_directories",
            allow_empty=False,
        )
        updates[_SKILL_DIRECTORIES_ENV] = _csv_env_value(settings.skill_directories)
    if payload.install_directory is not None:
        install_directory = _validate_skill_path(
            settings,
            payload.install_directory,
            field_name="install_directory",
        )
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

    if payload.refresh and not updates:
        refresh_result = _refresh_runtime_skill_registry(runtime)
    else:
        refresh_result = _reload_runtime_skill_registry(runtime)
    _reload_runtime_tool_registry(runtime)
    _reload_runtime_graph(runtime)

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
    _reload_runtime_tool_registry(runtime)
    _reload_runtime_graph(runtime)
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
        aliases=list(getattr(skill, "aliases", ()) or ()),
        localized_triggers=list(getattr(skill, "localized_triggers", ()) or ()),
        domains=list(getattr(skill, "domains", ()) or ()),
        intents=list(getattr(skill, "intents", ()) or ()),
        when_to_use=list(getattr(skill, "when_to_use", ()) or ()),
        primary_tools=list(getattr(skill, "primary_tools", ()) or ()),
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
    registries = [
        _skill_registry_for_response(runtime),
        SkillRegistry.from_settings(runtime.settings),
    ]
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


def _coerce_skill_path_tuple(
    settings: Any,
    values: list[str],
    *,
    field_name: str,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    items = [
        _validate_skill_path(settings, value, field_name=field_name)
        for value in values
        if str(value or "").strip()
    ]
    if not allow_empty and not items:
        raise AdminConfigError(f"{field_name} cannot be empty.")
    return tuple(dict.fromkeys(items))


def _validate_skill_path(settings: Any, value: str, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AdminConfigError(f"{field_name} cannot be empty.")
    path = Path(text).expanduser()
    if not path.is_absolute() and any(part == ".." for part in path.parts):
        raise AdminConfigError(f"{field_name} must stay inside the workspace.")
    workspace_root = Path(getattr(settings, "workspace_root", ".") or ".").expanduser().resolve()
    resolved = path.resolve() if path.is_absolute() else (workspace_root / path).resolve()
    if resolved == workspace_root or workspace_root not in resolved.parents:
        raise AdminConfigError(f"{field_name} must stay inside the workspace.")
    return text


def _csv_env_value(values: tuple[str, ...]) -> str:
    return ",".join(values)


def _skill_update_message(changed: bool, refresh_result: dict[str, Any]) -> str:
    count = int(refresh_result.get("count") or 0)
    if changed:
        return f"Skill configuration saved. {count} skills available."
    return f"Skill index refreshed. {count} skills available."


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
