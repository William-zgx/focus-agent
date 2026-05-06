from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

from .config_parts.auth import (
    DEFAULT_AUTH_JWT_SECRET,
    AuthJwtKey,
    _validate_non_development_security,
)
from .config_parts.auth_settings import load_auth_config
from .config_parts.catalogs import (
    DEFAULT_MODEL_CATALOG_DOC,
    DEFAULT_TOOL_CATALOG_DOC,
    ProviderConfig,
    ConfiguredModel,
    WebSearchConfig,
    CurrentUtcTimeToolConfig,
    WriteTextArtifactToolConfig,
    ArtifactListToolConfig,
    ArtifactReadToolConfig,
    ArtifactUpdateToolConfig,
    ListFilesToolConfig,
    ReadFileToolConfig,
    SearchCodeToolConfig,
    CodebaseStatsToolConfig,
    GitStatusToolConfig,
    GitDiffToolConfig,
    GitLogToolConfig,
    WebFetchToolConfig,
    MemorySaveToolConfig,
    MemorySearchToolConfig,
    MemoryForgetToolConfig,
    ConversationSummaryToolConfig,
    SkillsListToolConfig,
    SkillViewToolConfig,
    ModelCatalogValidationError,
    ModelCatalogConfig,
    ToolCatalogConfig,
    ToolCatalogSectionSpec,
    load_model_catalog_document,
    load_model_catalog_toml,
    load_tool_catalog_document,
)
from .config_parts.common import (
    DEFAULT_LOCAL_ENV_FILE,
    load_local_env_file,
)
from .config_parts.agent import load_agent_config
from .config_parts.context import load_context_config
from .config_parts.observability import load_observability_config
from .config_parts.runtime import load_runtime_config
from .config_parts.server import load_server_config
from .config_parts.trajectory import load_trajectory_config


def ensure_runtime_directories(settings: "Settings") -> None:
    """Create directories required by runtime persistence and artifacts."""
    Path(settings.branch_db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    Path(settings.artifact_dir).expanduser().mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class Settings:
    model: str = "openai:gpt-4.1-mini"
    helper_model: str | None = None
    model_choices: tuple[str, ...] = ()
    model_catalog: ModelCatalogConfig = field(default_factory=ModelCatalogConfig)
    tool_catalog: ToolCatalogConfig = field(default_factory=ToolCatalogConfig)
    web_search: WebSearchConfig = field(default_factory=WebSearchConfig)
    resolved_env: dict[str, str] = field(default_factory=dict, repr=False)
    temperature: float = 0.0
    database_uri: str | None = None
    langgraph_api_url: str | None = None
    langsmith_project: str = "focus-agent"
    branch_db_path: str = ".focus_agent/branches.sqlite3"
    artifact_dir: str = ".focus_agent/artifacts"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_reload: bool = False
    app_version: str = "1.0.0"
    app_environment: str = "development"
    deployment_name: str | None = None
    tracing_enabled: bool = False
    tracing_service_name: str = "focus-agent"
    otel_traces_exporters: tuple[str, ...] = ()
    otel_exporter_otlp_endpoint: str | None = None
    otel_exporter_otlp_traces_endpoint: str | None = None
    otel_exporter_otlp_headers: str | None = None
    otel_exporter_otlp_protocol: str = "http/protobuf"
    otel_exporter_otlp_timeout_ms: int = 10000
    otel_tracer_provider: object | None = field(default=None, repr=False)
    web_app_dist_dir: str | None = None
    web_app_dev_server_url: str | None = None
    auth_enabled: bool = True
    auth_demo_tokens_enabled: bool = True
    auth_jwt_secret: str = DEFAULT_AUTH_JWT_SECRET
    auth_jwt_key_id: str | None = None
    auth_jwt_keys: tuple[AuthJwtKey, ...] = ()
    auth_jwt_issuer: str = "focus-agent"
    auth_jwt_audience: str | None = None
    auth_access_token_ttl_seconds: int = 8 * 60 * 60
    auth_bootstrap_admin_user_ids: tuple[str, ...] = ()
    auth_access_cookie_name: str = "focus_agent_access"
    auth_refresh_cookie_name: str = "focus_agent_refresh"
    auth_refresh_token_ttl_seconds: int = 7 * 24 * 60 * 60
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    sse_heartbeat_seconds: float = 1.5
    cors_allowed_origins: tuple[str, ...] = ()
    cors_allow_credentials: bool = True
    rate_limit_enabled: bool = False
    rate_limit_per_minute: int = 60
    rate_limit_chat_per_minute: int = 20
    metrics_trajectory_window_hours: int = 24
    metrics_cache_ttl_seconds: int = 15
    metrics_governance_recent_limit: int = 1000
    tool_max_parallel_workers: int = 4
    background_worker_max_concurrency: int = 2
    background_queue_max_size: int = 1000
    background_job_backend: str = "memory"
    background_job_execution: str = "best_effort"
    background_job_claim_ttl_seconds: float = 300.0
    runtime_thread_lock_ttl_seconds: float = 300.0
    runtime_thread_lock_heartbeat_seconds: float = 30.0
    local_checkpoint_path: str | None = None
    local_store_path: str | None = None
    branch_max_depth: int = 5
    skill_directories: tuple[str, ...] = (".focus_agent/skills",)
    workspace_root: str = "."
    plan_act_reflect_enabled: bool = True
    plan_scenes: tuple[str, ...] = ("long_dialog_research", "technical_deep_dive")
    plan_task_brief_min_chars: int = 120
    plan_max_replans: int = 1
    agent_role_routing_enabled: bool = False
    agent_role_orchestrator_model: str | None = None
    agent_role_planner_model: str | None = None
    agent_role_executor_model: str | None = None
    agent_role_critic_model: str | None = None
    agent_role_memory_model: str | None = None
    agent_role_skill_model: str | None = None
    agent_role_max_parallel_runs: int = 2
    agent_memory_curator_enabled: bool = False
    agent_memory_auto_promote_on_merge: bool = True
    agent_tool_router_enabled: bool = False
    agent_tool_router_enforce: bool = True
    agent_delegation_enabled: bool = False
    agent_delegation_enforce: bool = False
    agent_delegation_execution_mode: str = "observe"
    agent_model_router_enabled: bool = False
    agent_model_router_mode: str = "observe"
    agent_self_repair_enabled: bool = False
    agent_review_queue_enabled: bool = False
    agent_context_engineering_v2_enabled: bool = False
    agent_context_artifactize_long_observations: bool = False
    agent_context_role_views_enabled: bool = False
    agent_context_tokenizer_mode: str = "chars_fallback"
    agent_context_artifact_min_chars: int = 12000
    context_auto_compaction_enabled: bool = True
    context_auto_compaction_pre_send_ratio: float = 0.92
    context_auto_compaction_post_turn_ratio: float = 0.85
    agent_task_ledger_enabled: bool = False
    agent_artifact_synthesis_enabled: bool = False
    agent_critic_gate_enabled: bool = False
    agent_critic_gate_enforce: bool = False
    trajectory_enabled: bool | None = None
    trajectory_observation_max_chars: int = 4000
    trajectory_answer_max_chars: int = 4000
    trajectory_hash_user_id: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        process_env = dict(os.environ)
        local_overrides = load_local_env_file(
            process_env.get("FOCUS_AGENT_LOCAL_ENV_FILE"),
            environ={},
        )
        env = {**local_overrides, **process_env}
        model_catalog = load_model_catalog_document(
            env.get("FOCUS_AGENT_MODEL_CATALOG_DOC"),
            environ=env,
        )
        tool_catalog = load_tool_catalog_document(
            env.get("FOCUS_AGENT_TOOL_CATALOG_DOC"),
            environ=env,
        )
        defaults = cls()
        values = load_runtime_config(
            env,
            defaults,
            model_catalog=model_catalog,
            tool_catalog=tool_catalog,
        )
        values.update(load_observability_config(env, defaults))
        values.update(load_server_config(env, defaults))
        values.update(load_auth_config(env, defaults))
        values.update(load_agent_config(env, defaults))
        values.update(load_context_config(env, defaults))
        values.update(
            load_trajectory_config(
                env,
                defaults,
                database_uri=values["database_uri"],
            )
        )
        instance = cls(**values)
        _validate_non_development_security(instance, env)
        return instance


__all__ = [
    "DEFAULT_LOCAL_ENV_FILE",
    "DEFAULT_AUTH_JWT_SECRET",
    "DEFAULT_MODEL_CATALOG_DOC",
    "DEFAULT_TOOL_CATALOG_DOC",
    "ProviderConfig",
    "ConfiguredModel",
    "WebSearchConfig",
    "CurrentUtcTimeToolConfig",
    "WriteTextArtifactToolConfig",
    "ArtifactListToolConfig",
    "ArtifactReadToolConfig",
    "ArtifactUpdateToolConfig",
    "ListFilesToolConfig",
    "ReadFileToolConfig",
    "SearchCodeToolConfig",
    "CodebaseStatsToolConfig",
    "GitStatusToolConfig",
    "GitDiffToolConfig",
    "GitLogToolConfig",
    "WebFetchToolConfig",
    "MemorySaveToolConfig",
    "MemorySearchToolConfig",
    "MemoryForgetToolConfig",
    "ConversationSummaryToolConfig",
    "SkillsListToolConfig",
    "SkillViewToolConfig",
    "ModelCatalogValidationError",
    "ModelCatalogConfig",
    "ToolCatalogConfig",
    "ToolCatalogSectionSpec",
    "load_model_catalog_document",
    "load_model_catalog_toml",
    "load_tool_catalog_document",
    "AuthJwtKey",
    "Settings",
    "ensure_runtime_directories",
    "load_local_env_file",
]
