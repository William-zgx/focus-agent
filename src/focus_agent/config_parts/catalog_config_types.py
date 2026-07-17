"""Dataclass entries used by model and tool catalogs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    id: str
    label: str | None = None
    backend_provider: str | None = None
    aliases: tuple[str, ...] = ()
    logo_slug: str | None = None
    logo_letter: str | None = None
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
    description: str = (
        "Write a text artifact to disk and return its location. "
        "After saving, always surface the artifact id/path in the user-facing reply "
        "so the deliverable is visible without digging through tool logs."
    )


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
class ArtifactSearchToolConfig:
    enabled: bool = True
    label: str = "Artifact Search"
    description: str = "Search saved text artifact chunks."
    default_limit: int = 5
    max_limit: int = 20


@dataclass(frozen=True, slots=True)
class ListFilesToolConfig:
    enabled: bool = True
    label: str = "List Files"
    description: str = "List workspace files under a directory using a glob-like pattern."
    default_max_results: int = 200
    max_results_cap: int = 500


@dataclass(frozen=True, slots=True)
class WorkspaceTreeToolConfig:
    enabled: bool = True
    label: str = "Workspace Tree"
    description: str = (
        "Print a directory as an indented tree up to a maximum depth. "
        "Common noise directories are skipped. Prefer this to understand layout "
        "before reading individual files."
    )
    default_max_depth: int = 5
    max_depth_cap: int = 12
    default_max_entries: int = 400
    max_entries_cap: int = 1000


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
class WorkspaceSearchToolConfig:
    enabled: bool = True
    label: str = "Workspace Search"
    description: str = "Search workspace code and docs using the semantic retrieval index."
    default_limit: int = 5
    max_limit: int = 20


@dataclass(frozen=True, slots=True)
class CodebaseStatsToolConfig:
    enabled: bool = True
    label: str = "Codebase Stats"
    description: str = "Summarize file counts and line counts for the current workspace."
    default_max_files: int = 5000
    max_files_cap: int = 10000


@dataclass(frozen=True, slots=True)
class ApplyPatchToolConfig:
    enabled: bool = True
    label: str = "Apply Patch"
    description: str = "Apply a unified diff to text files under the workspace root."
    max_patch_bytes: int = 200000


@dataclass(frozen=True, slots=True)
class RunWorkspaceCommandToolConfig:
    enabled: bool = True
    label: str = "Run Workspace Command"
    description: str = (
        "Run an allowlisted test, lint, build, check, or trusted local skill script command "
        "in the workspace."
    )
    allowed_commands: tuple[str, ...] = (
        "cargo",
        "go",
        "make",
        "mypy",
        "npm",
        "pnpm",
        "pytest",
        "ruff",
        "uv",
    )
    default_timeout_seconds: int = 60
    max_timeout_seconds: int = 300
    max_output_chars: int = 20000


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
    blocked_domains: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = ()


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
class AskUserQuestionToolConfig:
    enabled: bool = True
    label: str = "Ask User Question"
    description: str = (
        "Collect structured multiple-choice answers from the user when blocked on a "
        "genuine product or preference decision. Pauses the run until the user replies. "
        "Always includes an Other option for free text. Prefer this over guessing."
    )


@dataclass(frozen=True, slots=True)
class SkillsListToolConfig:
    enabled: bool = True
    label: str = "Skills List"
    description: str = (
        "List bundled and local skills with short descriptions and trigger prefixes. "
        "Use this as a catalog; call skill_view to load full workflow instructions."
    )


@dataclass(frozen=True, slots=True)
class SkillViewToolConfig:
    enabled: bool = True
    label: str = "Skill View"
    description: str = (
        "Load the full instructions for a named skill (progressive skill loading). "
        "When the user task matches an available skill, call this before following "
        "that workflow instead of guessing from the short catalog blurb alone."
    )


@dataclass(frozen=True, slots=True)
class SkillSourcesToolConfig:
    enabled: bool = True
    label: str = "Skill Sources"
    description: str = "List configured skill sources and trust metadata."


@dataclass(frozen=True, slots=True)
class SkillsSearchToolConfig:
    enabled: bool = True
    label: str = "Skills Search"
    description: str = "Search installed and configured skill sources for relevant capabilities."
    default_limit: int = 5
    max_limit_cap: int = 20


@dataclass(frozen=True, slots=True)
class SkillInstallToolConfig:
    enabled: bool = True
    label: str = "Skill Install"
    description: str = (
        "Install a trusted local skill, or return a review-required result for external sources."
    )


@dataclass(frozen=True, slots=True)
class SkillsRefreshIndexToolConfig:
    enabled: bool = True
    label: str = "Skills Refresh Index"
    description: str = "Refresh the runtime skill index after project or source changes."


@dataclass(frozen=True, slots=True)
class ProductivityToolConfig:
    enabled: bool = True
    label: str = "Productivity"
    description: str = "Create, search, and update personal notes or tasks."


@dataclass(frozen=True, slots=True)
class ToolProviderConfig:
    id: str
    enabled: bool = True
    order: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    overrides: tuple[str, ...] = ()
