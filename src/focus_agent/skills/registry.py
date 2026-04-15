from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ..config import Settings
from ..core.types import PromptMode
from .models import SkillDefinition, SkillSelection

_SKILL_FILE_NAME = "SKILL.md"


def bundled_skills_dir() -> Path:
    return Path(__file__).resolve().parent / "builtin"


def _normalize_skill_id(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _normalize_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _parse_scalar(value: str) -> Any:
    stripped = value.strip()
    if not stripped:
        return ""
    if stripped.startswith("[") and stripped.endswith("]"):
        inner = stripped[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("\"'") for item in inner.split(",") if item.strip()]
    lowered = stripped.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    return stripped.strip("\"'")


def _parse_frontmatter_block(block: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    current_list_key: str | None = None

    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list_key:
            parsed.setdefault(current_list_key, [])
            parsed[current_list_key].append(_parse_scalar(stripped[2:]))
            continue
        if ":" not in line:
            current_list_key = None
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not value:
            parsed[key] = []
            current_list_key = key
            continue
        parsed[key] = _parse_scalar(value)
        current_list_key = None

    return parsed


def _split_frontmatter(raw_text: str) -> tuple[dict[str, Any], str]:
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw_text.strip()

    for index in range(1, len(lines)):
        if lines[index].strip() != "---":
            continue
        frontmatter = "\n".join(lines[1:index])
        body = "\n".join(lines[index + 1 :]).strip()
        return _parse_frontmatter_block(frontmatter), body

    return {}, raw_text.strip()


def _coerce_prompt_mode(value: Any) -> PromptMode | None:
    if not value:
        return None
    try:
        return PromptMode(str(value).strip())
    except ValueError:
        return None


class SkillRegistry:
    def __init__(self, skill_dirs: Iterable[Path]):
        self._skill_dirs = tuple(
            path.expanduser().resolve()
            for path in skill_dirs
            if str(path).strip()
        )
        self._skills = self._discover()
        self._skills_by_id = {
            _normalize_skill_id(skill.skill_id): skill
            for skill in self._skills
        }
        self._trigger_pairs = tuple(
            sorted(
                (
                    (trigger.lower(), skill)
                    for skill in self._skills
                    for trigger in skill.triggers
                ),
                key=lambda item: len(item[0]),
                reverse=True,
            )
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "SkillRegistry":
        configured = [Path(path) for path in settings.skill_directories]
        return cls([*configured, bundled_skills_dir()])

    @property
    def skill_dirs(self) -> tuple[Path, ...]:
        return self._skill_dirs

    def all_skills(self) -> tuple[SkillDefinition, ...]:
        return self._skills

    def resolve(self, skill_id: str) -> SkillDefinition | None:
        return self._skills_by_id.get(_normalize_skill_id(skill_id))

    def select_for_message(
        self,
        message: str,
        *,
        explicit_hints: Iterable[str] = (),
    ) -> SkillSelection:
        chosen: list[SkillDefinition] = []
        seen: set[str] = set()

        for hint in explicit_hints:
            skill = self.resolve(str(hint))
            if skill is None or skill.skill_id in seen:
                continue
            seen.add(skill.skill_id)
            chosen.append(skill)

        stripped = message.strip()
        while stripped:
            lowered = stripped.lower()
            matched_skill: SkillDefinition | None = None
            matched_trigger = ""
            for trigger, skill in self._trigger_pairs:
                if not lowered.startswith(trigger):
                    continue
                matched_skill = skill
                matched_trigger = trigger
                break
            if matched_skill is None:
                break
            if matched_skill.skill_id not in seen:
                seen.add(matched_skill.skill_id)
                chosen.append(matched_skill)
            stripped = stripped[len(matched_trigger) :].lstrip()

        prompt_mode = next(
            (skill.prompt_mode for skill in reversed(chosen) if skill.prompt_mode is not None),
            None,
        )
        return SkillSelection(
            skill_ids=tuple(skill.skill_id for skill in chosen),
            stripped_message=stripped or message.strip(),
            prompt_mode=prompt_mode,
        )

    def list_skills(self) -> list[dict[str, Any]]:
        return [
            {
                "name": skill.skill_id,
                "description": skill.description,
                "triggers": list(skill.triggers),
                "when_to_use": list(skill.when_to_use),
                "prompt_mode": skill.prompt_mode.value if skill.prompt_mode else None,
                "path": str(skill.path),
            }
            for skill in self._skills
        ]

    def view_skill(self, skill_id: str) -> dict[str, Any] | None:
        skill = self.resolve(skill_id)
        if skill is None:
            return None
        return {
            "name": skill.skill_id,
            "description": skill.description,
            "triggers": list(skill.triggers),
            "when_to_use": list(skill.when_to_use),
            "prompt_mode": skill.prompt_mode.value if skill.prompt_mode else None,
            "path": str(skill.path),
            "content": skill.body,
        }

    def render_available_skills_block(self) -> str:
        if not self._skills:
            return ""

        lines = [
            "## Available skills",
            "If a user message starts with one of these prefixes, activate the matching skill for that turn.",
        ]
        for skill in self._skills:
            trigger_text = ", ".join(skill.triggers) if skill.triggers else "manual only"
            line = f"- {skill.skill_id}: {skill.description} (triggers: {trigger_text})"
            if skill.when_to_use:
                line += f" Use when: {'; '.join(skill.when_to_use)}"
            lines.append(line)
        return "\n".join(lines)

    def render_active_skills_block(self, skill_ids: Iterable[str]) -> str:
        skills = [self.resolve(skill_id) for skill_id in skill_ids]
        resolved = [skill for skill in skills if skill is not None]
        if not resolved:
            return ""

        sections = [
            "## Active skills",
            "Apply the following skill instructions for this turn in addition to the base agent rules.",
        ]
        for skill in resolved:
            sections.append(f"### {skill.skill_id}\n{skill.body}")
        return "\n\n".join(sections)

    def _discover(self) -> tuple[SkillDefinition, ...]:
        discovered: list[SkillDefinition] = []
        seen: set[str] = set()

        for root in self._skill_dirs:
            if not root.exists():
                continue
            for skill_path in sorted(root.rglob(_SKILL_FILE_NAME)):
                if any(part.startswith(".") for part in skill_path.relative_to(root).parts):
                    continue
                skill = self._load_skill(skill_path)
                if skill is None:
                    continue
                normalized = _normalize_skill_id(skill.skill_id)
                if normalized in seen:
                    continue
                seen.add(normalized)
                discovered.append(skill)

        return tuple(discovered)

    def _load_skill(self, skill_path: Path) -> SkillDefinition | None:
        raw_text = skill_path.read_text(encoding="utf-8")
        frontmatter, body = _split_frontmatter(raw_text)
        skill_id = str(frontmatter.get("name") or skill_path.parent.name).strip()
        description = str(frontmatter.get("description") or "").strip()
        if not skill_id or not description:
            return None
        return SkillDefinition(
            skill_id=_normalize_skill_id(skill_id),
            description=description,
            path=skill_path,
            body=body,
            raw_text=raw_text,
            triggers=_normalize_list(frontmatter.get("triggers")),
            when_to_use=_normalize_list(frontmatter.get("when_to_use")),
            prompt_mode=_coerce_prompt_mode(frontmatter.get("prompt_mode")),
        )


def render_skills_list_json(registry: SkillRegistry) -> str:
    return json.dumps(
        {
            "success": True,
            "skills": registry.list_skills(),
        },
        ensure_ascii=False,
    )


def render_skill_view_json(registry: SkillRegistry, *, skill_id: str) -> str:
    payload = registry.view_skill(skill_id)
    if payload is None:
        return json.dumps(
            {
                "success": False,
                "error": f"Skill '{skill_id}' not found.",
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "success": True,
            **payload,
        },
        ensure_ascii=False,
    )
