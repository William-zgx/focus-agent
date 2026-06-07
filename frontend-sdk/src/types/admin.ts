import type { FocusAgentUser, FocusAgentUserStatus } from "./auth.js";

export interface FocusAgentUserListRequest {
  status?: string | string[] | null;
  role?: string | string[] | null;
  tenant_id?: string | null;
  query?: string | null;
  limit?: number;
  offset?: number;
}

export interface FocusAgentUserListResponse {
  items: FocusAgentUser[];
  count: number;
  limit: number;
  offset: number;
}

export interface FocusAgentUserSessionListRequest {
  include_revoked?: boolean;
}

export interface FocusAgentCreateUserRequest {
  user_id: string;
  username?: string | null;
  display_name?: string | null;
  email?: string | null;
  tenant_id?: string | null;
  status?: FocusAgentUserStatus | string | null;
  roles?: string[];
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentUpdateUserRequest {
  username?: string | null;
  display_name?: string | null;
  email?: string | null;
  tenant_id?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentUpdateUserStatusRequest {
  status: FocusAgentUserStatus | string;
  reason?: string | null;
}

export interface FocusAgentUpdateUserRolesRequest {
  roles: string[];
  reason?: string | null;
}

export interface FocusAgentAuditEvent {
  event_id: string;
  actor_user_id?: string | null;
  tenant_id?: string | null;
  action: string;
  resource_type: string;
  resource_id?: string | null;
  decision: string;
  reason?: string | null;
  metadata: Record<string, unknown>;
  request_id?: string | null;
  created_at?: string | null;
}

export interface FocusAgentAuditEventListRequest {
  actor_user_id?: string | null;
  resource_type?: string | null;
  resource_id?: string | null;
  decision?: string | null;
  limit?: number;
  offset?: number;
}

export interface FocusAgentAuditEventListResponse {
  items: FocusAgentAuditEvent[];
  count: number;
  limit: number;
  offset: number;
}

export interface FocusAgentAdminConfigSource {
  path: string;
  exists: boolean;
  writable: boolean;
}

export interface FocusAgentAdminConfigValue {
  key: string;
  env_key?: string | null;
  label: string;
  value?: unknown;
  value_type: string;
  source: string;
  editable: boolean;
  sensitive: boolean;
  configured?: boolean | null;
  requires_restart: boolean;
  description?: string | null;
  options: string[];
}

export interface FocusAgentAdminConfigProvider {
  id: string;
  label?: string | null;
  backend_provider?: string | null;
  aliases: string[];
  logo_slug?: string | null;
  logo_letter?: string | null;
  base_url_env?: string | null;
  base_url_default?: string | null;
  base_url_configured: boolean;
  api_key_env?: string | null;
  api_key_configured: boolean;
}

export interface FocusAgentAdminModelConfigEntry {
  id: string;
  label?: string | null;
  supports_thinking?: boolean | null;
  default_thinking_enabled?: boolean | null;
  request_kwargs: Record<string, unknown>;
  thinking_enabled_request_kwargs: Record<string, unknown>;
  thinking_disabled_request_kwargs: Record<string, unknown>;
  thinking_disabled_model_name?: string | null;
  reasoning_effort?: string | null;
  no_temperature?: boolean | null;
  thinking_enable_extra_body_type?: string | null;
  thinking_disable_extra_body_type?: string | null;
  thinking_disable_switch_model?: string | null;
}

export interface FocusAgentAdminModelConfig {
  source: FocusAgentAdminConfigSource;
  default_model: string | null;
  helper_model?: string | null;
  model_choices: string[];
  providers: FocusAgentAdminConfigProvider[];
  models: FocusAgentAdminModelConfigEntry[];
  requires_restart: boolean;
}

export interface FocusAgentAdminToolConfigEntry {
  name: string;
  label: string;
  description: string;
  enabled: boolean;
  settings: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface FocusAgentAdminToolProviderConfig {
  id: string;
  enabled: boolean;
  order?: number | null;
  metadata: Record<string, unknown>;
  overrides: string[];
}

export interface FocusAgentAdminToolConfig {
  source: FocusAgentAdminConfigSource;
  tools: FocusAgentAdminToolConfigEntry[];
  providers: FocusAgentAdminToolProviderConfig[];
  requires_restart: boolean;
}

export interface FocusAgentAdminSkillConfigEntry {
  skill_id: string;
  description: string;
  enabled: boolean;
  triggers: string[];
  aliases: string[];
  localized_triggers: string[];
  domains: string[];
  intents: string[];
  when_to_use: string[];
  primary_tools: string[];
  recommended_tools: string[];
  prompt_mode?: string | null;
  path: string;
  source_id: string;
  source_type: string;
  version?: string | null;
  trust_level: string;
  install_state: string;
  provenance?: string | null;
  checksum?: string | null;
  capability_requirements: string[];
}

export interface FocusAgentAdminSkillSourceConfig {
  source_id: string;
  source_type: string;
  label: string;
  enabled: boolean;
  trusted: boolean;
  location?: string | null;
  metadata: Record<string, unknown>;
}

export interface FocusAgentAdminSkillRefreshConfig {
  available: boolean;
  refreshed: boolean;
  previous_count?: number | null;
  count: number;
}

export interface FocusAgentAdminSkillConfig {
  source: FocusAgentAdminConfigSource;
  enabled: boolean;
  install_directory: FocusAgentAdminConfigSource;
  skill_directories: FocusAgentAdminConfigSource[];
  disabled_skill_ids: string[];
  sources_enabled: string[];
  source_locations: string[];
  trusted_sources: string[];
  sources: FocusAgentAdminSkillSourceConfig[];
  catalog: FocusAgentAdminSkillConfigEntry[];
  semantic_match_enabled: boolean;
  semantic_match_threshold: number;
  refresh: FocusAgentAdminSkillRefreshConfig;
  requires_restart: boolean;
}

export interface FocusAgentAdminPolicyConfig {
  source: FocusAgentAdminConfigSource;
  items: FocusAgentAdminConfigValue[];
  requires_restart: boolean;
}

export interface FocusAgentAdminSystemConfig {
  source: FocusAgentAdminConfigSource;
  items: FocusAgentAdminConfigValue[];
}

export interface FocusAgentAdminConfig {
  models: FocusAgentAdminModelConfig;
  tools: FocusAgentAdminToolConfig;
  skills: FocusAgentAdminSkillConfig;
  policies: FocusAgentAdminPolicyConfig;
  system: FocusAgentAdminSystemConfig;
  updated_at?: string | null;
  updated_by?: string | null;
  message?: string | null;
}

export interface FocusAgentUpdateAdminModelProviderConfig {
  id: string;
  label?: string | null;
  backend_provider?: string | null;
  aliases?: string[];
  logo_slug?: string | null;
  logo_letter?: string | null;
  base_url_env?: string | null;
  base_url_default?: string | null;
  api_key_env?: string | null;
  api_key_default?: string | null;
}

export interface FocusAgentUpdateAdminModelConfigEntry {
  id: string;
  label?: string | null;
  supports_thinking?: boolean | null;
  default_thinking_enabled?: boolean | null;
  request_kwargs?: Record<string, unknown>;
  thinking_enabled_request_kwargs?: Record<string, unknown>;
  thinking_disabled_request_kwargs?: Record<string, unknown>;
  thinking_disabled_model_name?: string | null;
  reasoning_effort?: string | null;
  no_temperature?: boolean | null;
  thinking_enable_extra_body_type?: string | null;
  thinking_disable_extra_body_type?: string | null;
  thinking_disable_switch_model?: string | null;
}

export interface FocusAgentUpdateAdminModelConfigRequest {
  reason?: string | null;
  default_model?: string | null;
  helper_model?: string | null;
  model_choices?: string[];
  providers?: FocusAgentUpdateAdminModelProviderConfig[];
  models?: FocusAgentUpdateAdminModelConfigEntry[];
}

export interface FocusAgentUpdateAdminToolConfigEntry {
  name: string;
  enabled?: boolean | null;
  label?: string | null;
  description?: string | null;
  settings?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface FocusAgentUpdateAdminToolProviderConfig {
  id: string;
  enabled?: boolean;
  order?: number | null;
  metadata?: Record<string, unknown>;
  overrides?: string[];
}

export interface FocusAgentUpdateAdminToolConfigRequest {
  reason?: string | null;
  tools?: FocusAgentUpdateAdminToolConfigEntry[];
  providers?: FocusAgentUpdateAdminToolProviderConfig[];
}

export interface FocusAgentUpdateAdminSkillConfigEntry {
  skill_id: string;
  enabled: boolean;
}

export interface FocusAgentUpdateAdminSkillConfigRequest {
  reason?: string | null;
  enabled?: boolean | null;
  skills?: FocusAgentUpdateAdminSkillConfigEntry[];
  disabled_skill_ids?: string[];
  skill_directories?: string[];
  install_directory?: string | null;
  sources_enabled?: string[];
  source_locations?: string[];
  trusted_sources?: string[];
  semantic_match_enabled?: boolean | null;
  semantic_match_threshold?: number | null;
  refresh?: boolean;
}

export interface FocusAgentUpdateAdminPolicyConfigRequest {
  reason?: string | null;
  values: Record<string, unknown>;
}
