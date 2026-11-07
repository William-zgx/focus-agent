from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from ..core.coercion import optional_str
from .catalog_config_types import (
    ApplyPatchToolConfig,
    ArtifactListToolConfig,
    ArtifactReadToolConfig,
    ArtifactSearchToolConfig,
    ArtifactUpdateToolConfig,
    AskUserQuestionToolConfig,
    CodebaseStatsToolConfig,
    ConfiguredModel,
    ConversationSummaryToolConfig,
    CurrentUtcTimeToolConfig,
    GitDiffToolConfig,
    GitLogToolConfig,
    GitStatusToolConfig,
    HooksConfig,
    ListFilesToolConfig,
    MCPServerConfig,
    MemoryForgetToolConfig,
    MemorySaveToolConfig,
    MemorySearchToolConfig,
    PermissionsConfig,
    ProductivityToolConfig,
    ProviderConfig,
    ReadFileToolConfig,
    RunWorkspaceCommandToolConfig,
    SearchCodeToolConfig,
    SkillInstallToolConfig,
    SkillsListToolConfig,
    SkillSourcesToolConfig,
    SkillsRefreshIndexToolConfig,
    SkillsSearchToolConfig,
    SkillViewToolConfig,
    ToolProviderConfig,
    WebFetchToolConfig,
    WebSearchConfig,
    WorkspaceSearchToolConfig,
    WorkspaceTreeToolConfig,
    WriteTextArtifactToolConfig,
)
from .catalog_toml_helpers import _load_string_mapping, load_tool_governance_configs
from .common import _split_csv
from .env import parse_bool

DEFAULT_MODEL_CATALOG_DOC = ".focus_agent/models.toml"
DEFAULT_TOOL_CATALOG_DOC = ".focus_agent/tools.toml"
_ToolConfigT = TypeVar("_ToolConfigT")
_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
_MODEL_PROTOCOLS = frozenset({"chat", "system_one"})
_TOOL_METADATA_OVERLAY_KEYS = frozenset(
    {
        "allowed_roles",
        "cache_scope",
        "cacheable",
        "fallback_group",
        "intent_policies",
        "intent_tags",
        "max_observation_chars",
        "parallel_safe",
        "requires_approval",
        "requires_network",
        "requires_workspace_write",
        "risk_level",
        "side_effect",
        "side_effect_kind",
        "timeout_seconds",
        "toolset",
    }
)
_TOOL_PROVIDER_CONFIG_KEYS = frozenset({"id", "enabled", "order", "metadata", "overrides"})
_MCP_SERVER_NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")
_MCP_TRANSPORTS = frozenset({"stdio", "streamable_http"})
_MCP_SERVER_CONFIG_KEYS = frozenset(
    "name transport command args env env_from url headers_from_env enabled "
    "allowed_tools requires_approval timeout_seconds".split()
)
_TOOL_CATALOG_RESERVED_KEYS = frozenset({"providers", "mcp_servers", "permissions", "hooks"})


class ModelCatalogValidationError(ValueError):
    """Raised when model catalog configuration is malformed or ambiguous."""


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


def _catalog_error(source: str, detail: str) -> ModelCatalogValidationError:
    return ModelCatalogValidationError(f"{source}: {detail}")


def _model_provider_name(model_id: str) -> str:
    raw = str(model_id or "").strip()
    provider = raw.split(":", 1)[0] if ":" in raw else "openai"
    return provider.strip().lower()


def _model_name_part(model_id: str) -> str:
    raw = str(model_id or "").strip()
    return raw.split(":", 1)[1].strip() if ":" in raw else raw


def _canonical_model_key(model_id: str, aliases: dict[str, str]) -> str:
    provider = aliases.get(_model_provider_name(model_id), _model_provider_name(model_id))
    return f"{provider}:{_model_name_part(model_id)}"


def _validate_provider_id(provider_id: str, *, source: str, location: str) -> None:
    if not _PROVIDER_ID_PATTERN.fullmatch(provider_id):
        raise _catalog_error(
            source,
            f"{location}.id must match {_PROVIDER_ID_PATTERN.pattern!r}; got {provider_id!r}.",
        )


def _normalize_provider_id(raw: object, *, source: str, location: str) -> str:
    provider_id = optional_str(raw)
    if provider_id is None:
        raise _catalog_error(source, f"{location}.id is required.")
    provider_id = provider_id.lower()
    _validate_provider_id(provider_id, source=source, location=location)
    return provider_id


def _validate_provider_aliases(
    providers: tuple[ProviderConfig, ...],
    *,
    source: str,
) -> dict[str, str]:
    provider_ids = {provider.id for provider in providers}
    alias_owner: dict[str, str] = {}
    for provider in providers:
        for alias in provider.aliases:
            if not _PROVIDER_ID_PATTERN.fullmatch(alias):
                raise _catalog_error(
                    source,
                    f"provider {provider.id!r} alias {alias!r} must match "
                    f"{_PROVIDER_ID_PATTERN.pattern!r}.",
                )
            if alias in provider_ids:
                raise _catalog_error(
                    source,
                    f"provider {provider.id!r} alias {alias!r} conflicts with a provider id.",
                )
            previous = alias_owner.get(alias)
            if previous is not None and previous != provider.id:
                raise _catalog_error(
                    source,
                    f"provider alias {alias!r} is assigned to both {previous!r} and "
                    f"{provider.id!r}.",
                )
            alias_owner[alias] = provider.id
    return alias_owner


def _tool_enabled(raw: object, default: bool = True) -> bool:
    coerced = parse_bool(raw)
    return default if coerced is None else coerced


def _tool_label(raw: object, default: str) -> str:
    return optional_str(raw) or default


def _tool_description(raw: object, default: str) -> str:
    return optional_str(raw) or default


def _load_basic_tool_config(
    raw_section: object,
    defaults: _ToolConfigT,
    *,
    int_fields: tuple[str, ...] = (),
    optional_string_fields: tuple[str, ...] = (),
    tuple_fields: tuple[str, ...] = (),
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
            values[field_name] = optional_str(raw_value) or default_value
        elif field_name in tuple_fields:
            values[field_name] = _split_listish(raw_value) or default_value
        else:
            values[field_name] = default_value

    return type(defaults)(**values)


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
    artifact_search: ArtifactSearchToolConfig = field(default_factory=ArtifactSearchToolConfig)
    list_files: ListFilesToolConfig = field(default_factory=ListFilesToolConfig)
    workspace_tree: WorkspaceTreeToolConfig = field(default_factory=WorkspaceTreeToolConfig)
    read_file: ReadFileToolConfig = field(default_factory=ReadFileToolConfig)
    search_code: SearchCodeToolConfig = field(default_factory=SearchCodeToolConfig)
    workspace_search: WorkspaceSearchToolConfig = field(default_factory=WorkspaceSearchToolConfig)
    codebase_stats: CodebaseStatsToolConfig = field(default_factory=CodebaseStatsToolConfig)
    apply_patch: ApplyPatchToolConfig = field(default_factory=ApplyPatchToolConfig)
    run_workspace_command: RunWorkspaceCommandToolConfig = field(
        default_factory=RunWorkspaceCommandToolConfig
    )
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
    ask_user_question: AskUserQuestionToolConfig = field(default_factory=AskUserQuestionToolConfig)
    skills_list: SkillsListToolConfig = field(default_factory=SkillsListToolConfig)
    skill_view: SkillViewToolConfig = field(default_factory=SkillViewToolConfig)
    skill_sources: SkillSourcesToolConfig = field(default_factory=SkillSourcesToolConfig)
    skills_search: SkillsSearchToolConfig = field(default_factory=SkillsSearchToolConfig)
    skill_install: SkillInstallToolConfig = field(default_factory=SkillInstallToolConfig)
    skills_refresh_index: SkillsRefreshIndexToolConfig = field(
        default_factory=SkillsRefreshIndexToolConfig
    )
    notes_create: ProductivityToolConfig = field(
        default_factory=lambda: ProductivityToolConfig(
            label="Create Note",
            description="Create a personal note owned by the current user.",
        )
    )
    notes_search: ProductivityToolConfig = field(
        default_factory=lambda: ProductivityToolConfig(
            label="Search Notes",
            description="Search personal notes owned by the current user.",
        )
    )
    notes_update: ProductivityToolConfig = field(
        default_factory=lambda: ProductivityToolConfig(
            label="Update Note",
            description="Update a personal note owned by the current user.",
        )
    )
    tasks_create: ProductivityToolConfig = field(
        default_factory=lambda: ProductivityToolConfig(
            label="Create Task",
            description="Create a personal task owned by the current user.",
        )
    )
    tasks_list: ProductivityToolConfig = field(
        default_factory=lambda: ProductivityToolConfig(
            label="List Tasks",
            description="List personal tasks owned by the current user.",
        )
    )
    tasks_update: ProductivityToolConfig = field(
        default_factory=lambda: ProductivityToolConfig(
            label="Update Task",
            description="Update a personal task owned by the current user.",
        )
    )
    productivity_capture: ProductivityToolConfig = field(
        default_factory=lambda: ProductivityToolConfig(
            label="Capture Productivity Item",
            description="Capture a chat or Agent Team payload as an explicit note or task.",
        )
    )
    web_search: WebSearchConfig = field(default_factory=WebSearchConfig)
    section_order: tuple[str, ...] = ()
    metadata_section_order: tuple[str, ...] = ()
    generic_metadata_overlays: dict[str, dict[str, object]] = field(default_factory=dict)
    providers: tuple[ToolProviderConfig, ...] = ()
    mcp_servers: tuple[MCPServerConfig, ...] = ()
    permissions: PermissionsConfig = field(default_factory=PermissionsConfig)
    hooks: HooksConfig = field(default_factory=HooksConfig)

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

    @property
    def manifest_section_names(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                [
                    *self.metadata_section_order,
                    *self.section_order,
                    *tuple(_TOOL_CATALOG_SPECS),
                    *self.generic_metadata_overlays.keys(),
                ]
            )
        )

    def metadata_overlay_for(self, tool_name: str) -> dict[str, object]:
        return dict(self.generic_metadata_overlays.get(tool_name, {}))

    def provider_config_for(self, provider_id: str) -> ToolProviderConfig | None:
        normalized = str(provider_id or "").strip().lower()
        for provider in self.providers:
            if provider.id == normalized:
                return provider
        return None

    def provider_metadata_overlay_for(self, provider_id: str) -> dict[str, object]:
        provider = self.provider_config_for(provider_id)
        return dict(provider.metadata) if provider is not None else {}

    def provider_overrides_for(self, provider_id: str) -> tuple[str, ...]:
        provider = self.provider_config_for(provider_id)
        return provider.overrides if provider is not None else ()


@dataclass(frozen=True, slots=True)
class ToolCatalogSectionSpec:
    defaults_factory: Callable[[], Any]
    int_fields: tuple[str, ...] = ()
    optional_string_fields: tuple[str, ...] = ()
    tuple_fields: tuple[str, ...] = ()


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
    "artifact_search": ToolCatalogSectionSpec(
        ArtifactSearchToolConfig,
        int_fields=("default_limit", "max_limit"),
    ),
    "list_files": ToolCatalogSectionSpec(
        ListFilesToolConfig,
        int_fields=("default_max_results", "max_results_cap"),
    ),
    "workspace_tree": ToolCatalogSectionSpec(
        WorkspaceTreeToolConfig,
        int_fields=(
            "default_max_depth",
            "max_depth_cap",
            "default_max_entries",
            "max_entries_cap",
        ),
    ),
    "read_file": ToolCatalogSectionSpec(
        ReadFileToolConfig,
        int_fields=("default_end_line", "max_lines", "max_chars"),
    ),
    "search_code": ToolCatalogSectionSpec(
        SearchCodeToolConfig,
        int_fields=("default_max_results", "max_results_cap"),
    ),
    "workspace_search": ToolCatalogSectionSpec(
        WorkspaceSearchToolConfig,
        int_fields=("default_limit", "max_limit"),
    ),
    "codebase_stats": ToolCatalogSectionSpec(
        CodebaseStatsToolConfig,
        int_fields=("default_max_files", "max_files_cap"),
    ),
    "apply_patch": ToolCatalogSectionSpec(
        ApplyPatchToolConfig,
        int_fields=("max_patch_bytes",),
    ),
    "run_workspace_command": ToolCatalogSectionSpec(
        RunWorkspaceCommandToolConfig,
        int_fields=("default_timeout_seconds", "max_timeout_seconds", "max_output_chars"),
        tuple_fields=("allowed_commands",),
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
        tuple_fields=("blocked_domains", "allowed_domains"),
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
    "ask_user_question": ToolCatalogSectionSpec(AskUserQuestionToolConfig),
    "skills_list": ToolCatalogSectionSpec(SkillsListToolConfig),
    "skill_view": ToolCatalogSectionSpec(SkillViewToolConfig),
    "skill_sources": ToolCatalogSectionSpec(SkillSourcesToolConfig),
    "skills_search": ToolCatalogSectionSpec(
        SkillsSearchToolConfig,
        int_fields=("default_limit", "max_limit_cap"),
    ),
    "skill_install": ToolCatalogSectionSpec(SkillInstallToolConfig),
    "skills_refresh_index": ToolCatalogSectionSpec(SkillsRefreshIndexToolConfig),
    "notes_create": ToolCatalogSectionSpec(ProductivityToolConfig),
    "notes_search": ToolCatalogSectionSpec(ProductivityToolConfig),
    "notes_update": ToolCatalogSectionSpec(ProductivityToolConfig),
    "tasks_create": ToolCatalogSectionSpec(ProductivityToolConfig),
    "tasks_list": ToolCatalogSectionSpec(ProductivityToolConfig),
    "tasks_update": ToolCatalogSectionSpec(ProductivityToolConfig),
    "productivity_capture": ToolCatalogSectionSpec(ProductivityToolConfig),
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

    return load_model_catalog_toml(resolved.read_text(encoding="utf-8"), source=str(resolved))


def load_model_catalog_toml(content: str, *, source: str = "model catalog") -> ModelCatalogConfig:
    raw = tomllib.loads(content)
    provider_entries: list[ProviderConfig] = []
    seen_provider_ids: set[str] = set()
    for index, item in enumerate(raw.get("providers", []) or []):
        if not isinstance(item, dict):
            raise _catalog_error(source, f"providers[{index}] must be a TOML table.")
        provider_id = optional_str(item.get("id"))
        if provider_id is None:
            raise _catalog_error(source, f"providers[{index}].id is required.")
        provider_id = provider_id.lower()
        _validate_provider_id(provider_id, source=source, location=f"providers[{index}]")
        if provider_id in seen_provider_ids:
            raise _catalog_error(source, f"providers[{index}].id duplicates {provider_id!r}.")
        seen_provider_ids.add(provider_id)
        provider_entries.append(
            ProviderConfig(
                id=provider_id,
                label=optional_str(item.get("label")),
                backend_provider=optional_str(item.get("backend_provider")),
                aliases=tuple(alias.lower() for alias in _split_listish(item.get("aliases"))),
                logo_slug=optional_str(item.get("logo_slug")),
                logo_letter=optional_str(item.get("logo_letter")),
                base_url_env=optional_str(item.get("base_url_env")),
                base_url_default=optional_str(item.get("base_url_default")),
                api_key_env=optional_str(item.get("api_key_env")),
                api_key_default=optional_str(item.get("api_key_default")),
            )
        )
    aliases = _validate_provider_aliases(tuple(provider_entries), source=source)

    model_entries: list[ConfiguredModel] = []
    seen_model_ids: set[str] = set()
    for index, item in enumerate(raw.get("models", []) or []):
        if not isinstance(item, dict):
            raise _catalog_error(source, f"models[{index}] must be a TOML table.")
        model_id = optional_str(item.get("id"))
        if model_id is None:
            raise _catalog_error(source, f"models[{index}].id is required.")
        provider_name = _model_provider_name(model_id)
        model_name = _model_name_part(model_id)
        if not provider_name or not model_name:
            raise _catalog_error(source, f"models[{index}].id has invalid model id {model_id!r}.")
        model_key = _canonical_model_key(model_id, aliases)
        if model_key in seen_model_ids:
            raise _catalog_error(source, f"models[{index}].id duplicates {model_key!r}.")
        seen_model_ids.add(model_key)
        protocol = (optional_str(item.get("protocol")) or "chat").lower()
        if protocol not in _MODEL_PROTOCOLS:
            allowed = ", ".join(sorted(_MODEL_PROTOCOLS))
            raise _catalog_error(
                source,
                f"models[{index}].protocol must be one of: {allowed}.",
            )
        model_entries.append(
            ConfiguredModel(
                id=model_id,
                label=optional_str(item.get("label")),
                protocol=protocol,
                supports_thinking=parse_bool(item.get("supports_thinking")),
                default_thinking_enabled=parse_bool(item.get("default_thinking_enabled")),
                request_kwargs=_copy_toml_mapping(item.get("request_kwargs")),
                thinking_enabled_request_kwargs=_copy_toml_mapping(
                    item.get("thinking_enabled_request_kwargs")
                ),
                thinking_disabled_request_kwargs=_copy_toml_mapping(
                    item.get("thinking_disabled_request_kwargs")
                ),
                thinking_disabled_model_name=optional_str(item.get("thinking_disabled_model_name")),
                reasoning_effort=optional_str(item.get("reasoning_effort")),
                no_temperature=parse_bool(item.get("no_temperature")),
                thinking_enable_extra_body_type=optional_str(
                    item.get("thinking_enable_extra_body_type")
                ),
                thinking_disable_extra_body_type=optional_str(
                    item.get("thinking_disable_extra_body_type")
                ),
                thinking_disable_switch_model=optional_str(
                    item.get("thinking_disable_switch_model")
                ),
            )
        )

    return ModelCatalogConfig(
        default_model=optional_str(raw.get("default_model")),
        helper_model=optional_str(raw.get("helper_model")),
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
    raw_section_names = tuple(
        str(section_name) for section_name in raw if section_name not in _TOOL_CATALOG_RESERVED_KEYS
    )
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
            tuple_fields=spec.tuple_fields,
        )
        for section_name, spec in _TOOL_CATALOG_SPECS.items()
    }
    return ToolCatalogConfig(
        section_order=ordered_section_names,
        metadata_section_order=raw_section_names,
        generic_metadata_overlays=_load_tool_metadata_overlays(raw),
        providers=_load_tool_provider_configs(raw, source=str(resolved)),
        mcp_servers=_load_mcp_server_configs(raw, source=str(resolved)),
        **load_tool_governance_configs(raw, source=str(resolved), error=_catalog_error),
        **loaded_sections,
    )


def _load_tool_metadata_overlays(raw: dict[str, object]) -> dict[str, dict[str, object]]:
    overlays: dict[str, dict[str, object]] = {}
    for section_name, raw_section in raw.items():
        if section_name in _TOOL_CATALOG_RESERVED_KEYS:
            continue
        if not isinstance(raw_section, dict):
            continue
        overlay: dict[str, object] = {}
        metadata = raw_section.get("metadata")
        if isinstance(metadata, dict):
            overlay.update(_copy_toml_mapping(metadata))
        for key in _TOOL_METADATA_OVERLAY_KEYS:
            if key in raw_section:
                overlay[key] = _copy_toml_value(raw_section[key])
        if section_name not in _TOOL_CATALOG_SPECS:
            for key, value in raw_section.items():
                if key == "metadata":
                    continue
                overlay.setdefault(str(key), _copy_toml_value(value))
        if overlay:
            overlays[str(section_name)] = overlay
    return overlays


def _load_tool_provider_configs(
    raw: dict[str, object],
    *,
    source: str,
) -> tuple[ToolProviderConfig, ...]:
    raw_providers = raw.get("providers")
    if raw_providers is None:
        return ()
    if not isinstance(raw_providers, list):
        raise _catalog_error(source, "providers must be an array of TOML tables.")

    providers: list[ToolProviderConfig] = []
    seen_provider_ids: set[str] = set()
    for index, item in enumerate(raw_providers):
        location = f"providers[{index}]"
        if not isinstance(item, dict):
            raise _catalog_error(source, f"{location} must be a TOML table.")
        blocked_keys = {"module", "factory", "callable", "entrypoint"} & set(item)
        if blocked_keys:
            blocked = ", ".join(sorted(blocked_keys))
            raise _catalog_error(
                source,
                f"{location} may not configure external Python loading keys: {blocked}.",
            )
        unknown_keys = set(item) - _TOOL_PROVIDER_CONFIG_KEYS
        if unknown_keys:
            unknown = ", ".join(sorted(str(key) for key in unknown_keys))
            raise _catalog_error(source, f"{location} has unsupported keys: {unknown}.")

        provider_id = _normalize_provider_id(item.get("id"), source=source, location=location)
        if provider_id in seen_provider_ids:
            raise _catalog_error(source, f"{location}.id duplicates {provider_id!r}.")
        seen_provider_ids.add(provider_id)
        enabled = _tool_enabled(item.get("enabled"), True)
        order_raw = item.get("order")
        providers.append(
            ToolProviderConfig(
                id=provider_id,
                enabled=enabled,
                order=int(order_raw) if order_raw is not None else None,
                metadata=_copy_toml_mapping(item.get("metadata")),
                overrides=tuple(dict.fromkeys(_split_listish(item.get("overrides")))),
            )
        )
    return tuple(providers)


def _load_mcp_server_configs(
    raw: dict[str, object],
    *,
    source: str,
) -> tuple[MCPServerConfig, ...]:
    raw_servers = raw.get("mcp_servers")
    if raw_servers is None:
        return ()
    if not isinstance(raw_servers, list):
        raise _catalog_error(source, "mcp_servers must be an array of TOML tables.")
    servers: list[MCPServerConfig] = []
    seen_names: set[str] = set()
    for index, item in enumerate(raw_servers):
        location = f"mcp_servers[{index}]"
        if not isinstance(item, dict):
            raise _catalog_error(source, f"{location} must be a TOML table.")
        unknown_keys = set(item) - _MCP_SERVER_CONFIG_KEYS
        if unknown_keys:
            unknown = ", ".join(sorted(str(key) for key in unknown_keys))
            raise _catalog_error(source, f"{location} has unsupported keys: {unknown}.")
        name = optional_str(item.get("name"))
        if name is None:
            raise _catalog_error(source, f"{location}.name is required.")
        if not _MCP_SERVER_NAME_PATTERN.fullmatch(name):
            raise _catalog_error(
                source,
                f"{location}.name must match {_MCP_SERVER_NAME_PATTERN.pattern!r}; got {name!r}.",
            )
        if name in seen_names:
            raise _catalog_error(source, f"{location}.name duplicates {name!r}.")
        seen_names.add(name)
        transport = optional_str(item.get("transport"))
        if transport not in _MCP_TRANSPORTS:
            allowed = ", ".join(sorted(_MCP_TRANSPORTS))
            raise _catalog_error(source, f"{location}.transport must be one of: {allowed}.")
        command = optional_str(item.get("command"))
        url = optional_str(item.get("url"))
        if transport == "stdio" and command is None:
            raise _catalog_error(source, f"{location}.command is required for stdio transport.")
        if transport == "streamable_http" and url is None:
            raise _catalog_error(
                source, f"{location}.url is required for streamable_http transport."
            )
        timeout_raw = item.get("timeout_seconds", 60.0)
        try:
            timeout_seconds = float(timeout_raw)
        except (TypeError, ValueError) as exc:
            raise _catalog_error(source, f"{location}.timeout_seconds must be a number.") from exc
        if not timeout_seconds > 0 or timeout_seconds == float("inf"):
            raise _catalog_error(source, f"{location}.timeout_seconds must be finite and positive.")
        raw_allowed_tools = item.get("allowed_tools")
        if raw_allowed_tools is not None and (
            not isinstance(raw_allowed_tools, list)
            or not all(isinstance(tool, str) for tool in raw_allowed_tools)
        ):
            raise _catalog_error(source, f"{location}.allowed_tools must be an array of strings.")
        servers.append(
            MCPServerConfig(
                name=name,
                transport=transport,
                command=command,
                args=_split_listish(item.get("args")),
                env=_load_string_mapping(
                    item.get("env"), source=source, location=location, error=_catalog_error
                ),
                env_from=_load_string_mapping(
                    item.get("env_from"),
                    source=source,
                    location=location,
                    error=_catalog_error,
                ),
                url=url,
                headers_from_env=_load_string_mapping(
                    item.get("headers_from_env"),
                    source=source,
                    location=location,
                    error=_catalog_error,
                ),
                enabled=_tool_enabled(item.get("enabled"), True),
                allowed_tools=tuple(dict.fromkeys(_split_listish(item.get("allowed_tools")))),
                requires_approval=_tool_enabled(item.get("requires_approval"), True),
                timeout_seconds=timeout_seconds,
            )
        )
    return tuple(servers)
