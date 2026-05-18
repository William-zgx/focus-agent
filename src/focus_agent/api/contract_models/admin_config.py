from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AdminConfigSourceResponse(BaseModel):
    path: str
    exists: bool = False
    writable: bool = True


class AdminConfigValueResponse(BaseModel):
    key: str
    env_key: str | None = None
    label: str
    value: Any = None
    value_type: str = "string"
    source: str = "runtime"
    editable: bool = True
    sensitive: bool = False
    configured: bool | None = None
    requires_restart: bool = False
    description: str | None = None
    options: list[str] = Field(default_factory=list)


class AdminConfigProviderResponse(BaseModel):
    id: str
    label: str | None = None
    backend_provider: str | None = None
    aliases: list[str] = Field(default_factory=list)
    logo_slug: str | None = None
    logo_letter: str | None = None
    base_url_env: str | None = None
    base_url_default: str | None = None
    base_url_configured: bool = False
    api_key_env: str | None = None
    api_key_configured: bool = False


class AdminConfigModelResponse(BaseModel):
    id: str
    label: str | None = None
    supports_thinking: bool | None = None
    default_thinking_enabled: bool | None = None
    request_kwargs: dict[str, Any] = Field(default_factory=dict)
    thinking_enabled_request_kwargs: dict[str, Any] = Field(default_factory=dict)
    thinking_disabled_request_kwargs: dict[str, Any] = Field(default_factory=dict)
    thinking_disabled_model_name: str | None = None
    reasoning_effort: str | None = None
    no_temperature: bool | None = None
    thinking_enable_extra_body_type: str | None = None
    thinking_disable_extra_body_type: str | None = None
    thinking_disable_switch_model: str | None = None


class AdminConfigToolResponse(BaseModel):
    name: str
    label: str
    description: str
    enabled: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdminConfigToolProviderResponse(BaseModel):
    id: str
    enabled: bool = True
    order: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    overrides: list[str] = Field(default_factory=list)


class AdminConfigModelSectionResponse(BaseModel):
    source: AdminConfigSourceResponse
    default_model: str | None = None
    helper_model: str | None = None
    model_choices: list[str] = Field(default_factory=list)
    providers: list[AdminConfigProviderResponse] = Field(default_factory=list)
    models: list[AdminConfigModelResponse] = Field(default_factory=list)
    requires_restart: bool = False


class AdminConfigToolSectionResponse(BaseModel):
    source: AdminConfigSourceResponse
    tools: list[AdminConfigToolResponse] = Field(default_factory=list)
    providers: list[AdminConfigToolProviderResponse] = Field(default_factory=list)
    requires_restart: bool = True


class AdminConfigPolicySectionResponse(BaseModel):
    source: AdminConfigSourceResponse
    items: list[AdminConfigValueResponse] = Field(default_factory=list)
    requires_restart: bool = True


class AdminConfigSystemSectionResponse(BaseModel):
    source: AdminConfigSourceResponse
    items: list[AdminConfigValueResponse] = Field(default_factory=list)


class AdminConfigResponse(BaseModel):
    models: AdminConfigModelSectionResponse
    tools: AdminConfigToolSectionResponse
    policies: AdminConfigPolicySectionResponse
    system: AdminConfigSystemSectionResponse
    updated_at: str | None = None
    updated_by: str | None = None
    message: str | None = None


class AdminModelProviderConfigPayload(BaseModel):
    id: str
    label: str | None = None
    backend_provider: str | None = None
    aliases: list[str] = Field(default_factory=list)
    logo_slug: str | None = None
    logo_letter: str | None = None
    base_url_env: str | None = None
    base_url_default: str | None = None
    api_key_env: str | None = None
    api_key_default: str | None = None


class AdminModelConfigPayload(BaseModel):
    id: str
    label: str | None = None
    supports_thinking: bool | None = None
    default_thinking_enabled: bool | None = None
    request_kwargs: dict[str, Any] = Field(default_factory=dict)
    thinking_enabled_request_kwargs: dict[str, Any] = Field(default_factory=dict)
    thinking_disabled_request_kwargs: dict[str, Any] = Field(default_factory=dict)
    thinking_disabled_model_name: str | None = None
    reasoning_effort: str | None = None
    no_temperature: bool | None = None
    thinking_enable_extra_body_type: str | None = None
    thinking_disable_extra_body_type: str | None = None
    thinking_disable_switch_model: str | None = None


class AdminModelConfigUpdateRequest(BaseModel):
    reason: str | None = None
    default_model: str | None = None
    helper_model: str | None = None
    model_choices: list[str] | None = None
    providers: list[AdminModelProviderConfigPayload] | None = None
    models: list[AdminModelConfigPayload] | None = None


class AdminToolConfigPayload(BaseModel):
    name: str
    enabled: bool | None = None
    label: str | None = None
    description: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AdminToolProviderConfigPayload(BaseModel):
    id: str
    enabled: bool = True
    order: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    overrides: list[str] = Field(default_factory=list)


class AdminToolConfigUpdateRequest(BaseModel):
    reason: str | None = None
    tools: list[AdminToolConfigPayload] | None = None
    providers: list[AdminToolProviderConfigPayload] | None = None


class AdminPolicyConfigUpdateRequest(BaseModel):
    reason: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AdminConfigModelResponse",
    "AdminConfigModelSectionResponse",
    "AdminConfigProviderResponse",
    "AdminConfigResponse",
    "AdminConfigSourceResponse",
    "AdminConfigSystemSectionResponse",
    "AdminConfigToolProviderResponse",
    "AdminConfigToolResponse",
    "AdminConfigToolSectionResponse",
    "AdminConfigValueResponse",
    "AdminModelConfigPayload",
    "AdminModelConfigUpdateRequest",
    "AdminModelProviderConfigPayload",
    "AdminPolicyConfigUpdateRequest",
    "AdminToolConfigPayload",
    "AdminToolConfigUpdateRequest",
    "AdminToolProviderConfigPayload",
]
