from __future__ import annotations

import hashlib
from pathlib import Path

from .models import SkillDefinition, SkillSearchResult, SkillSourceDefinition
from .registry_matching import (
    _add_weighted_tokens,
    _cosine_score,
    _skill_semantic_vector,
)
from .registry_parsing import (
    _coerce_prompt_mode,
    _normalize_entrypoints,
    _normalize_list,
    _split_frontmatter,
)
from .registry_paths import _is_safe_skill_id, _normalize_skill_id, bundled_skills_dir
from .registry_sources import (
    _path_is_relative_to,
    _search_result_from_skill,
)

_SKILL_FILE_NAME = "SKILL.md"


class SkillRegistryDiscoveryMixin:
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

    def _load_skill(
        self,
        skill_path: Path,
        *,
        source: SkillSourceDefinition | None = None,
    ) -> SkillDefinition | None:
        raw_text = skill_path.read_text(encoding="utf-8")
        frontmatter, body = _split_frontmatter(raw_text)
        skill_id = str(frontmatter.get("name") or skill_path.parent.name).strip()
        description = str(frontmatter.get("description") or "").strip()
        if not skill_id or not description or not _is_safe_skill_id(skill_id):
            return None
        resolved_source = source or self._source_for_path(skill_path)
        return SkillDefinition(
            skill_id=_normalize_skill_id(skill_id),
            description=description,
            path=skill_path,
            body=body,
            raw_text=raw_text,
            triggers=_normalize_list(frontmatter.get("triggers")),
            aliases=_normalize_list(frontmatter.get("aliases")),
            localized_triggers=_normalize_list(frontmatter.get("localized_triggers")),
            domains=_normalize_list(frontmatter.get("domains")),
            intents=_normalize_list(frontmatter.get("intents")),
            when_to_use=_normalize_list(frontmatter.get("when_to_use")),
            primary_tools=_normalize_list(frontmatter.get("primary_tools")),
            recommended_tools=_normalize_list(frontmatter.get("recommended_tools")),
            prompt_mode=_coerce_prompt_mode(frontmatter.get("prompt_mode")),
            source_id=resolved_source.source_id,
            source_type=resolved_source.source_type,
            version=str(frontmatter.get("version") or "").strip() or None,
            trust_level="trusted" if resolved_source.trusted else "untrusted",
            install_state="installed",
            provenance=str(frontmatter.get("provenance") or "").strip() or resolved_source.location,
            checksum=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
            capability_requirements=_normalize_list(frontmatter.get("capability_requirements")),
            entrypoints=_normalize_entrypoints(frontmatter.get("entrypoints")),
        )

    def _source_for_path(self, skill_path: Path) -> SkillSourceDefinition:
        bundled = bundled_skills_dir().resolve()
        resolved = skill_path.resolve()
        if _path_is_relative_to(resolved, bundled):
            return SkillSourceDefinition(
                source_id="builtin",
                source_type="builtin",
                label="Bundled skills",
                enabled=True,
                trusted=True,
                location=str(bundled),
            )
        return SkillSourceDefinition(
            source_id="project",
            source_type="local",
            label="Project skills",
            enabled=True,
            trusted=True,
            location=str(self._skill_dirs[0]) if self._skill_dirs else None,
        )

    def _source_by_id(self, source_id: str) -> SkillSourceDefinition | None:
        normalized = str(source_id or "installed").strip().lower()
        for source in self._source_definitions:
            if source.source_id == normalized:
                return source
        return None

    def _search_local_sources(
        self,
        query: str,
        *,
        source_filter: set[str],
        limit: int,
    ) -> list[SkillSearchResult]:
        results: list[SkillSearchResult] = []
        query_vector: dict[str, float] = {}
        _add_weighted_tokens(query_vector, query, 1.0)
        for source in self._source_definitions:
            if not source.enabled or source.source_type != "local" or not source.location:
                continue
            if source.source_id in {"project", "installed"}:
                continue
            if source_filter and source.source_id not in source_filter:
                continue
            root = Path(source.location).expanduser().resolve()
            if not root.exists():
                continue
            for skill_path in sorted(root.rglob(_SKILL_FILE_NAME)):
                if any(part.startswith(".") for part in skill_path.relative_to(root).parts):
                    continue
                skill = self._load_skill(skill_path, source=source)
                if skill is None or self.resolve(skill.skill_id) is not None:
                    continue
                score = 1.0
                if query.strip():
                    score = round(_cosine_score(query_vector, _skill_semantic_vector(skill)), 4)
                    haystack = (
                        f"{skill.skill_id} {skill.description} {' '.join(skill.aliases)} "
                        f"{' '.join(skill.localized_triggers)} {' '.join(skill.domains)} "
                        f"{' '.join(skill.intents)} {' '.join(skill.when_to_use)} "
                        f"{' '.join(skill.primary_tools)} "
                        f"{' '.join(skill.capability_requirements)}"
                    ).lower()
                    if score <= 0 and query.lower() in haystack:
                        score = 0.1
                if query.strip() and score <= 0:
                    continue
                results.append(_search_result_from_skill(skill, score=score, installed=False))
                if len(results) >= limit:
                    return results
        return results

    def _load_external_skill_from_root(
        self,
        root: Path,
        skill_id: str,
        *,
        source: SkillSourceDefinition,
    ) -> SkillDefinition | None:
        for skill_path in sorted(root.rglob(_SKILL_FILE_NAME)):
            if any(part.startswith(".") for part in skill_path.relative_to(root).parts):
                continue
            skill = self._load_skill(skill_path, source=source)
            if skill is not None and skill.skill_id == skill_id:
                return skill
        return None


__all__ = ["SkillRegistryDiscoveryMixin"]
