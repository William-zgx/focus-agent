from __future__ import annotations

import hashlib
import re
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..config import Settings
from ..retrieval import RetrievalDocument, RetrievalIndex
from .models import (
    SkillDefinition,
    SkillEntrypoint,
    SkillInstallResult,
    SkillSearchResult,
    SkillSelection,
    SkillSemanticCandidate,
    SkillSourceDefinition,
)
from .registry_matching import (
    _SEMANTIC_CANDIDATE_LIMIT,
    _add_weighted_tokens,
    _cosine_score,
    _selection_source,
    _semantic_enabled,
    _skill_semantic_vector,
)
from .registry_parsing import (
    _coerce_prompt_mode,
    _normalize_entrypoints,
    _normalize_list,
    _split_frontmatter,
)
from .registry_paths import _is_safe_skill_id, _normalize_skill_id, bundled_skills_dir
from .registry_rendering import (
    _install_result_to_dict as _install_result_to_dict,
)
from .registry_rendering import (
    _search_result_to_dict as _search_result_to_dict,
)
from .registry_rendering import (
    render_skill_install_json as render_skill_install_json,
)
from .registry_rendering import (
    render_skill_sources_json as render_skill_sources_json,
)
from .registry_rendering import (
    render_skill_view_json as render_skill_view_json,
)
from .registry_rendering import (
    render_skills_list_json as render_skills_list_json,
)
from .registry_rendering import (
    render_skills_refresh_index_json as render_skills_refresh_index_json,
)
from .registry_rendering import (
    render_skills_search_json as render_skills_search_json,
)
from .registry_sources import (
    _parse_source_location as _parse_source_location,
)
from .registry_sources import (
    _path_is_relative_to,
    _search_result_from_skill,
    _source_definitions_from_settings,
)

_SKILL_FILE_NAME = "SKILL.md"


def _entrypoint_to_dict(entrypoint: SkillEntrypoint) -> dict[str, Any]:
    return {
        "name": entrypoint.name,
        "command": list(entrypoint.command),
        "dependencies": list(entrypoint.dependencies),
        "network": entrypoint.network,
        "timeout_seconds": entrypoint.timeout_seconds,
        "memory_mb": entrypoint.memory_mb,
        "output_dir_arg": entrypoint.output_dir_arg,
    }


def _skill_retrieval_text(skill: SkillDefinition) -> str:
    parts = [
        skill.skill_id,
        skill.description,
        *skill.aliases,
        *skill.localized_triggers,
        *skill.domains,
        *skill.intents,
        *skill.when_to_use,
        *skill.primary_tools,
        *skill.recommended_tools,
        *skill.capability_requirements,
    ]
    return "\n".join(str(part).strip() for part in parts if str(part).strip())


class SkillRegistry:
    def __init__(
        self,
        skill_dirs: Iterable[Path],
        *,
        enabled: bool = True,
        disabled_skill_ids: Iterable[str] = (),
        semantic_match_enabled: bool = True,
        semantic_match_threshold: float = 0.22,
        source_definitions: Iterable[SkillSourceDefinition] = (),
        install_dir: Path | None = None,
        retrieval_index: RetrievalIndex | None = None,
        embedding_provider: Any | None = None,
    ):
        configured_skill_dirs = tuple(
            path.expanduser().resolve() for path in skill_dirs if str(path).strip()
        )
        resolved_install_dir = install_dir.expanduser().resolve() if install_dir else None
        if resolved_install_dir is not None and resolved_install_dir not in configured_skill_dirs:
            configured_skill_dirs = (*configured_skill_dirs, resolved_install_dir)
        self._skill_dirs = configured_skill_dirs
        self._enabled = bool(enabled)
        self._disabled_skill_ids = {
            _normalize_skill_id(skill_id)
            for skill_id in disabled_skill_ids
            if str(skill_id).strip()
        }
        self._semantic_match_enabled = bool(semantic_match_enabled)
        self._semantic_match_threshold = float(semantic_match_threshold)
        self._source_definitions = self._normalize_sources(source_definitions)
        self._install_dir = resolved_install_dir
        self._retrieval_index = retrieval_index
        self._embedding_provider = embedding_provider
        self._skills = self._discover()
        self._reindex()

    @staticmethod
    def _normalize_sources(
        source_definitions: Iterable[SkillSourceDefinition],
    ) -> tuple[SkillSourceDefinition, ...]:
        sources: list[SkillSourceDefinition] = [
            SkillSourceDefinition(
                source_id="installed",
                source_type="installed",
                label="Installed skills",
                enabled=True,
                trusted=True,
            )
        ]
        seen = {"installed"}
        for source in source_definitions:
            source_id = str(source.source_id or "").strip().lower()
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            sources.append(
                SkillSourceDefinition(
                    source_id=source_id,
                    source_type=str(source.source_type or "local").strip().lower(),
                    label=source.label or source_id,
                    enabled=bool(source.enabled),
                    trusted=bool(source.trusted),
                    location=source.location,
                    metadata=dict(source.metadata or {}),
                )
            )
        return tuple(sources)

    def _reindex(self) -> None:
        self._skills_by_id = {_normalize_skill_id(skill.skill_id): skill for skill in self._skills}
        self._semantic_vectors = {
            skill.skill_id: _skill_semantic_vector(skill) for skill in self._skills
        }
        self._trigger_pairs = tuple(
            sorted(
                (
                    (trigger.lower(), skill)
                    for skill in self._active_skills()
                    for trigger in (*skill.triggers, *skill.localized_triggers)
                ),
                key=lambda item: len(item[0]),
                reverse=True,
            )
        )
        self._index_skills_best_effort()

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        retrieval_index: RetrievalIndex | None = None,
        embedding_provider: Any | None = None,
    ) -> SkillRegistry:
        configured = [Path(path) for path in settings.skill_directories]
        source_definitions = _source_definitions_from_settings(settings)
        return cls(
            [*configured, bundled_skills_dir()],
            enabled=bool(getattr(settings, "skills_enabled", True)),
            disabled_skill_ids=getattr(settings, "skill_disabled_ids", ()),
            semantic_match_enabled=_semantic_enabled(
                getattr(settings, "skill_semantic_match_enabled", True)
            ),
            semantic_match_threshold=float(
                getattr(settings, "skill_semantic_match_threshold", 0.22)
            ),
            source_definitions=source_definitions,
            install_dir=Path(
                getattr(settings, "skill_install_directory", ".focus_agent/skills")
                or ".focus_agent/skills"
            ),
            retrieval_index=retrieval_index,
            embedding_provider=embedding_provider,
        )

    @property
    def skill_dirs(self) -> tuple[Path, ...]:
        return self._skill_dirs

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def install_dir(self) -> Path | None:
        return self._install_dir

    def disabled_skill_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._disabled_skill_ids))

    def set_disabled_skill_ids(self, disabled_skill_ids: Iterable[str]) -> None:
        self._disabled_skill_ids = {
            _normalize_skill_id(skill_id)
            for skill_id in disabled_skill_ids
            if str(skill_id).strip()
        }
        self._reindex()

    def is_skill_enabled(self, skill_id: str) -> bool:
        return self._enabled and _normalize_skill_id(skill_id) not in self._disabled_skill_ids

    def _active_skills(self) -> tuple[SkillDefinition, ...]:
        if not self._enabled:
            return ()
        return tuple(skill for skill in self._skills if self.is_skill_enabled(skill.skill_id))

    def all_skills(self) -> tuple[SkillDefinition, ...]:
        return self._skills

    def list_sources(self) -> list[dict[str, Any]]:
        return [
            {
                "source_id": source.source_id,
                "source_type": source.source_type,
                "label": source.label or source.source_id,
                "enabled": source.enabled,
                "trusted": source.trusted,
                "location": source.location,
                "metadata": dict(source.metadata or {}),
            }
            for source in self._source_definitions
        ]

    def resolve(self, skill_id: str) -> SkillDefinition | None:
        return self._skills_by_id.get(_normalize_skill_id(skill_id))

    def search_skills(
        self,
        query: str,
        *,
        scope: str = "installed",
        sources: Iterable[str] = (),
        limit: int = 5,
    ) -> tuple[SkillSearchResult, ...]:
        if not self._enabled:
            return ()
        source_filter = {_normalize_skill_id(source) for source in sources if str(source).strip()}
        include_installed = scope in {"", "installed", "all"} or "installed" in source_filter
        results: list[SkillSearchResult] = []
        if include_installed:
            results.extend(self._search_installed(query, source_filter=source_filter, limit=limit))
        if scope in {"external", "all"}:
            results.extend(
                self._search_local_sources(query, source_filter=source_filter, limit=limit)
            )
        results.sort(key=lambda item: (-item.score, item.source_id, item.skill_id))
        return tuple(results[: max(0, int(limit or 0))])

    def install_skill(
        self,
        skill_id: str,
        *,
        source_id: str = "installed",
        version: str | None = None,
        mode: str = "project",
    ) -> SkillInstallResult:
        del version
        normalized_skill_id = _normalize_skill_id(skill_id)
        if not self._enabled:
            return SkillInstallResult(
                success=False,
                skill_id=normalized_skill_id,
                source_id=source_id or "installed",
                error="Skill registry is disabled.",
            )
        if not _is_safe_skill_id(normalized_skill_id):
            return SkillInstallResult(
                success=False,
                skill_id=normalized_skill_id,
                source_id=source_id or "installed",
                error="Skill id must be a simple skill name without path separators.",
            )
        installed = self.resolve(normalized_skill_id)
        if installed is not None:
            return SkillInstallResult(
                success=True,
                skill_id=installed.skill_id,
                source_id=installed.source_id,
                installed=True,
                installed_path=str(installed.path),
                metadata={"already_installed": True},
            )

        source = self._source_by_id(source_id)
        if source is None:
            return SkillInstallResult(
                success=False,
                skill_id=normalized_skill_id,
                source_id=source_id or "installed",
                error=f"Skill source '{source_id}' not found.",
            )
        if source.source_type != "local" or not source.location or not source.trusted:
            return SkillInstallResult(
                success=False,
                skill_id=normalized_skill_id,
                source_id=source.source_id,
                requires_review=True,
                error="Only trusted local skill sources can be installed by this runtime.",
                metadata={
                    "source_type": source.source_type,
                    "trusted": source.trusted,
                    "mode": mode,
                },
            )

        source_root = Path(source.location).expanduser().resolve()
        candidate = self._load_external_skill_from_root(
            source_root,
            normalized_skill_id,
            source=source,
        )
        if candidate is None:
            return SkillInstallResult(
                success=False,
                skill_id=normalized_skill_id,
                source_id=source.source_id,
                error=f"Skill '{normalized_skill_id}' not found in source '{source.source_id}'.",
            )
        install_root = self._install_dir or (self._skill_dirs[0] if self._skill_dirs else None)
        if install_root is None:
            return SkillInstallResult(
                success=False,
                skill_id=normalized_skill_id,
                source_id=source.source_id,
                error="No skill install directory is configured.",
            )
        target_dir = install_root / candidate.skill_id
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / _SKILL_FILE_NAME
        shutil.copytree(candidate.path.parent, target_dir, dirs_exist_ok=True)
        self.refresh_index()
        installed_after_copy = self.resolve(candidate.skill_id)
        return SkillInstallResult(
            success=installed_after_copy is not None,
            skill_id=candidate.skill_id,
            source_id=source.source_id,
            installed=installed_after_copy is not None,
            installed_path=str(target_path),
            metadata={"mode": mode},
        )

    def refresh_index(self, *, sources: Iterable[str] = ()) -> dict[str, Any]:
        del sources
        before = len(self._skills)
        self._skills = self._discover()
        self._reindex()
        return {
            "success": True,
            "enabled": self._enabled,
            "previous_count": before,
            "count": len(self._skills),
            "sources": self.list_sources(),
        }

    def reload_from_settings(self, settings: Settings) -> dict[str, Any]:
        before = len(self._skills)
        updated = type(self).from_settings(
            settings,
            retrieval_index=self._retrieval_index,
            embedding_provider=self._embedding_provider,
        )
        self._skill_dirs = updated._skill_dirs
        self._enabled = updated._enabled
        self._disabled_skill_ids = updated._disabled_skill_ids
        self._semantic_match_enabled = updated._semantic_match_enabled
        self._semantic_match_threshold = updated._semantic_match_threshold
        self._source_definitions = updated._source_definitions
        self._install_dir = updated._install_dir
        self._retrieval_index = updated._retrieval_index
        self._embedding_provider = updated._embedding_provider
        self._skills = updated._skills
        self._reindex()
        return {
            "success": True,
            "enabled": self._enabled,
            "previous_count": before,
            "count": len(self._skills),
            "sources": self.list_sources(),
        }

    def select_for_message(
        self,
        message: str,
        *,
        explicit_hints: Iterable[str] = (),
        semantic_match_enabled: bool | None = None,
        semantic_match_threshold: float | None = None,
    ) -> SkillSelection:
        chosen: list[SkillDefinition] = []
        seen: set[str] = set()
        explicit_matched = False

        resolved_explicit_hints = (
            *tuple(str(item) for item in explicit_hints),
            *self.explicit_hints_for_message(message),
        )
        for hint in resolved_explicit_hints:
            skill = self.resolve(str(hint))
            if skill is None or not self.is_skill_enabled(skill.skill_id) or skill.skill_id in seen:
                continue
            seen.add(skill.skill_id)
            chosen.append(skill)
            explicit_matched = True

        stripped = message.strip()
        matched_triggers: list[str] = []
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
            matched_triggers.append(matched_trigger)
            if matched_skill.skill_id not in seen:
                seen.add(matched_skill.skill_id)
                chosen.append(matched_skill)
            stripped = stripped[len(matched_trigger) :].lstrip()

        threshold = (
            self._semantic_match_threshold
            if semantic_match_threshold is None
            else float(semantic_match_threshold)
        )
        semantic_enabled = (
            self._semantic_match_enabled
            if semantic_match_enabled is None
            else bool(semantic_match_enabled)
        )
        semantic_candidates = (
            self.semantic_candidates_for_message(
                stripped or message.strip(),
                threshold=threshold,
                limit=_SEMANTIC_CANDIDATE_LIMIT,
            )
            if semantic_enabled
            else ()
        )
        semantic_matched = False
        if semantic_enabled and not chosen and semantic_candidates:
            top_candidate = semantic_candidates[0]
            if top_candidate.score >= threshold:
                skill = self.resolve(top_candidate.skill_id)
                if skill is not None:
                    chosen.append(skill)
                    seen.add(skill.skill_id)
                    semantic_matched = True
                    semantic_candidates = (
                        SkillSemanticCandidate(
                            skill_id=top_candidate.skill_id,
                            score=top_candidate.score,
                            matched_terms=top_candidate.matched_terms,
                            auto_activate=True,
                            rationale=top_candidate.rationale,
                        ),
                        *semantic_candidates[1:],
                    )
        elif chosen and semantic_candidates:
            semantic_candidates = tuple(
                SkillSemanticCandidate(
                    skill_id=candidate.skill_id,
                    score=candidate.score,
                    matched_terms=candidate.matched_terms,
                    auto_activate=False,
                    rationale=candidate.rationale,
                )
                for candidate in semantic_candidates
            )

        prompt_mode = next(
            (skill.prompt_mode for skill in reversed(chosen) if skill.prompt_mode is not None),
            None,
        )
        confidence = semantic_candidates[0].score if semantic_candidates else 0.0
        return SkillSelection(
            skill_ids=tuple(skill.skill_id for skill in chosen),
            stripped_message=stripped or message.strip(),
            prompt_mode=prompt_mode,
            selection_source=_selection_source(
                explicit_matched=explicit_matched,
                prefix_matched=bool(matched_triggers),
                semantic_matched=semantic_matched,
            ),
            matched_triggers=tuple(matched_triggers),
            semantic_candidates=semantic_candidates,
            confidence=confidence,
            rationale=self._selection_rationale(
                selection_source=_selection_source(
                    explicit_matched=explicit_matched,
                    prefix_matched=bool(matched_triggers),
                    semantic_matched=semantic_matched,
                ),
                semantic_enabled=semantic_enabled,
                semantic_candidates=semantic_candidates,
                threshold=threshold,
            ),
        )

    def explicit_hints_for_message(self, message: str) -> tuple[str, ...]:
        lowered = str(message or "").lower()
        if not lowered:
            return ()
        hints: list[str] = []
        seen: set[str] = set()
        for skill in self._active_skills():
            skill_id = skill.skill_id.lower()
            escaped = re.escape(skill_id)
            path_markers = (
                f".focus_agent/skills/{skill_id}/skill.md",
                f"/skills/{skill_id}/skill.md",
            )
            contextual_patterns = (
                rf"(?<![a-z0-9_-]){escaped}(?![a-z0-9_-])\s*(?:skill|技能)",
                rf"(?:skill|技能)\s*[：:'\"`（(]*\s*{escaped}(?![a-z0-9_-])",
                rf"(?:调用|使用|use|run)\s*{escaped}(?![a-z0-9_-])",
            )
            if not (
                any(marker in lowered for marker in path_markers)
                or any(re.search(pattern, lowered) for pattern in contextual_patterns)
            ):
                continue
            if skill.skill_id in seen:
                continue
            seen.add(skill.skill_id)
            hints.append(skill.skill_id)
        return tuple(hints)

    def semantic_candidates_for_message(
        self,
        message: str,
        *,
        threshold: float | None = None,
        limit: int = _SEMANTIC_CANDIDATE_LIMIT,
    ) -> tuple[SkillSemanticCandidate, ...]:
        if not self._enabled:
            return ()
        zvec_candidates = self._retrieval_semantic_candidates(
            message,
            threshold=self._semantic_match_threshold if threshold is None else float(threshold),
            limit=limit,
        )
        if zvec_candidates:
            return zvec_candidates
        query: dict[str, float] = {}
        _add_weighted_tokens(query, message, 1.0)
        if not query:
            return ()
        resolved_threshold = (
            self._semantic_match_threshold if threshold is None else float(threshold)
        )
        candidates: list[SkillSemanticCandidate] = []
        for skill in self._skills:
            if not self.is_skill_enabled(skill.skill_id):
                continue
            vector = self._semantic_vectors.get(skill.skill_id, {})
            score = round(_cosine_score(query, vector), 4)
            if score <= 0:
                continue
            matched_terms = tuple(sorted(token for token in query if vector.get(token, 0.0) > 0))
            candidates.append(
                SkillSemanticCandidate(
                    skill_id=skill.skill_id,
                    score=score,
                    matched_terms=matched_terms,
                    auto_activate=score >= resolved_threshold,
                    rationale=self._semantic_rationale(
                        skill_id=skill.skill_id,
                        score=score,
                        matched_terms=matched_terms,
                        threshold=resolved_threshold,
                    ),
                )
            )
        candidates.sort(key=lambda item: (-item.score, item.skill_id))
        return tuple(candidates[: max(0, limit)])

    def _retrieval_semantic_candidates(
        self,
        message: str,
        *,
        threshold: float,
        limit: int,
    ) -> tuple[SkillSemanticCandidate, ...]:
        if self._retrieval_index is None or self._embedding_provider is None:
            return ()
        try:
            query_vector = self._embedding_provider.embed([message])[0]
            hits = self._retrieval_index.search(
                collection="focus_skills",
                query=message,
                vector=query_vector,
                limit=limit,
            )
        except Exception:  # noqa: BLE001
            return ()
        candidates: list[SkillSemanticCandidate] = []
        for hit in hits:
            skill_id = _normalize_skill_id(hit.source_id)
            if not self.is_skill_enabled(skill_id):
                continue
            score = round(float(hit.score), 4)
            candidates.append(
                SkillSemanticCandidate(
                    skill_id=skill_id,
                    score=score,
                    matched_terms=(),
                    auto_activate=score >= threshold,
                    rationale=self._semantic_rationale(
                        skill_id=skill_id,
                        score=score,
                        matched_terms=(),
                        threshold=threshold,
                    ),
                )
            )
        return tuple(candidates[: max(0, limit)])

    def _index_skills_best_effort(self) -> None:
        if self._retrieval_index is None or self._embedding_provider is None:
            return
        for skill in self._active_skills():
            text = _skill_retrieval_text(skill)
            try:
                vector = self._embedding_provider.embed([text])[0]
                self._retrieval_index.upsert(
                    RetrievalDocument(
                        collection="focus_skills",
                        doc_id=f"skill:{skill.skill_id}",
                        source_id=skill.skill_id,
                        text=text,
                        vector=vector,
                        fields={
                            "source_type": "skill",
                            "skill_id": skill.skill_id,
                            "source_id": skill.source_id,
                            "enabled": True,
                            "trust_level": skill.trust_level,
                        },
                    )
                )
            except Exception:  # noqa: BLE001
                continue

    @staticmethod
    def _semantic_rationale(
        *,
        skill_id: str,
        score: float,
        matched_terms: tuple[str, ...],
        threshold: float,
    ) -> str:
        term_text = ", ".join(matched_terms[:5]) if matched_terms else "no shared terms"
        decision = "meets" if score >= threshold else "below"
        return f"{skill_id} {decision} semantic threshold {threshold:.2f}; matched {term_text}."

    @staticmethod
    def _selection_rationale(
        *,
        selection_source: str,
        semantic_enabled: bool,
        semantic_candidates: tuple[SkillSemanticCandidate, ...],
        threshold: float,
    ) -> str:
        if selection_source == "explicit":
            return "Selected from explicit skill hints."
        if selection_source == "prefix":
            return "Selected from message prefix triggers."
        if selection_source == "mixed":
            return "Selected from higher-priority explicit hints or prefix triggers."
        if selection_source == "semantic":
            top = semantic_candidates[0] if semantic_candidates else None
            if top is not None:
                return f"Selected {top.skill_id} from semantic match score {top.score:.2f}."
            return "Selected from semantic match."
        if not semantic_enabled:
            return "No skills selected; semantic matching is disabled."
        if semantic_candidates:
            top = semantic_candidates[0]
            return (
                f"No skills auto-activated; top semantic candidate {top.skill_id} "
                f"scored {top.score:.2f}, below threshold {threshold:.2f}."
            )
        return "No skills selected."

    def list_skills(self) -> list[dict[str, Any]]:
        return [
            {
                "name": skill.skill_id,
                "description": skill.description,
                "enabled": self.is_skill_enabled(skill.skill_id),
                "triggers": list(skill.triggers),
                "aliases": list(skill.aliases),
                "localized_triggers": list(skill.localized_triggers),
                "domains": list(skill.domains),
                "intents": list(skill.intents),
                "when_to_use": list(skill.when_to_use),
                "primary_tools": list(skill.primary_tools),
                "recommended_tools": list(skill.recommended_tools),
                "prompt_mode": skill.prompt_mode.value if skill.prompt_mode else None,
                "path": str(skill.path),
                "source_id": skill.source_id,
                "source_type": skill.source_type,
                "version": skill.version,
                "trust_level": skill.trust_level,
                "install_state": skill.install_state,
                "provenance": skill.provenance,
                "checksum": skill.checksum,
                "capability_requirements": list(skill.capability_requirements),
                "entrypoints": [_entrypoint_to_dict(entry) for entry in skill.entrypoints],
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
            "enabled": self.is_skill_enabled(skill.skill_id),
            "triggers": list(skill.triggers),
            "aliases": list(skill.aliases),
            "localized_triggers": list(skill.localized_triggers),
            "domains": list(skill.domains),
            "intents": list(skill.intents),
            "when_to_use": list(skill.when_to_use),
            "primary_tools": list(skill.primary_tools),
            "recommended_tools": list(skill.recommended_tools),
            "prompt_mode": skill.prompt_mode.value if skill.prompt_mode else None,
            "path": str(skill.path),
            "source_id": skill.source_id,
            "source_type": skill.source_type,
            "version": skill.version,
            "trust_level": skill.trust_level,
            "install_state": skill.install_state,
            "provenance": skill.provenance,
            "checksum": skill.checksum,
            "capability_requirements": list(skill.capability_requirements),
            "entrypoints": [_entrypoint_to_dict(entry) for entry in skill.entrypoints],
            "content": skill.body,
        }

    def render_available_skills_block(self) -> str:
        active_skills = self._active_skills()
        if not active_skills:
            return ""

        lines = [
            "## Available skills",
            "If a user message starts with one of these prefixes, activate the matching skill for that turn.",
        ]
        for skill in active_skills:
            trigger_text = ", ".join(skill.triggers) if skill.triggers else "manual only"
            line = f"- {skill.skill_id}: {skill.description} (triggers: {trigger_text})"
            if skill.aliases:
                line += f" Aliases: {', '.join(skill.aliases)}."
            if skill.localized_triggers:
                line += f" Localized triggers: {', '.join(skill.localized_triggers)}."
            if skill.when_to_use:
                line += f" Use when: {'; '.join(skill.when_to_use)}"
            lines.append(line)
        return "\n".join(lines)

    def render_active_skills_block(self, skill_ids: Iterable[str]) -> str:
        skills = [self.resolve(skill_id) for skill_id in skill_ids]
        resolved = [
            skill
            for skill in skills
            if skill is not None and self.is_skill_enabled(skill.skill_id)
        ]
        if not resolved:
            return ""

        sections = [
            "## Active skills",
            "Apply the following skill instructions for this turn in addition to the base agent rules.",
        ]
        for skill in resolved:
            entrypoint_block = ""
            if skill.entrypoints:
                lines = ["Declared entrypoints:"]
                for entry in skill.entrypoints:
                    lines.append(
                        f"- {entry.name}: {' '.join(entry.command)}"
                    )
                entrypoint_block = "\n\n" + "\n".join(lines)
            sections.append(f"### {skill.skill_id}\n{skill.body}{entrypoint_block}")
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

    def _search_installed(
        self,
        query: str,
        *,
        source_filter: set[str],
        limit: int,
    ) -> list[SkillSearchResult]:
        if query.strip():
            candidates = self.semantic_candidates_for_message(
                query, threshold=0.0, limit=max(limit, len(self._skills))
            )
            scores = {candidate.skill_id: candidate.score for candidate in candidates}
            ordered_skills = sorted(
                self._skills,
                key=lambda skill: (-scores.get(skill.skill_id, 0.0), skill.skill_id),
            )
        else:
            scores = {}
            ordered_skills = sorted(self._skills, key=lambda skill: skill.skill_id)
        results: list[SkillSearchResult] = []
        for skill in ordered_skills:
            if not self.is_skill_enabled(skill.skill_id):
                continue
            if (
                source_filter
                and "installed" not in source_filter
                and skill.source_id not in source_filter
            ):
                continue
            score = scores.get(skill.skill_id, 1.0 if not query.strip() else 0.0)
            if query.strip() and score <= 0:
                haystack = " ".join(
                    [
                        skill.skill_id,
                        skill.description,
                        " ".join(skill.triggers),
                        " ".join(skill.aliases),
                        " ".join(skill.localized_triggers),
                        " ".join(skill.domains),
                        " ".join(skill.intents),
                        " ".join(skill.when_to_use),
                        " ".join(skill.primary_tools),
                        " ".join(skill.capability_requirements),
                    ]
                ).lower()
                if query.lower() not in haystack:
                    continue
                score = 0.1
            results.append(_search_result_from_skill(skill, score=score, installed=True))
        return results[: max(0, int(limit or 0))]

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
