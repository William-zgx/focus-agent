from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..config import Settings
from .models import SkillInstallResult
from .registry_paths import _is_safe_skill_id, _normalize_skill_id

_SKILL_FILE_NAME = "SKILL.md"


class SkillRegistryManagementMixin:
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


__all__ = ["SkillRegistryManagementMixin"]
