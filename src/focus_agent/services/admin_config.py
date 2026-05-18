from __future__ import annotations

import os
import re
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, NamedTuple

from focus_agent.api.contract_models.admin_config import (
    AdminConfigModelResponse,
    AdminConfigModelSectionResponse,
    AdminConfigPolicySectionResponse,
    AdminConfigProviderResponse,
    AdminConfigResponse,
    AdminConfigSourceResponse,
    AdminConfigSystemSectionResponse,
    AdminConfigToolProviderResponse,
    AdminConfigToolResponse,
    AdminConfigToolSectionResponse,
    AdminConfigValueResponse,
    AdminModelConfigPayload,
    AdminModelConfigUpdateRequest,
    AdminModelProviderConfigPayload,
    AdminPolicyConfigUpdateRequest,
    AdminToolConfigPayload,
    AdminToolConfigUpdateRequest,
    AdminToolProviderConfigPayload,
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

_ENV_ASSIGNMENT_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=\s*(.*)$")
_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key_default",
        "agent_memory_embedding_api_key",
        "auth_jwt_secret",
        "database_uri",
    }
)


class AdminConfigError(ValueError):
    """Raised when an administrator submits an invalid configuration payload."""


class ConfigFieldSpec(NamedTuple):
    key: str
    env_key: str
    label: str
    value_type: str
    description: str
    options: tuple[str, ...] = ()
    requires_restart: bool = True


_POLICY_FIELD_SPECS: tuple[ConfigFieldSpec, ...] = (
    ConfigFieldSpec(
        "multi_agent_v2_enabled",
        "MULTI_AGENT_V2_ENABLED",
        "Multi-agent v2",
        "boolean",
        "Enable the v2 multi-agent coordination surface.",
    ),
    ConfigFieldSpec(
        "multi_agent_dag_scheduler_enabled",
        "MULTI_AGENT_DAG_SCHEDULER_ENABLED",
        "DAG scheduler",
        "boolean",
        "Enable dependency-aware multi-agent task scheduling.",
    ),
    ConfigFieldSpec(
        "multi_agent_resource_lock_enabled",
        "MULTI_AGENT_RESOURCE_LOCK_ENABLED",
        "Resource locks",
        "boolean",
        "Coordinate agent write ownership through resource locks.",
    ),
    ConfigFieldSpec(
        "multi_agent_message_bus_enabled",
        "MULTI_AGENT_MESSAGE_BUS_ENABLED",
        "Message bus",
        "boolean",
        "Enable structured agent-to-agent messages.",
    ),
    ConfigFieldSpec(
        "multi_agent_async_approval_enabled",
        "MULTI_AGENT_ASYNC_APPROVAL_ENABLED",
        "Async approvals",
        "boolean",
        "Allow multi-agent approval waits to run asynchronously.",
    ),
    ConfigFieldSpec(
        "multi_agent_failure_handler_enabled",
        "MULTI_AGENT_FAILURE_HANDLER_ENABLED",
        "Failure handler",
        "boolean",
        "Enable the multi-agent failure recovery coordinator.",
    ),
    ConfigFieldSpec(
        "agent_role_routing_enabled",
        "AGENT_ROLE_ROUTING_ENABLED",
        "Role routing",
        "boolean",
        "Route planner, executor, critic, memory, and skill work by role.",
    ),
    ConfigFieldSpec(
        "agent_role_max_parallel_runs",
        "AGENT_ROLE_MAX_PARALLEL_RUNS",
        "Role max parallel runs",
        "integer",
        "Maximum parallel role-specific model calls.",
    ),
    ConfigFieldSpec(
        "agent_tool_router_enabled",
        "AGENT_TOOL_ROUTER_ENABLED",
        "Tool router",
        "boolean",
        "Enable policy-assisted routing for tool calls.",
    ),
    ConfigFieldSpec(
        "agent_tool_router_enforce",
        "AGENT_TOOL_ROUTER_ENFORCE",
        "Tool router enforce",
        "boolean",
        "Block tool calls rejected by the router instead of observing only.",
    ),
    ConfigFieldSpec(
        "agent_delegation_enabled",
        "AGENT_DELEGATION_ENABLED",
        "Delegation",
        "boolean",
        "Enable agent delegation planning.",
    ),
    ConfigFieldSpec(
        "agent_delegation_enforce",
        "AGENT_DELEGATION_ENFORCE",
        "Delegation enforce",
        "boolean",
        "Require delegation policy decisions instead of observing only.",
    ),
    ConfigFieldSpec(
        "agent_delegation_execution_mode",
        "AGENT_DELEGATION_EXECUTION_MODE",
        "Delegation mode",
        "string",
        "Execution mode used by delegation.",
        ("observe", "fake", "inline", "background"),
    ),
    ConfigFieldSpec(
        "agent_model_router_enabled",
        "AGENT_MODEL_ROUTER_ENABLED",
        "Model router",
        "boolean",
        "Enable policy-assisted model selection.",
    ),
    ConfigFieldSpec(
        "agent_model_router_mode",
        "AGENT_MODEL_ROUTER_MODE",
        "Model router mode",
        "string",
        "Observe or enforce model router decisions.",
        ("observe", "enforce"),
    ),
    ConfigFieldSpec(
        "agent_branch_decision_enabled",
        "AGENT_BRANCH_DECISION_ENABLED",
        "Branch decisions",
        "boolean",
        "Enable evidence-first branch decision recording.",
    ),
    ConfigFieldSpec(
        "agent_branch_decision_mode",
        "AGENT_BRANCH_DECISION_MODE",
        "Branch decision mode",
        "string",
        "Control branch decision behavior.",
        ("shadow", "suggest", "execute"),
    ),
    ConfigFieldSpec(
        "agent_branch_decision_min_confidence",
        "AGENT_BRANCH_DECISION_MIN_CONFIDENCE",
        "Branch min confidence",
        "float",
        "Minimum confidence for branch decisions.",
    ),
    ConfigFieldSpec(
        "agent_branch_decision_split_threshold",
        "AGENT_BRANCH_DECISION_SPLIT_THRESHOLD",
        "Split threshold",
        "float",
        "Confidence threshold for split decisions.",
    ),
    ConfigFieldSpec(
        "agent_branch_decision_conclude_threshold",
        "AGENT_BRANCH_DECISION_CONCLUDE_THRESHOLD",
        "Conclude threshold",
        "float",
        "Confidence threshold for conclude decisions.",
    ),
    ConfigFieldSpec(
        "agent_branch_decision_merge_candidate_threshold",
        "AGENT_BRANCH_DECISION_MERGE_CANDIDATE_THRESHOLD",
        "Merge candidate threshold",
        "float",
        "Confidence threshold for merge-candidate decisions.",
    ),
    ConfigFieldSpec(
        "agent_branch_decision_rate_limit_per_hour",
        "AGENT_BRANCH_DECISION_RATE_LIMIT_PER_HOUR",
        "Branch decision rate limit",
        "integer",
        "Maximum automated branch decisions per hour.",
    ),
    ConfigFieldSpec(
        "agent_branch_recommendation_enabled",
        "AGENT_BRANCH_RECOMMENDATION_ENABLED",
        "Branch recommendations",
        "boolean",
        "Enable pre-turn branch recommendations.",
    ),
    ConfigFieldSpec(
        "agent_branch_recommendation_mode",
        "AGENT_BRANCH_RECOMMENDATION_MODE",
        "Branch recommendation mode",
        "string",
        "Control recommendation behavior: shadow records diagnostics only; suggest may create pending cards.",
        ("shadow", "suggest"),
    ),
    ConfigFieldSpec(
        "agent_branch_recommendation_min_confidence",
        "AGENT_BRANCH_RECOMMENDATION_MIN_CONFIDENCE",
        "Recommendation min confidence",
        "float",
        "Minimum confidence for branch recommendations.",
    ),
    ConfigFieldSpec(
        "agent_context_engineering_v2_enabled",
        "AGENT_CONTEXT_ENGINEERING_V2_ENABLED",
        "Context engineering v2",
        "boolean",
        "Enable the v2 context assembly policy surface.",
    ),
    ConfigFieldSpec(
        "agent_context_artifactize_long_observations",
        "AGENT_CONTEXT_ARTIFACTIZE_LONG_OBSERVATIONS",
        "Artifactize long observations",
        "boolean",
        "Move long tool observations into artifacts when assembling context.",
    ),
    ConfigFieldSpec(
        "agent_context_role_views_enabled",
        "AGENT_CONTEXT_ROLE_VIEWS_ENABLED",
        "Context role views",
        "boolean",
        "Assemble role-specific context views.",
    ),
    ConfigFieldSpec(
        "agent_context_tokenizer_mode",
        "AGENT_CONTEXT_TOKENIZER_MODE",
        "Context tokenizer mode",
        "string",
        "Tokenizer strategy for context budgeting.",
        ("tokenizer_first", "chars_fallback"),
    ),
    ConfigFieldSpec(
        "agent_context_artifact_min_chars",
        "AGENT_CONTEXT_ARTIFACT_MIN_CHARS",
        "Artifact min chars",
        "integer",
        "Minimum observation size before artifactization can apply.",
    ),
    ConfigFieldSpec(
        "context_auto_compaction_enabled",
        "CONTEXT_AUTO_COMPACTION_ENABLED",
        "Auto compaction",
        "boolean",
        "Automatically compact context near budget limits.",
    ),
    ConfigFieldSpec(
        "context_auto_compaction_pre_send_ratio",
        "CONTEXT_AUTO_COMPACTION_PRE_SEND_RATIO",
        "Pre-send compaction ratio",
        "float",
        "Context usage ratio that triggers compaction before model calls.",
    ),
    ConfigFieldSpec(
        "context_auto_compaction_post_turn_ratio",
        "CONTEXT_AUTO_COMPACTION_POST_TURN_RATIO",
        "Post-turn compaction ratio",
        "float",
        "Context usage ratio that triggers compaction after a turn.",
    ),
    ConfigFieldSpec(
        "agent_memory_curator_enabled",
        "AGENT_MEMORY_CURATOR_ENABLED",
        "Memory curator",
        "boolean",
        "Enable the memory curator policy.",
    ),
    ConfigFieldSpec(
        "agent_memory_auto_promote_on_merge",
        "AGENT_MEMORY_AUTO_PROMOTE_ON_MERGE",
        "Memory auto promote",
        "boolean",
        "Promote memory candidates after accepted merges.",
    ),
    ConfigFieldSpec(
        "agent_task_ledger_enabled",
        "AGENT_TASK_LEDGER_ENABLED",
        "Task ledger",
        "boolean",
        "Enable task ledger planning and run tracking.",
    ),
    ConfigFieldSpec(
        "agent_artifact_synthesis_enabled",
        "AGENT_ARTIFACT_SYNTHESIS_ENABLED",
        "Artifact synthesis",
        "boolean",
        "Enable artifact synthesis from agent-team work.",
    ),
    ConfigFieldSpec(
        "agent_critic_gate_enabled",
        "AGENT_CRITIC_GATE_ENABLED",
        "Critic gate",
        "boolean",
        "Enable critic gate evaluation.",
    ),
    ConfigFieldSpec(
        "agent_critic_gate_enforce",
        "AGENT_CRITIC_GATE_ENFORCE",
        "Critic gate enforce",
        "boolean",
        "Require critic gate approval before finalization.",
    ),
)

_SYSTEM_FIELD_SPECS: tuple[ConfigFieldSpec, ...] = (
    ConfigFieldSpec(
        "temperature",
        "TEMPERATURE",
        "Temperature",
        "float",
        "Default chat model temperature.",
        requires_restart=False,
    ),
    ConfigFieldSpec(
        "rate_limit_enabled",
        "RATE_LIMIT_ENABLED",
        "Rate limiting",
        "boolean",
        "Enable API request rate limits.",
    ),
    ConfigFieldSpec(
        "rate_limit_per_minute",
        "RATE_LIMIT_PER_MINUTE",
        "API rate limit",
        "integer",
        "Default API request limit per minute.",
    ),
    ConfigFieldSpec(
        "rate_limit_chat_per_minute",
        "RATE_LIMIT_CHAT_PER_MINUTE",
        "Chat rate limit",
        "integer",
        "Chat request limit per minute.",
    ),
    ConfigFieldSpec(
        "sse_heartbeat_seconds",
        "SSE_HEARTBEAT_SECONDS",
        "SSE heartbeat",
        "float",
        "Server-sent event heartbeat interval.",
    ),
    ConfigFieldSpec(
        "metrics_cache_ttl_seconds",
        "METRICS_CACHE_TTL_SECONDS",
        "Metrics cache TTL",
        "integer",
        "Seconds before metrics cache entries expire.",
    ),
    ConfigFieldSpec(
        "trajectory_enabled",
        "TRAJECTORY_ENABLED",
        "Trajectory capture",
        "boolean",
        "Enable trajectory recording when storage is available.",
    ),
    ConfigFieldSpec(
        "api_host",
        "API_HOST",
        "API host",
        "string",
        "API bind host. Restart is required.",
    ),
    ConfigFieldSpec(
        "api_port",
        "API_PORT",
        "API port",
        "integer",
        "API bind port. Restart is required.",
    ),
    ConfigFieldSpec(
        "database_uri",
        "DATABASE_URI",
        "Database URI",
        "string",
        "Database connection string. The value is never returned.",
    ),
    ConfigFieldSpec(
        "auth_jwt_secret",
        "AUTH_JWT_SECRET",
        "JWT secret",
        "string",
        "JWT signing secret. The value is never returned.",
    ),
)


def read_admin_config(
    runtime: AppRuntime,
    *,
    message: str | None = None,
    updated_by: str | None = None,
) -> AdminConfigResponse:
    settings = runtime.settings
    return AdminConfigResponse(
        models=_build_model_section(settings),
        tools=_build_tool_section(settings),
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
    return AdminConfigModelSectionResponse(
        source=source,
        default_model=getattr(settings, "model", None) or catalog.default_model,
        helper_model=getattr(settings, "helper_model", None) or catalog.helper_model,
        model_choices=list(getattr(settings, "model_choices", ()) or catalog.model_choices),
        providers=[
            AdminConfigProviderResponse(
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
            AdminConfigModelResponse(
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
    return AdminConfigToolSectionResponse(
        source=_source_response(_tool_catalog_path(settings)),
        tools=[
            _tool_response(name, getattr(catalog, name), catalog.metadata_overlay_for(name))
            for name in catalog.section_names
            if hasattr(catalog, name)
        ],
        providers=[
            AdminConfigToolProviderResponse(
                id=provider.id,
                enabled=provider.enabled,
                order=provider.order,
                metadata=dict(provider.metadata),
                overrides=list(provider.overrides),
            )
            for provider in catalog.providers
        ],
    )


def _build_policy_section(settings: Any) -> AdminConfigPolicySectionResponse:
    return AdminConfigPolicySectionResponse(
        source=_source_response(_local_env_path(settings)),
        items=[_value_response(settings, spec, editable=True) for spec in _POLICY_FIELD_SPECS],
    )


def _build_system_section(settings: Any) -> AdminConfigSystemSectionResponse:
    return AdminConfigSystemSectionResponse(
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
    return AdminConfigValueResponse(
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
    return AdminConfigToolResponse(
        name=name,
        label=label,
        description=description,
        enabled=enabled,
        settings=settings,
        metadata=dict(metadata),
    )


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

    providers = [
        AdminToolProviderConfigPayload(
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
    return AdminToolConfigPayload(
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
    return AdminToolConfigPayload(
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
    return AdminConfigSourceResponse(
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
    "update_admin_model_config",
    "update_admin_policy_config",
    "update_admin_tool_config",
]
