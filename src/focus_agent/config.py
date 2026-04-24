from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import tomllib
from typing import Any, Callable, MutableMapping, TypeVar


DEFAULT_LOCAL_ENV_FILE = ".focus_agent/local.env"
DEFAULT_MODEL_CATALOG_DOC = ".focus_agent/models.toml"
DEFAULT_TOOL_CATALOG_DOC = ".focus_agent/tools.toml"
_ENV_ASSIGNMENT_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=\s*(.*)$")
_ToolConfigT = TypeVar("_ToolConfigT")


def _normalize_config_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _split_csv(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _normalize_optional_string(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _split_listish(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return _split_csv(value)
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _copy_toml_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _copy_toml_value(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_copy_toml_value(item) for item in value]
    return value


def _copy_toml_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _copy_toml_value(nested) for key, nested in value.items()}


def _tool_enabled(raw: object, default: bool = True) -> bool:
    coerced = _coerce_bool(raw)
    return default if coerced is None else coerced


def _tool_label(raw: object, default: str) -> str:
    return _normalize_optional_string(raw) or default


def _tool_description(raw: object, default: str) -> str:
    return _normalize_optional_string(raw) or default


def _load_basic_tool_config(
    raw_section: object,
    defaults: _ToolConfigT,
    *,
    int_fields: tuple[str, ...] = (),
    optional_string_fields: tuple[str, ...] = (),
) -> _ToolConfigT:
    if not isinstance(raw_section, dict):
        return defaults

    values: dict[str, object] = {}
    for field_name in defaults.__dataclass_fields__:
        default_value = getattr(defaults, field_name)
        raw_value = raw_section.get(field_name)
        if field_name == "enabled":
            values[field_name] = _tool_enabled(raw_value, default_value)
        elif field_name == "label":
            values[field_name] = _tool_label(raw_value, default_value)
        elif field_name == "description":
            values[field_name] = _tool_description(raw_value, default_value)
        elif field_name in int_fields:
            values[field_name] = int(raw_section.get(field_name, default_value))
        elif field_name in optional_string_fields:
            values[field_name] = _normalize_optional_string(raw_value) or default_value
        else:
            values[field_name] = default_value

    return type(defaults)(**values)


def load_local_env_file(
    path: str | Path | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    target_env = environ if environ is not None else os.environ
    resolved = Path(
        path
        or target_env.get("FOCUS_AGENT_LOCAL_ENV_FILE")
        or DEFAULT_LOCAL_ENV_FILE
    ).expanduser()
    if not resolved.exists():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
        match = _ENV_ASSIGNMENT_RE.match(raw_line.strip())
        if not match:
            continue
        key, raw_value = match.groups()
        value = _normalize_config_value(raw_value)
        loaded[key] = value
        target_env.setdefault(key, value)
    return loaded


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    id: str
    label: str | None = None
    backend_provider: str | None = None
    aliases: tuple[str, ...] = ()
    base_url_env: str | None = None
    base_url_default: str | None = None
    api_key_env: str | None = None
    api_key_default: str | None = None


@dataclass(frozen=True, slots=True)
class ConfiguredModel:
    id: str
    label: str | None = None
    supports_thinking: bool | None = None
    default_thinking_enabled: bool | None = None
    request_kwargs: dict[str, object] = field(default_factory=dict)
    thinking_enabled_request_kwargs: dict[str, object] = field(default_factory=dict)
    thinking_disabled_request_kwargs: dict[str, object] = field(default_factory=dict)
    thinking_disabled_model_name: str | None = None
    reasoning_effort: str | None = None
    no_temperature: bool | None = None
    thinking_enable_extra_body_type: str | None = None
    thinking_disable_extra_body_type: str | None = None
    thinking_disable_switch_model: str | None = None


@dataclass(frozen=True, slots=True)
class WebSearchConfig:
    enabled: bool = True
    label: str = "Web Search"
    description: str = "Search the live web with Tavily first and DuckDuckGo as a fallback."
    provider: str = "auto"
    fallback_provider: str | None = "duckduckgo"
    api_key_env: str | None = "TAVILY_API_KEY"
    api_key_default: str | None = None


@dataclass(frozen=True, slots=True)
class CurrentUtcTimeToolConfig:
    enabled: bool = True
    label: str = "Current UTC Time"
    description: str = "Return the current UTC timestamp in ISO-8601 format."


@dataclass(frozen=True, slots=True)
class WriteTextArtifactToolConfig:
    enabled: bool = True
    label: str = "Write Text Artifact"
    description: str = "Write a text artifact to disk and return its location."


@dataclass(frozen=True, slots=True)
class ArtifactListToolConfig:
    enabled: bool = True
    label: str = "Artifact List"
    description: str = "List text artifacts saved in the configured artifact directory."
    default_max_results: int = 50
    max_results_cap: int = 200


@dataclass(frozen=True, slots=True)
class ArtifactReadToolConfig:
    enabled: bool = True
    label: str = "Artifact Read"
    description: str = "Read a saved text artifact by filename or artifact id."
    max_chars: int = 50000


@dataclass(frozen=True, slots=True)
class ArtifactUpdateToolConfig:
    enabled: bool = True
    label: str = "Artifact Update"
    description: str = "Replace, append to, or prepend content in an existing text artifact."


@dataclass(frozen=True, slots=True)
class ListFilesToolConfig:
    enabled: bool = True
    label: str = "List Files"
    description: str = "List workspace files under a directory using a glob-like pattern."
    default_max_results: int = 200
    max_results_cap: int = 500


@dataclass(frozen=True, slots=True)
class ReadFileToolConfig:
    enabled: bool = True
    label: str = "Read File"
    description: str = "Read a UTF-8 text file from the workspace with line numbers."
    default_end_line: int = 200
    max_lines: int = 400
    max_chars: int = 50000


@dataclass(frozen=True, slots=True)
class SearchCodeToolConfig:
    enabled: bool = True
    label: str = "Search Code"
    description: str = "Search for matching text in workspace files and return matching lines."
    default_max_results: int = 30
    max_results_cap: int = 100


@dataclass(frozen=True, slots=True)
class CodebaseStatsToolConfig:
    enabled: bool = True
    label: str = "Codebase Stats"
    description: str = "Summarize file counts and line counts for the current workspace."
    default_max_files: int = 5000
    max_files_cap: int = 10000


@dataclass(frozen=True, slots=True)
class GitStatusToolConfig:
    enabled: bool = True
    label: str = "Git Status"
    description: str = "Inspect the current repository status from the workspace root."


@dataclass(frozen=True, slots=True)
class GitDiffToolConfig:
    enabled: bool = True
    label: str = "Git Diff"
    description: str = "Return a git diff for the workspace, optionally narrowed to one path."
    default_context_lines: int = 3
    max_context_lines: int = 20
    max_diff_chars: int = 20000


@dataclass(frozen=True, slots=True)
class GitLogToolConfig:
    enabled: bool = True
    label: str = "Git Log"
    description: str = "Return recent commits from the current repository."
    default_limit: int = 10
    max_limit: int = 50


@dataclass(frozen=True, slots=True)
class WebFetchToolConfig:
    enabled: bool = True
    label: str = "Web Fetch"
    description: str = "Fetch and extract readable text from a user-provided HTTP or HTTPS URL."
    default_max_chars: int = 12000
    max_chars_cap: int = 50000


@dataclass(frozen=True, slots=True)
class MemorySaveToolConfig:
    enabled: bool = True
    label: str = "Memory Save"
    description: str = "Save an explicit durable memory such as a user preference or project fact."


@dataclass(frozen=True, slots=True)
class MemorySearchToolConfig:
    enabled: bool = True
    label: str = "Memory Search"
    description: str = "Search durable memories by query across the default memory namespaces."
    default_limit: int = 5
    max_limit: int = 20


@dataclass(frozen=True, slots=True)
class MemoryForgetToolConfig:
    enabled: bool = True
    label: str = "Memory Forget"
    description: str = "Delete a saved memory by id from an explicit or default memory namespace."


@dataclass(frozen=True, slots=True)
class ConversationSummaryToolConfig:
    enabled: bool = True
    label: str = "Conversation Summary"
    description: str = "Return the latest saved rolling summary and recent messages for a thread."
    default_recent_messages: int = 8
    max_recent_messages: int = 30


@dataclass(frozen=True, slots=True)
class SkillsListToolConfig:
    enabled: bool = True
    label: str = "Skills List"
    description: str = "List bundled and local skills with their descriptions and trigger prefixes."


@dataclass(frozen=True, slots=True)
class SkillViewToolConfig:
    enabled: bool = True
    label: str = "Skill View"
    description: str = "Load the full instructions for a named skill."


@dataclass(frozen=True, slots=True)
class ModelCatalogConfig:
    default_model: str | None = None
    helper_model: str | None = None
    model_choices: tuple[str, ...] = ()
    providers: tuple[ProviderConfig, ...] = ()
    models: tuple[ConfiguredModel, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolCatalogConfig:
    current_utc_time: CurrentUtcTimeToolConfig = field(default_factory=CurrentUtcTimeToolConfig)
    write_text_artifact: WriteTextArtifactToolConfig = field(default_factory=WriteTextArtifactToolConfig)
    artifact_list: ArtifactListToolConfig = field(default_factory=ArtifactListToolConfig)
    artifact_read: ArtifactReadToolConfig = field(default_factory=ArtifactReadToolConfig)
    artifact_update: ArtifactUpdateToolConfig = field(default_factory=ArtifactUpdateToolConfig)
    list_files: ListFilesToolConfig = field(default_factory=ListFilesToolConfig)
    read_file: ReadFileToolConfig = field(default_factory=ReadFileToolConfig)
    search_code: SearchCodeToolConfig = field(default_factory=SearchCodeToolConfig)
    codebase_stats: CodebaseStatsToolConfig = field(default_factory=CodebaseStatsToolConfig)
    git_status: GitStatusToolConfig = field(default_factory=GitStatusToolConfig)
    git_diff: GitDiffToolConfig = field(default_factory=GitDiffToolConfig)
    git_log: GitLogToolConfig = field(default_factory=GitLogToolConfig)
    web_fetch: WebFetchToolConfig = field(default_factory=WebFetchToolConfig)
    memory_save: MemorySaveToolConfig = field(default_factory=MemorySaveToolConfig)
    memory_search: MemorySearchToolConfig = field(default_factory=MemorySearchToolConfig)
    memory_forget: MemoryForgetToolConfig = field(default_factory=MemoryForgetToolConfig)
    conversation_summary: ConversationSummaryToolConfig = field(default_factory=ConversationSummaryToolConfig)
    skills_list: SkillsListToolConfig = field(default_factory=SkillsListToolConfig)
    skill_view: SkillViewToolConfig = field(default_factory=SkillViewToolConfig)
    web_search: WebSearchConfig = field(default_factory=WebSearchConfig)
    section_order: tuple[str, ...] = ()

    @property
    def section_names(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                [
                    *self.section_order,
                    *tuple(_TOOL_CATALOG_SPECS),
                ]
            )
        )

    @property
    def by_name(self) -> dict[str, Any]:
        return {section_name: getattr(self, section_name) for section_name in self.section_names}


@dataclass(frozen=True, slots=True)
class ToolCatalogSectionSpec:
    defaults_factory: Callable[[], Any]
    int_fields: tuple[str, ...] = ()
    optional_string_fields: tuple[str, ...] = ()


_TOOL_CATALOG_SPECS: dict[str, ToolCatalogSectionSpec] = {
    "current_utc_time": ToolCatalogSectionSpec(CurrentUtcTimeToolConfig),
    "write_text_artifact": ToolCatalogSectionSpec(WriteTextArtifactToolConfig),
    "artifact_list": ToolCatalogSectionSpec(
        ArtifactListToolConfig,
        int_fields=("default_max_results", "max_results_cap"),
    ),
    "artifact_read": ToolCatalogSectionSpec(
        ArtifactReadToolConfig,
        int_fields=("max_chars",),
    ),
    "artifact_update": ToolCatalogSectionSpec(ArtifactUpdateToolConfig),
    "list_files": ToolCatalogSectionSpec(
        ListFilesToolConfig,
        int_fields=("default_max_results", "max_results_cap"),
    ),
    "read_file": ToolCatalogSectionSpec(
        ReadFileToolConfig,
        int_fields=("default_end_line", "max_lines", "max_chars"),
    ),
    "search_code": ToolCatalogSectionSpec(
        SearchCodeToolConfig,
        int_fields=("default_max_results", "max_results_cap"),
    ),
    "codebase_stats": ToolCatalogSectionSpec(
        CodebaseStatsToolConfig,
        int_fields=("default_max_files", "max_files_cap"),
    ),
    "git_status": ToolCatalogSectionSpec(GitStatusToolConfig),
    "git_diff": ToolCatalogSectionSpec(
        GitDiffToolConfig,
        int_fields=("default_context_lines", "max_context_lines", "max_diff_chars"),
    ),
    "git_log": ToolCatalogSectionSpec(
        GitLogToolConfig,
        int_fields=("default_limit", "max_limit"),
    ),
    "web_fetch": ToolCatalogSectionSpec(
        WebFetchToolConfig,
        int_fields=("default_max_chars", "max_chars_cap"),
    ),
    "memory_save": ToolCatalogSectionSpec(MemorySaveToolConfig),
    "memory_search": ToolCatalogSectionSpec(
        MemorySearchToolConfig,
        int_fields=("default_limit", "max_limit"),
    ),
    "memory_forget": ToolCatalogSectionSpec(MemoryForgetToolConfig),
    "conversation_summary": ToolCatalogSectionSpec(
        ConversationSummaryToolConfig,
        int_fields=("default_recent_messages", "max_recent_messages"),
    ),
    "skills_list": ToolCatalogSectionSpec(SkillsListToolConfig),
    "skill_view": ToolCatalogSectionSpec(SkillViewToolConfig),
    "web_search": ToolCatalogSectionSpec(
        WebSearchConfig,
        optional_string_fields=("provider", "fallback_provider", "api_key_env", "api_key_default"),
    ),
}


def load_model_catalog_document(
    path: str | Path | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> ModelCatalogConfig:
    target_env = environ if environ is not None else os.environ
    resolved = Path(
        path
        or target_env.get("FOCUS_AGENT_MODEL_CATALOG_DOC")
        or DEFAULT_MODEL_CATALOG_DOC
    ).expanduser()
    if not resolved.exists():
        return ModelCatalogConfig()

    raw = tomllib.loads(resolved.read_text(encoding="utf-8"))
    provider_entries: list[ProviderConfig] = []
    for item in raw.get("providers", []) or []:
        if not isinstance(item, dict):
            continue
        provider_id = _normalize_optional_string(item.get("id"))
        if provider_id is None:
            continue
        provider_entries.append(
            ProviderConfig(
                id=provider_id.lower(),
                label=_normalize_optional_string(item.get("label")),
                backend_provider=_normalize_optional_string(item.get("backend_provider")),
                aliases=tuple(alias.lower() for alias in _split_listish(item.get("aliases"))),
                base_url_env=_normalize_optional_string(item.get("base_url_env")),
                base_url_default=_normalize_optional_string(item.get("base_url_default")),
                api_key_env=_normalize_optional_string(item.get("api_key_env")),
                api_key_default=_normalize_optional_string(item.get("api_key_default")),
            )
        )

    model_entries: list[ConfiguredModel] = []
    for item in raw.get("models", []) or []:
        if not isinstance(item, dict):
            continue
        model_id = _normalize_optional_string(item.get("id"))
        if model_id is None:
            continue
        model_entries.append(
            ConfiguredModel(
                id=model_id,
                label=_normalize_optional_string(item.get("label")),
                supports_thinking=_coerce_bool(item.get("supports_thinking")),
                default_thinking_enabled=_coerce_bool(item.get("default_thinking_enabled")),
                request_kwargs=_copy_toml_mapping(item.get("request_kwargs")),
                thinking_enabled_request_kwargs=_copy_toml_mapping(
                    item.get("thinking_enabled_request_kwargs")
                ),
                thinking_disabled_request_kwargs=_copy_toml_mapping(
                    item.get("thinking_disabled_request_kwargs")
                ),
                thinking_disabled_model_name=_normalize_optional_string(
                    item.get("thinking_disabled_model_name")
                ),
                reasoning_effort=_normalize_optional_string(item.get("reasoning_effort")),
                no_temperature=_coerce_bool(item.get("no_temperature")),
                thinking_enable_extra_body_type=_normalize_optional_string(
                    item.get("thinking_enable_extra_body_type")
                ),
                thinking_disable_extra_body_type=_normalize_optional_string(
                    item.get("thinking_disable_extra_body_type")
                ),
                thinking_disable_switch_model=_normalize_optional_string(
                    item.get("thinking_disable_switch_model")
                ),
            )
        )

    return ModelCatalogConfig(
        default_model=_normalize_optional_string(raw.get("default_model")),
        helper_model=_normalize_optional_string(raw.get("helper_model")),
        model_choices=_split_listish(raw.get("model_choices")),
        providers=tuple(provider_entries),
        models=tuple(model_entries),
    )


def load_tool_catalog_document(
    path: str | Path | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> ToolCatalogConfig:
    target_env = environ if environ is not None else os.environ
    resolved = Path(
        path
        or target_env.get("FOCUS_AGENT_TOOL_CATALOG_DOC")
        or DEFAULT_TOOL_CATALOG_DOC
    ).expanduser()
    if not resolved.exists():
        return ToolCatalogConfig()

    raw = tomllib.loads(resolved.read_text(encoding="utf-8"))
    ordered_section_names = tuple(
        dict.fromkeys(
            [
                *(section_name for section_name in raw if section_name in _TOOL_CATALOG_SPECS),
                *tuple(_TOOL_CATALOG_SPECS),
            ]
        )
    )
    loaded_sections = {
        section_name: _load_basic_tool_config(
            raw.get(section_name),
            spec.defaults_factory(),
            int_fields=spec.int_fields,
            optional_string_fields=spec.optional_string_fields,
        )
        for section_name, spec in _TOOL_CATALOG_SPECS.items()
    }
    return ToolCatalogConfig(section_order=ordered_section_names, **loaded_sections)


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
    auth_jwt_secret: str = "focus-agent-dev-secret"
    auth_jwt_issuer: str = "focus-agent"
    auth_access_token_ttl_seconds: int = 8 * 60 * 60
    sse_heartbeat_seconds: float = 1.5
    cors_allowed_origins: tuple[str, ...] = ()
    cors_allow_credentials: bool = True
    rate_limit_enabled: bool = False
    rate_limit_per_minute: int = 60
    rate_limit_chat_per_minute: int = 20
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
        database_uri = env.get("DATABASE_URI") or None
        langgraph_api_url = env.get("LANGGRAPH_API_URL") or None
        trajectory_enabled = _coerce_bool(env.get("TRAJECTORY_ENABLED"))
        otel_traces_exporters = (
            _split_csv(env.get("OTEL_TRACES_EXPORTER"))
            if env.get("OTEL_TRACES_EXPORTER") is not None
            else (
                ("otlp",)
                if (
                    env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
                    or env.get("OTEL_EXPORTER_OTLP_ENDPOINT")
                )
                else defaults.otel_traces_exporters
            )
        )
        instance = cls(
            model=env.get("MODEL") or model_catalog.default_model or defaults.model,
            helper_model=env.get("HELPER_MODEL") or model_catalog.helper_model or None,
            model_choices=model_catalog.model_choices or defaults.model_choices,
            model_catalog=model_catalog,
            tool_catalog=tool_catalog,
            web_search=tool_catalog.web_search,
            resolved_env=dict(env),
            temperature=float(env.get("TEMPERATURE", str(defaults.temperature))),
            database_uri=database_uri,
            langgraph_api_url=langgraph_api_url,
            langsmith_project=env.get("LANGSMITH_PROJECT", defaults.langsmith_project),
            branch_db_path=env.get("BRANCH_DB_PATH", defaults.branch_db_path),
            artifact_dir=env.get("ARTIFACT_DIR", defaults.artifact_dir),
            api_host=env.get("API_HOST", defaults.api_host),
            api_port=int(env.get("API_PORT", str(defaults.api_port))),
            api_reload=env.get("API_RELOAD", "false").lower() in {"1", "true", "yes", "on"},
            app_version=env.get("APP_VERSION", defaults.app_version),
            app_environment=(
                env.get("APP_ENVIRONMENT")
                or env.get("ENVIRONMENT")
                or defaults.app_environment
            ),
            deployment_name=env.get("DEPLOYMENT_NAME") or defaults.deployment_name,
            tracing_enabled=(
                _coerce_bool(env.get("FOCUS_AGENT_TRACING_ENABLED"))
                if env.get("FOCUS_AGENT_TRACING_ENABLED") is not None
                else _coerce_bool(env.get("OTEL_TRACING_ENABLED")) or defaults.tracing_enabled
            ),
            tracing_service_name=(
                env.get("OTEL_SERVICE_NAME")
                or env.get("FOCUS_AGENT_TRACING_SERVICE_NAME")
                or defaults.tracing_service_name
            ),
            otel_traces_exporters=otel_traces_exporters,
            otel_exporter_otlp_endpoint=env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
            otel_exporter_otlp_traces_endpoint=env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or None,
            otel_exporter_otlp_headers=(
                env.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS")
                or env.get("OTEL_EXPORTER_OTLP_HEADERS")
                or None
            ),
            otel_exporter_otlp_protocol=(
                env.get("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL")
                or env.get("OTEL_EXPORTER_OTLP_PROTOCOL")
                or defaults.otel_exporter_otlp_protocol
            ),
            otel_exporter_otlp_timeout_ms=int(
                env.get(
                    "OTEL_EXPORTER_OTLP_TRACES_TIMEOUT",
                    env.get(
                        "OTEL_EXPORTER_OTLP_TIMEOUT",
                        str(defaults.otel_exporter_otlp_timeout_ms),
                    ),
                )
            ),
            web_app_dist_dir=env.get("WEB_APP_DIST_DIR") or None,
            web_app_dev_server_url=env.get("WEB_APP_DEV_SERVER_URL") or None,
            auth_enabled=env.get("AUTH_ENABLED", "true").lower() in {"1", "true", "yes", "on"},
            auth_demo_tokens_enabled=env.get("AUTH_DEMO_TOKENS_ENABLED", "true").lower()
            in {"1", "true", "yes", "on"},
            auth_jwt_secret=env.get("AUTH_JWT_SECRET", defaults.auth_jwt_secret),
            auth_jwt_issuer=env.get("AUTH_JWT_ISSUER", defaults.auth_jwt_issuer),
            auth_access_token_ttl_seconds=int(
                env.get(
                    "AUTH_ACCESS_TOKEN_TTL_SECONDS",
                    str(defaults.auth_access_token_ttl_seconds),
                )
            ),
            sse_heartbeat_seconds=float(
                env.get("SSE_HEARTBEAT_SECONDS", str(defaults.sse_heartbeat_seconds))
            ),
            cors_allowed_origins=_split_csv(env.get("CORS_ALLOWED_ORIGINS")),
            cors_allow_credentials=env.get("CORS_ALLOW_CREDENTIALS", "true").lower()
            in {"1", "true", "yes", "on"},
            rate_limit_enabled=env.get("RATE_LIMIT_ENABLED", "false").lower()
            in {"1", "true", "yes", "on"},
            rate_limit_per_minute=int(
                env.get("RATE_LIMIT_PER_MINUTE", str(defaults.rate_limit_per_minute))
            ),
            rate_limit_chat_per_minute=int(
                env.get("RATE_LIMIT_CHAT_PER_MINUTE", str(defaults.rate_limit_chat_per_minute))
            ),
            local_checkpoint_path=env.get("LOCAL_CHECKPOINT_PATH") or None,
            local_store_path=env.get("LOCAL_STORE_PATH") or None,
            branch_max_depth=int(env.get("BRANCH_MAX_DEPTH", str(defaults.branch_max_depth))),
            skill_directories=(
                _split_csv(env.get("FOCUS_AGENT_SKILLS_DIRS"))
                if env.get("FOCUS_AGENT_SKILLS_DIRS") is not None
                else defaults.skill_directories
            ),
            workspace_root=env.get("WORKSPACE_ROOT", defaults.workspace_root),
            plan_act_reflect_enabled=env.get(
                "PLAN_ACT_REFLECT_ENABLED",
                "true" if defaults.plan_act_reflect_enabled else "false",
            ).lower() in {"1", "true", "yes", "on"},
            plan_scenes=(
                _split_csv(env.get("PLAN_SCENES"))
                if env.get("PLAN_SCENES") is not None
                else defaults.plan_scenes
            ),
            plan_task_brief_min_chars=int(
                env.get("PLAN_TASK_BRIEF_MIN_CHARS", str(defaults.plan_task_brief_min_chars))
            ),
            plan_max_replans=int(
                env.get("PLAN_MAX_REPLANS", str(defaults.plan_max_replans))
            ),
            agent_role_routing_enabled=env.get(
                "AGENT_ROLE_ROUTING_ENABLED",
                "true" if defaults.agent_role_routing_enabled else "false",
            ).lower() in {"1", "true", "yes", "on"},
            agent_role_orchestrator_model=(
                env.get("AGENT_ROLE_ORCHESTRATOR_MODEL")
                or defaults.agent_role_orchestrator_model
            ),
            agent_role_planner_model=(
                env.get("AGENT_ROLE_PLANNER_MODEL") or defaults.agent_role_planner_model
            ),
            agent_role_executor_model=(
                env.get("AGENT_ROLE_EXECUTOR_MODEL") or defaults.agent_role_executor_model
            ),
            agent_role_critic_model=(
                env.get("AGENT_ROLE_CRITIC_MODEL") or defaults.agent_role_critic_model
            ),
            agent_role_memory_model=(
                env.get("AGENT_ROLE_MEMORY_MODEL") or defaults.agent_role_memory_model
            ),
            agent_role_skill_model=(
                env.get("AGENT_ROLE_SKILL_MODEL") or defaults.agent_role_skill_model
            ),
            agent_role_max_parallel_runs=max(
                1,
                int(
                    env.get(
                        "AGENT_ROLE_MAX_PARALLEL_RUNS",
                        str(defaults.agent_role_max_parallel_runs),
                    )
                ),
            ),
            trajectory_enabled=(
                bool(database_uri) if trajectory_enabled is None else trajectory_enabled
            ),
            trajectory_observation_max_chars=int(
                env.get(
                    "TRAJECTORY_OBSERVATION_MAX_CHARS",
                    str(defaults.trajectory_observation_max_chars),
                )
            ),
            trajectory_answer_max_chars=int(
                env.get(
                    "TRAJECTORY_ANSWER_MAX_CHARS",
                    str(defaults.trajectory_answer_max_chars),
                )
            ),
            trajectory_hash_user_id=env.get(
                "TRAJECTORY_HASH_USER_ID",
                "true" if defaults.trajectory_hash_user_id else "false",
            ).lower() in {"1", "true", "yes", "on"},
        )
        Path(instance.branch_db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        Path(instance.artifact_dir).expanduser().mkdir(parents=True, exist_ok=True)
        return instance
