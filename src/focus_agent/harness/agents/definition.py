"""Declarative agent persona/role definitions.

Inspired by opencode's markdown agent definitions and pi's subagent markdown
files, :class:`AgentDefinition` provides a declarative, serializable model for
describing agent personas -- their system prompts, tool access policies, model
overrides, and UI metadata. Definitions can be authored inline in Python or
loaded from Markdown files with YAML frontmatter, enabling users to drop new
agent personas into a directory without writing code.

The built-in definitions mirror the existing :class:`AgentRole` enum in
:mod:`focus_agent.delegation.roles` so that role-routing and declarative
definitions share a single source of truth for tool governance.
"""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# YAML frontmatter parsing
# ---------------------------------------------------------------------------
# PyYAML is not a declared dependency in pyproject.toml, but it is frequently
# available as a transitive dep (e.g. via langchain). We attempt to import it
# and fall back to a small regex-based parser that handles the common scalar
# and list cases used in agent markdown files.
try:  # pragma: no cover - import probe
    import yaml as _yaml  # type: ignore[import-not-found]

    _HAS_YAML = True
except Exception:  # pragma: no cover - fallback path
    _yaml = None  # type: ignore[assignment]
    _HAS_YAML = False


_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n?(.*)$",
    re.DOTALL,
)


def _parse_scalar(raw: str) -> Any:
    """Parse a bare scalar value from the regex frontmatter fallback."""
    value = raw.strip()
    if not value:
        return ""
    # Quoted strings.
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    # Booleans.
    lowered = value.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if lowered in ("null", "none", "~"):
        return None
    # Numbers.
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        pass
    return value


def _parse_inline_list(raw: str) -> list[Any]:
    """Parse an inline YAML-style list like ``["a", "b", 1]``."""
    inner = raw.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1].strip()
    if not inner:
        return []
    items: list[Any] = []
    for part in _split_top_level(inner, ","):
        part = part.strip()
        if part:
            items.append(_parse_scalar(part))
    return items


def _split_top_level(text: str, sep: str) -> list[str]:
    """Split *text* on *sep* respecting bracket/quote nesting."""
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    buf: list[str] = []
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            buf.append(ch)
            continue
        if ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _parse_frontmatter_fallback(frontmatter: str) -> dict[str, Any]:
    """Minimal regex/YAML-subset parser used when PyYAML is unavailable."""
    data: dict[str, Any] = {}
    current_list_key: str | None = None
    current_list: list[Any] = []
    for raw_line in frontmatter.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # List continuation: "  - item"
        list_marker = line.lstrip()
        if (
            list_marker.startswith("-")
            and current_list_key is not None
            and (line.startswith("-") or line.startswith("  -") or line.startswith("\t-"))
        ):
            item = list_marker[1:].strip()
            current_list.append(_parse_scalar(item))
            continue
        # Flush any in-progress list.
        if current_list_key is not None:
            data[current_list_key] = current_list
            current_list_key = None
            current_list = []
        # Key: value line.
        if ":" not in line:
            continue
        key, _, value_part = line.partition(":")
        key = key.strip()
        value_part = value_part.strip()
        if not key:
            continue
        if not value_part:
            # Could be the start of a block list.
            current_list_key = key
            current_list = []
            continue
        if value_part.startswith("["):
            data[key] = _parse_inline_list(value_part)
        else:
            data[key] = _parse_scalar(value_part)
    if current_list_key is not None:
        data[current_list_key] = current_list
    return data


def parse_markdown_agent(text: str) -> tuple[dict[str, Any], str]:
    """Parse markdown text into ``(frontmatter_dict, body_system_prompt)``.

    If no frontmatter is present the frontmatter dict will be empty and the
    entire text is treated as the system prompt body.
    """
    match = _FRONTMATTER_RE.match(text.lstrip("\n"))
    if not match:
        return {}, text.strip()
    frontmatter_raw, body = match.group(1), match.group(2)
    if _HAS_YAML:
        try:
            data = _yaml.safe_load(frontmatter_raw) or {}
            if not isinstance(data, dict):
                logger.warning("Agent markdown frontmatter is not a mapping; ignoring.")
                data = {}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to parse YAML frontmatter, falling back to regex: %s", exc)
            data = _parse_frontmatter_fallback(frontmatter_raw)
    else:
        data = _parse_frontmatter_fallback(frontmatter_raw)
    return data, body.strip()


# ---------------------------------------------------------------------------
# Tool policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    """Glob-pattern based allow/deny policy for tool names.

    Patterns follow :mod:`fnmatch` syntax -- e.g. ``"bash:*"``, ``"read_*"``,
    ``"artifact_*"``. Evaluation order:

    1. If the tool name matches any ``denied_patterns`` -> denied.
    2. Else if the tool name matches any ``allowed_patterns`` -> allowed.
    3. Else if ``allowed_patterns == ["*"]`` -> allowed (default allow-all).
    4. Else -> denied.
    """

    allowed_patterns: list[str] = field(default_factory=lambda: ["*"])
    denied_patterns: list[str] = field(default_factory=list)

    def is_allowed(self, tool_name: str) -> bool:
        """Return True if *tool_name* is permitted by this policy."""
        name = str(tool_name)
        for pattern in self.denied_patterns:
            if fnmatch.fnmatch(name, pattern):
                return False
        for pattern in self.allowed_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
        if self.allowed_patterns == ["*"]:
            return True
        return False

    def filter(self, tool_names: list[str]) -> list[str]:
        """Return the subset of *tool_names* permitted by this policy."""
        return [name for name in tool_names if self.is_allowed(name)]


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------


_VALID_MODES = ("primary", "subagent", "all")


@dataclass(slots=True)
class AgentDefinition:
    """Declarative description of an agent persona/role.

    Inspired by opencode's markdown agent definitions and pi's subagent
    markdown files. An :class:`AgentDefinition` carries everything the harness
    needs to instantiate an agent: its identifier, routing description, model
    override, system prompt, tool policy, sampling parameters, and UI hints.
    """

    name: str
    """Unique identifier, e.g. ``"planner"``, ``"code-reviewer"``."""

    description: str
    """Short description used for LLM routing and ``@mention`` autocomplete."""

    model: str | None = None
    """Optional model override; ``None`` means inherit the default model."""

    system_prompt: str = ""
    """System prompt (markdown body when loaded from a file)."""

    mode: Literal["primary", "subagent", "all"] = "all"
    """Where this agent can run: as a primary turn agent, a subagent, or both."""

    tools_allowed: list[str] = field(default_factory=lambda: ["*"])
    """Glob patterns for tools this agent is permitted to call."""

    tools_denied: list[str] = field(default_factory=list)
    """Glob patterns for tools this agent must never call."""

    temperature: float = 0.0
    """Sampling temperature."""

    max_steps: int = 50
    """Maximum number of LLM/tool steps per run."""

    hidden: bool = False
    """If True the agent is a hidden system agent (excluded from UIs, ``@mentions``)."""

    color: str | None = None
    """Optional UI display color (hex string or CSS color name)."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Free-form extension metadata for providers/UI layers."""

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("AgentDefinition.name must be a non-empty string")
        if self.mode not in _VALID_MODES:
            raise ValueError(
                f"AgentDefinition.mode must be one of {_VALID_MODES}, got {self.mode!r}"
            )
        self.name = self.name.strip()
        self.description = self.description.strip()

    @property
    def tool_policy(self) -> ToolPolicy:
        """A :class:`ToolPolicy` compiled from this definition's patterns."""
        return ToolPolicy(
            allowed_patterns=list(self.tools_allowed),
            denied_patterns=list(self.tools_denied),
        )

    @classmethod
    def from_markdown(cls, text: str, *, defaults: dict[str, Any] | None = None) -> AgentDefinition:
        """Parse *text* (markdown with optional YAML frontmatter) into a definition.

        *defaults* supplies fallback values for any frontmatter keys not
        present in the file.
        """
        data, body = parse_markdown_agent(text)
        merged: dict[str, Any] = dict(defaults or {})
        merged.update(data)
        # The markdown body is always the system prompt unless explicitly overridden
        # via a "system_prompt" key in the frontmatter (rare, but supported).
        if "system_prompt" not in data and body:
            merged["system_prompt"] = body
        return cls(**_coerce_definition_fields(merged))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class AgentDefinitionRegistry:
    """Registry of :class:`AgentDefinition` instances keyed by name."""

    def __init__(self, definitions: list[AgentDefinition] | None = None) -> None:
        self._defs: dict[str, AgentDefinition] = {}
        for d in definitions or ():
            self.register(d)

    def register(self, definition: AgentDefinition) -> None:
        """Register *definition*, overwriting any previous entry with the same name."""
        if not isinstance(definition, AgentDefinition):
            raise TypeError(f"Expected AgentDefinition, got {type(definition).__name__}")
        self._defs[definition.name] = definition

    def get(self, name: str) -> AgentDefinition | None:
        """Return the definition registered under *name*, or ``None``."""
        return self._defs.get(str(name))

    def list_visible(self) -> list[AgentDefinition]:
        """Return all non-hidden definitions in insertion order."""
        return [d for d in self._defs.values() if not d.hidden]

    def list_all(self) -> list[AgentDefinition]:
        """Return every registered definition (including hidden ones)."""
        return list(self._defs.values())

    def names(self) -> list[str]:
        """Return the names of all registered definitions in insertion order."""
        return list(self._defs.keys())

    def __len__(self) -> int:
        return len(self._defs)

    def __contains__(self, name: str) -> bool:
        return str(name) in self._defs

    def __iter__(self):
        return iter(self._defs.values())

    # ---- Markdown loading -------------------------------------------------

    @classmethod
    def from_markdown_file(cls, path: str) -> AgentDefinition:
        """Load a single :class:`AgentDefinition` from a markdown *path*."""
        text = Path(path).read_text(encoding="utf-8")
        return AgentDefinition.from_markdown(text, defaults={"name": Path(path).stem})

    @classmethod
    def from_markdown_dir(cls, dir_path: str) -> list[AgentDefinition]:
        """Load all ``*.md`` files directly under *dir_path* as definitions.

        Files that fail to parse are logged and skipped.
        """
        root = Path(dir_path)
        defs: list[AgentDefinition] = []
        if not root.is_dir():
            logger.warning("Agent markdown directory not found: %s", dir_path)
            return defs
        for md in sorted(root.glob("*.md")):
            try:
                defs.append(cls.from_markdown_file(str(md)))
            except Exception as exc:
                logger.warning("Skipping agent markdown %s: %s", md, exc)
        return defs


def _coerce_definition_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Coerce raw frontmatter/dict values into the types AgentDefinition expects."""
    field_map: dict[str, Any] = {
        "name": str,
        "description": str,
        "model": lambda v: None if v in (None, "", "null") else str(v),
        "system_prompt": str,
        "mode": lambda v: str(v) if v in _VALID_MODES else "all",
        "tools_allowed": lambda v: _as_string_list(v, default=["*"]),
        "tools_denied": lambda v: _as_string_list(v, default=[]),
        "temperature": lambda v: float(v) if v is not None else 0.0,
        "max_steps": lambda v: int(v) if v is not None else 50,
        "hidden": lambda v: bool(v) if v is not None else False,
        "color": lambda v: None if v in (None, "", "null") else str(v),
        "metadata": lambda v: dict(v) if isinstance(v, dict) else {},
    }
    out: dict[str, Any] = {}
    for key, coercer in field_map.items():
        if key in data:
            out[key] = coercer(data[key])
        # Let dataclass defaults handle missing keys.
    # Preserve unknown keys inside metadata so nothing is silently dropped.
    if "metadata" not in out:
        out["metadata"] = {}
    for key, value in data.items():
        if key not in field_map:
            out["metadata"][key] = value
    return out


def _as_string_list(value: Any, *, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return list(default)


# ---------------------------------------------------------------------------
# Built-in agent definitions
# ---------------------------------------------------------------------------
# These mirror the tool-governance allowlists in
# ``focus_agent.delegation.roles._ROLE_GOVERNANCE`` and the default tool
# metadata in :mod:`focus_agent.capabilities.tool_manifest` so that the
# declarative and routing paths agree.


def orchestrator_builtin() -> AgentDefinition:
    """Built-in orchestrator agent -- coordinates delegated role runs."""
    return AgentDefinition(
        name="orchestrator",
        description="Coordinates and dispatches work across specialist subagents.",
        mode="primary",
        tools_allowed=[
            "conversation_summary",
            "skills_list",
            "skill_view",
            "skill_sources",
            "skills_search",
        ],
        temperature=0.0,
        max_steps=25,
        hidden=True,
        color="#6B7280",
        metadata={"builtin": True, "role": "orchestrator"},
        system_prompt=(
            "You are the orchestrator. Your job is to triage the user's request, "
            "select which specialist agents should handle it, and synthesize their "
            "results into a single coherent response. Do not perform implementation "
            "work yourself; delegate to planner, executor, critic, memory_curator, "
            "or skill_scout as appropriate."
        ),
    )


def planner_builtin() -> AgentDefinition:
    """Built-in planner agent -- researches and designs solutions."""
    return AgentDefinition(
        name="planner",
        description="Researches, analyzes, and designs implementation plans.",
        mode="subagent",
        tools_allowed=[
            "web_search",
            "web_fetch",
            "current_utc_time",
            "search_code",
            "read_file",
            "list_files",
            "workspace_tree",
            "conversation_summary",
            "ask_user_question",
            "skills_list",
            "skill_view",
            "skill_sources",
            "skills_search",
            "skills_refresh_index",
        ],
        tools_denied=[],
        temperature=0.1,
        max_steps=40,
        hidden=False,
        color="#3B82F6",
        metadata={"builtin": True, "role": "planner"},
        system_prompt=(
            "You are the planner. Investigate the problem thoroughly: read the "
            "relevant code, search for existing patterns, consult documentation "
            "or the web when needed, and produce a concrete step-by-step plan. "
            "Call out risks, open questions, and success criteria. Do not modify "
            "files or run side-effecting commands -- that is the executor's job."
        ),
    )


def executor_builtin() -> AgentDefinition:
    """Built-in executor agent -- implements changes."""
    return AgentDefinition(
        name="executor",
        description="Implements code changes, runs commands, and writes artifacts.",
        mode="subagent",
        tools_allowed=[
            "list_files",
            "workspace_tree",
            "read_file",
            "search_code",
            "codebase_stats",
            "git_status",
            "git_diff",
            "apply_patch",
            "run_workspace_command",
            "run_skill_entrypoint",
            "artifact_list",
            "artifact_read",
            "artifact_update",
            "write_text_artifact",
            "ask_user_question",
        ],
        temperature=0.0,
        max_steps=75,
        hidden=False,
        color="#10B981",
        metadata={"builtin": True, "role": "executor"},
        system_prompt=(
            "You are the executor. Implement the plan precisely: make the minimum "
            "necessary changes, run verification commands, and keep the diff "
            "focused. Before reporting done, confirm the change works by running "
            "targeted tests or the affected command. Prefer reading before writing."
        ),
    )


def critic_builtin() -> AgentDefinition:
    """Built-in critic agent -- reviews work for correctness and regressions."""
    return AgentDefinition(
        name="critic",
        description="Reviews completed work for correctness, security, and regressions.",
        mode="subagent",
        tools_allowed=[
            "list_files",
            "workspace_tree",
            "read_file",
            "search_code",
            "git_status",
            "git_diff",
            "git_log",
            "artifact_list",
            "artifact_read",
        ],
        temperature=0.1,
        max_steps=30,
        hidden=False,
        color="#F59E0B",
        metadata={"builtin": True, "role": "critic"},
        system_prompt=(
            "You are the critic. Review the diff or output critically: look for "
            "bugs, security issues, edge cases, missing tests, and regressions "
            "against existing behavior. Be specific and constructive -- cite "
            "file paths and line references when flagging issues. If the work "
            "looks good, say so and explain why."
        ),
    )


def memory_curator_builtin() -> AgentDefinition:
    """Built-in memory curator agent -- governs memory promotion."""
    return AgentDefinition(
        name="memory_curator",
        description="Reviews memory candidates and promotes durable learnings safely.",
        mode="subagent",
        tools_allowed=[
            "memory_search",
            "conversation_summary",
            "artifact_list",
            "artifact_read",
        ],
        temperature=0.0,
        max_steps=20,
        hidden=True,
        color="#8B5CF6",
        metadata={"builtin": True, "role": "memory_curator"},
        system_prompt=(
            "You are the memory curator. Decide which observations from this turn "
            "are worth promoting to long-term memory, verify they do not "
            "duplicate existing memories or contain sensitive data, and phrase "
            "them as durable, reusable facts."
        ),
    )


def skill_scout_builtin() -> AgentDefinition:
    """Built-in skill scout agent -- selects relevant skills/tools."""
    return AgentDefinition(
        name="skill_scout",
        description="Selects relevant skills and toolsets for the current task.",
        mode="subagent",
        tools_allowed=[
            "skills_list",
            "skill_view",
            "skill_sources",
            "skills_search",
            "skills_refresh_index",
            "skill_install",
            "conversation_summary",
        ],
        temperature=0.0,
        max_steps=20,
        hidden=True,
        color="#EC4899",
        metadata={"builtin": True, "role": "skill_scout"},
        system_prompt=(
            "You are the skill scout. Given the user's task, search the skill "
            "index, inspect relevant skill definitions, and recommend which "
            "skills should be activated. Do not execute skills yourself -- "
            "surface them for the orchestrator or executor."
        ),
    )


_BUILTIN_FACTORIES = (
    orchestrator_builtin,
    planner_builtin,
    executor_builtin,
    critic_builtin,
    memory_curator_builtin,
    skill_scout_builtin,
)


def create_default_registry() -> AgentDefinitionRegistry:
    """Return a :class:`AgentDefinitionRegistry` pre-loaded with every built-in agent."""
    registry = AgentDefinitionRegistry()
    for factory in _BUILTIN_FACTORIES:
        registry.register(factory())
    return registry


__all__ = [
    "AgentDefinition",
    "AgentDefinitionRegistry",
    "ToolPolicy",
    "create_default_registry",
    "critic_builtin",
    "executor_builtin",
    "memory_curator_builtin",
    "orchestrator_builtin",
    "parse_markdown_agent",
    "planner_builtin",
    "skill_scout_builtin",
]
