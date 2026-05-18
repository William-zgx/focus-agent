from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..config import Settings
from ..core.types import PromptMode
from .models import (
    SkillDefinition,
    SkillInstallResult,
    SkillSearchResult,
    SkillSelection,
    SkillSemanticCandidate,
    SkillSourceDefinition,
)

_SKILL_FILE_NAME = "SKILL.md"
_SEMANTIC_CANDIDATE_LIMIT = 3
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "before",
    "but",
    "by",
    "for",
    "from",
    "has",
    "in",
    "into",
    "is",
    "it",
    "needs",
    "of",
    "on",
    "or",
    "should",
    "skill",
    "skills",
    "that",
    "the",
    "this",
    "to",
    "tool",
    "tools",
    "use",
    "user",
    "wants",
    "when",
    "with",
    "work",
    "you",
}

_QUERY_ALIAS_MARKERS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("发布前", "发布", "发版", "上线", "里程碑"), ("release", "readiness", "checklist")),
    (("构建失败", "构建", "编译"), ("build", "failure", "fix")),
    (("修复", "报错", "失败"), ("fix", "failure")),
    (("测试", "单测", "回归"), ("test", "tdd", "regression")),
    (("评审", "审查", "复查"), ("review",)),
    (("安全", "权限", "漏洞"), ("security", "review")),
    (("文档", "说明", "readme"), ("documentation", "docs")),
    (("计划", "方案", "拆解"), ("plan", "planning")),
    (("调研", "研究", "资料"), ("research",)),
    (("提交", "合并", "拉取请求"), ("git", "pr", "workflow")),
)


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


def _semantic_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on"}


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in _TOKEN_RE.findall(value.lower().replace("_", " "))
        if len(token) > 1 and token not in _STOPWORDS
    )


def _body_headings(body: str) -> tuple[str, ...]:
    return tuple(
        match.group(1).strip().strip("#").strip()
        for match in _HEADING_RE.finditer(body)
        if match.group(1).strip()
    )


def _add_weighted_tokens(vector: dict[str, float], value: str, weight: float) -> None:
    for token in _tokens(value):
        vector[token] = vector.get(token, 0.0) + weight
    lowered = value.lower()
    for markers, aliases in _QUERY_ALIAS_MARKERS:
        if not any(marker in lowered for marker in markers):
            continue
        for alias in aliases:
            if alias not in _STOPWORDS:
                vector[alias] = vector.get(alias, 0.0) + weight


def _skill_semantic_vector(skill: SkillDefinition) -> dict[str, float]:
    vector: dict[str, float] = {}
    _add_weighted_tokens(vector, skill.description, 3.0)
    for item in skill.when_to_use:
        _add_weighted_tokens(vector, item, 4.0)
    for item in skill.recommended_tools:
        _add_weighted_tokens(vector, item, 1.5)
    for heading in _body_headings(skill.body):
        _add_weighted_tokens(vector, heading, 2.0)
    return vector


def _cosine_score(query: dict[str, float], document: dict[str, float]) -> float:
    if not query or not document:
        return 0.0
    dot = sum(weight * document.get(token, 0.0) for token, weight in query.items())
    if dot <= 0:
        return 0.0
    query_norm = math.sqrt(sum(weight * weight for weight in query.values()))
    document_norm = math.sqrt(sum(weight * weight for weight in document.values()))
    if query_norm <= 0 or document_norm <= 0:
        return 0.0
    return dot / (query_norm * document_norm)


def _selection_source(
    *,
    explicit_matched: bool,
    prefix_matched: bool,
    semantic_matched: bool,
) -> str:
    sources = [
        source
        for source, matched in (
            ("explicit", explicit_matched),
            ("prefix", prefix_matched),
            ("semantic", semantic_matched),
        )
        if matched
    ]
    if not sources:
        return "none"
    if len(sources) == 1:
        return sources[0]
    return "mixed"


class SkillRegistry:
    def __init__(
        self,
        skill_dirs: Iterable[Path],
        *,
        semantic_match_enabled: bool = True,
        semantic_match_threshold: float = 0.22,
        source_definitions: Iterable[SkillSourceDefinition] = (),
        install_dir: Path | None = None,
    ):
        configured_skill_dirs = tuple(
            path.expanduser().resolve()
            for path in skill_dirs
            if str(path).strip()
        )
        resolved_install_dir = install_dir.expanduser().resolve() if install_dir else None
        if resolved_install_dir is not None and resolved_install_dir not in configured_skill_dirs:
            configured_skill_dirs = (*configured_skill_dirs, resolved_install_dir)
        self._skill_dirs = configured_skill_dirs
        self._semantic_match_enabled = bool(semantic_match_enabled)
        self._semantic_match_threshold = float(semantic_match_threshold)
        self._source_definitions = self._normalize_sources(source_definitions)
        self._install_dir = resolved_install_dir
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
        self._skills_by_id = {
            _normalize_skill_id(skill.skill_id): skill
            for skill in self._skills
        }
        self._semantic_vectors = {
            skill.skill_id: _skill_semantic_vector(skill)
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
    def from_settings(cls, settings: Settings) -> SkillRegistry:
        configured = [Path(path) for path in settings.skill_directories]
        source_definitions = _source_definitions_from_settings(settings)
        return cls(
            [*configured, bundled_skills_dir()],
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
        )

    @property
    def skill_dirs(self) -> tuple[Path, ...]:
        return self._skill_dirs

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
        if source.source_type != "local" or not source.location:
            return SkillInstallResult(
                success=False,
                skill_id=normalized_skill_id,
                source_id=source.source_id,
                requires_review=True,
                error="Only trusted local skill sources can be installed by this runtime.",
                metadata={"source_type": source.source_type, "mode": mode},
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

        for hint in explicit_hints:
            skill = self.resolve(str(hint))
            if skill is None or skill.skill_id in seen:
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

    def semantic_candidates_for_message(
        self,
        message: str,
        *,
        threshold: float | None = None,
        limit: int = _SEMANTIC_CANDIDATE_LIMIT,
    ) -> tuple[SkillSemanticCandidate, ...]:
        query: dict[str, float] = {}
        _add_weighted_tokens(query, message, 1.0)
        if not query:
            return ()
        resolved_threshold = (
            self._semantic_match_threshold
            if threshold is None
            else float(threshold)
        )
        candidates: list[SkillSemanticCandidate] = []
        for skill in self._skills:
            vector = self._semantic_vectors.get(skill.skill_id, {})
            score = round(_cosine_score(query, vector), 4)
            if score <= 0:
                continue
            matched_terms = tuple(
                sorted(token for token in query if vector.get(token, 0.0) > 0)
            )
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
                "triggers": list(skill.triggers),
                "when_to_use": list(skill.when_to_use),
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
        if not skill_id or not description:
            return None
        resolved_source = source or self._source_for_path(skill_path)
        return SkillDefinition(
            skill_id=_normalize_skill_id(skill_id),
            description=description,
            path=skill_path,
            body=body,
            raw_text=raw_text,
            triggers=_normalize_list(frontmatter.get("triggers")),
            when_to_use=_normalize_list(frontmatter.get("when_to_use")),
            recommended_tools=_normalize_list(frontmatter.get("recommended_tools")),
            prompt_mode=_coerce_prompt_mode(frontmatter.get("prompt_mode")),
            source_id=resolved_source.source_id,
            source_type=resolved_source.source_type,
            version=str(frontmatter.get("version") or "").strip() or None,
            trust_level="trusted" if resolved_source.trusted else "untrusted",
            install_state="installed",
            provenance=str(frontmatter.get("provenance") or "").strip()
            or resolved_source.location,
            checksum=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
            capability_requirements=_normalize_list(frontmatter.get("capability_requirements")),
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
            candidates = self.semantic_candidates_for_message(query, threshold=0.0, limit=max(limit, len(self._skills)))
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
            if source_filter and "installed" not in source_filter and skill.source_id not in source_filter:
                continue
            score = scores.get(skill.skill_id, 1.0 if not query.strip() else 0.0)
            if query.strip() and score <= 0:
                haystack = " ".join(
                    [
                        skill.skill_id,
                        skill.description,
                        " ".join(skill.triggers),
                        " ".join(skill.when_to_use),
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
                skill = self._load_skill(skill_path, source=source)
                if skill is None or self.resolve(skill.skill_id) is not None:
                    continue
                score = 1.0
                if query.strip():
                    score = round(_cosine_score(query_vector, _skill_semantic_vector(skill)), 4)
                    haystack = (
                        f"{skill.skill_id} {skill.description} {' '.join(skill.when_to_use)}"
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
            skill = self._load_skill(skill_path, source=source)
            if skill is not None and skill.skill_id == skill_id:
                return skill
        return None


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
        rationale="Installed semantic/local match." if installed else "External local source match.",
    )


def _source_definitions_from_settings(settings: Settings) -> tuple[SkillSourceDefinition, ...]:
    enabled_sources = {
        str(source).strip().lower()
        for source in getattr(settings, "skill_sources_enabled", ("installed",)) or ()
        if str(source).strip()
    }
    trusted_sources = {
        str(source).strip().lower()
        for source in getattr(settings, "skill_trusted_sources", ("installed", "project", "builtin")) or ()
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
        source = _parse_source_location(str(raw), trusted_sources=trusted_sources, enabled_sources=enabled_sources)
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
        enabled=not enabled_sources or source_id in enabled_sources or "external" in enabled_sources,
        trusted=source_id in trusted_sources,
        location=location,
    )


def _search_result_to_dict(result: SkillSearchResult) -> dict[str, Any]:
    return {
        "skill_id": result.skill_id,
        "description": result.description,
        "source_id": result.source_id,
        "source_type": result.source_type,
        "path": result.path,
        "installed": result.installed,
        "trust_level": result.trust_level,
        "version": result.version,
        "provenance": result.provenance,
        "checksum": result.checksum,
        "recommended_tools": list(result.recommended_tools),
        "capability_requirements": list(result.capability_requirements),
        "score": result.score,
        "rationale": result.rationale,
    }


def _install_result_to_dict(result: SkillInstallResult) -> dict[str, Any]:
    return {
        "success": result.success,
        "skill_id": result.skill_id,
        "source_id": result.source_id,
        "installed": result.installed,
        "installed_path": result.installed_path,
        "requires_review": result.requires_review,
        "error": result.error,
        "metadata": dict(result.metadata or {}),
    }


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


def render_skill_sources_json(registry: SkillRegistry) -> str:
    return json.dumps(
        {
            "success": True,
            "sources": registry.list_sources(),
        },
        ensure_ascii=False,
    )


def render_skills_search_json(
    registry: SkillRegistry,
    *,
    query: str,
    scope: str = "installed",
    sources: Iterable[str] = (),
    limit: int = 5,
) -> str:
    return json.dumps(
        {
            "success": True,
            "query": query,
            "scope": scope,
            "results": [
                _search_result_to_dict(result)
                for result in registry.search_skills(
                    query,
                    scope=scope,
                    sources=sources,
                    limit=limit,
                )
            ],
        },
        ensure_ascii=False,
    )


def render_skill_install_json(
    registry: SkillRegistry,
    *,
    skill_id: str,
    source_id: str = "installed",
    version: str | None = None,
    mode: str = "project",
) -> str:
    return json.dumps(
        _install_result_to_dict(
            registry.install_skill(
                skill_id=skill_id,
                source_id=source_id,
                version=version,
                mode=mode,
            )
        ),
        ensure_ascii=False,
    )


def render_skills_refresh_index_json(
    registry: SkillRegistry,
    *,
    sources: Iterable[str] = (),
) -> str:
    return json.dumps(registry.refresh_index(sources=sources), ensure_ascii=False)
