from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from .models import SkillInstallResult, SkillSearchResult


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


def render_skills_list_json(registry: Any) -> str:
    return json.dumps(
        {
            "success": True,
            "skills": registry.list_skills(),
        },
        ensure_ascii=False,
    )


def render_skill_view_json(registry: Any, *, skill_id: str) -> str:
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


def render_skill_sources_json(registry: Any) -> str:
    return json.dumps(
        {
            "success": True,
            "sources": registry.list_sources(),
        },
        ensure_ascii=False,
    )


def render_skills_search_json(
    registry: Any,
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
    registry: Any,
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
    registry: Any,
    *,
    sources: Iterable[str] = (),
) -> str:
    return json.dumps(registry.refresh_index(sources=sources), ensure_ascii=False)


__all__ = [
    "_install_result_to_dict",
    "_search_result_to_dict",
    "render_skill_install_json",
    "render_skill_sources_json",
    "render_skill_view_json",
    "render_skills_list_json",
    "render_skills_refresh_index_json",
    "render_skills_search_json",
]
