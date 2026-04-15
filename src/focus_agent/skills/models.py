from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.types import PromptMode


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    skill_id: str
    description: str
    path: Path
    body: str
    raw_text: str
    triggers: tuple[str, ...] = ()
    when_to_use: tuple[str, ...] = ()
    prompt_mode: PromptMode | None = None


@dataclass(frozen=True, slots=True)
class SkillSelection:
    skill_ids: tuple[str, ...] = ()
    stripped_message: str = ""
    prompt_mode: PromptMode | None = None
