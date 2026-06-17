from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.types import PromptMode


@dataclass(frozen=True, slots=True)
class SkillEntrypoint:
    name: str
    command: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    network: bool = False
    timeout_seconds: int | None = None
    memory_mb: int | None = None
    output_dir_arg: str | None = None


@dataclass(frozen=True, slots=True)
class SkillSourceDefinition:
    source_id: str
    source_type: str = "installed"
    label: str = ""
    enabled: bool = True
    trusted: bool = True
    location: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    skill_id: str
    description: str
    path: Path
    body: str
    raw_text: str
    triggers: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    localized_triggers: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    intents: tuple[str, ...] = ()
    when_to_use: tuple[str, ...] = ()
    primary_tools: tuple[str, ...] = ()
    recommended_tools: tuple[str, ...] = ()
    prompt_mode: PromptMode | None = None
    source_id: str = "installed"
    source_type: str = "local"
    version: str | None = None
    trust_level: str = "trusted"
    install_state: str = "installed"
    provenance: str | None = None
    checksum: str | None = None
    capability_requirements: tuple[str, ...] = ()
    entrypoints: tuple[SkillEntrypoint, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillSemanticCandidate:
    skill_id: str
    score: float
    matched_terms: tuple[str, ...] = ()
    auto_activate: bool = False
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class SkillSelection:
    skill_ids: tuple[str, ...] = ()
    stripped_message: str = ""
    prompt_mode: PromptMode | None = None
    selection_source: str = "none"
    matched_triggers: tuple[str, ...] = ()
    semantic_candidates: tuple[SkillSemanticCandidate, ...] = ()
    confidence: float = 0.0
    rationale: str = ""
    resolution_events: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class SkillSearchResult:
    skill_id: str
    description: str = ""
    source_id: str = "installed"
    source_type: str = "local"
    path: str | None = None
    installed: bool = True
    trust_level: str = "trusted"
    version: str | None = None
    provenance: str | None = None
    checksum: str | None = None
    recommended_tools: tuple[str, ...] = ()
    primary_tools: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    intents: tuple[str, ...] = ()
    capability_requirements: tuple[str, ...] = ()
    score: float = 0.0
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class SkillInstallResult:
    success: bool
    skill_id: str
    source_id: str = "installed"
    installed: bool = False
    installed_path: str | None = None
    requires_review: bool = False
    error: str | None = None
    metadata: dict[str, object] | None = None
