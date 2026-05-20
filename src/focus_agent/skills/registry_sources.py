from __future__ import annotations

from pathlib import Path

from ..config import Settings
from .models import SkillDefinition, SkillSearchResult, SkillSourceDefinition
from .registry_paths import _normalize_skill_id, bundled_skills_dir


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _search_result_from_skill(
    skill: SkillDefinition,
    *,
    score: float,
    installed: bool,
) -> SkillSearchResult:
    return SkillSearchResult(
        skill_id=skill.skill_id,
        description=skill.description,
        source_id=skill.source_id,
        source_type=skill.source_type,
        path=str(skill.path),
        installed=installed,
        trust_level=skill.trust_level,
        version=skill.version,
        provenance=skill.provenance,
        checksum=skill.checksum,
        recommended_tools=skill.recommended_tools,
        capability_requirements=skill.capability_requirements,
        score=round(float(score), 4),
        rationale="Installed semantic/local match."
        if installed
        else "External local source match.",
    )


def _source_definitions_from_settings(settings: Settings) -> tuple[SkillSourceDefinition, ...]:
    enabled_sources = {
        str(source).strip().lower()
        for source in getattr(settings, "skill_sources_enabled", ("installed",)) or ()
        if str(source).strip()
    }
    trusted_sources = {
        str(source).strip().lower()
        for source in getattr(
            settings, "skill_trusted_sources", ("installed", "project", "builtin")
        )
        or ()
        if str(source).strip()
    }
    sources = [
        SkillSourceDefinition(
            source_id="project",
            source_type="local",
            label="Project skills",
            enabled="project" in enabled_sources or "installed" in enabled_sources,
            trusted=True,
            location=str(Path(getattr(settings, "skill_install_directory", ".focus_agent/skills"))),
        ),
        SkillSourceDefinition(
            source_id="builtin",
            source_type="builtin",
            label="Bundled skills",
            enabled=True,
            trusted=True,
            location=str(bundled_skills_dir()),
        ),
    ]
    for raw in getattr(settings, "skill_source_locations", ()) or ():
        source = _parse_source_location(
            str(raw), trusted_sources=trusted_sources, enabled_sources=enabled_sources
        )
        if source is not None:
            sources.append(source)
    return tuple(sources)


def _parse_source_location(
    raw: str,
    *,
    trusted_sources: set[str],
    enabled_sources: set[str],
) -> SkillSourceDefinition | None:
    text = raw.strip()
    if not text:
        return None
    source_id = ""
    source_type = "local"
    location = text
    if "=" in text:
        source_id, location = [part.strip() for part in text.split("=", 1)]
    if ":" in location and not location.startswith(("/", "~", ".")):
        maybe_type, maybe_location = [part.strip() for part in location.split(":", 1)]
        if maybe_type in {"local", "git", "http", "https", "ai-skills"}:
            source_type = "http" if maybe_type == "https" else maybe_type
            location = maybe_location
    if not source_id:
        source_id = _normalize_skill_id(Path(location).name or source_type)
    source_id = source_id.strip().lower()
    return SkillSourceDefinition(
        source_id=source_id,
        source_type=source_type,
        label=source_id,
        enabled=not enabled_sources
        or source_id in enabled_sources
        or "external" in enabled_sources,
        trusted=source_id in trusted_sources,
        location=location,
    )


__all__ = [
    "_parse_source_location",
    "_path_is_relative_to",
    "_search_result_from_skill",
    "_source_definitions_from_settings",
]
