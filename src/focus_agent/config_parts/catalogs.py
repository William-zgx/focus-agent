from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import tomllib
from typing import Any, Callable, MutableMapping, TypeVar

from .common import _coerce_bool, _normalize_optional_string, _split_csv


DEFAULT_MODEL_CATALOG_DOC = ".focus_agent/models.toml"
DEFAULT_TOOL_CATALOG_DOC = ".focus_agent/tools.toml"
_ToolConfigT = TypeVar("_ToolConfigT")


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
    write_text_artifact: WriteTextArtifactToolConfig = field(
        default_factory=WriteTextArtifactToolConfig
    )
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
    conversation_summary: ConversationSummaryToolConfig = field(
        default_factory=ConversationSummaryToolConfig
    )
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
        path or target_env.get("FOCUS_AGENT_MODEL_CATALOG_DOC") or DEFAULT_MODEL_CATALOG_DOC
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
        path or target_env.get("FOCUS_AGENT_TOOL_CATALOG_DOC") or DEFAULT_TOOL_CATALOG_DOC
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
