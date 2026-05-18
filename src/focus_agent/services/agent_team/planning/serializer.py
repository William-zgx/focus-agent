from __future__ import annotations

from typing import Any

from focus_agent.skills import SkillRegistry

from ...agent_team_planning_models import *  # noqa: F401,F403
from ...agent_team_planning_models import __all__ as _models_all
from ...agent_team_planning_support import _task_draft_from_spec


def _skill_plan_for_session(settings: Any | None, session: Any) -> dict[str, Any]:
    if settings is None or not bool(getattr(settings, "agent_team_skill_scout_enabled", True)):
        return {}

    registry = SkillRegistry.from_settings(settings)
    selection = registry.select_for_message(session.goal)
    candidates = registry.search_skills(session.goal, scope="installed", limit=5)
    selected_skills = [
        skill
        for skill_id in selection.skill_ids
        for skill in [registry.resolve(skill_id)]
        if skill is not None
    ]
    recommended_tools = _dedupe_values(
        tool for skill in selected_skills for tool in skill.recommended_tools if str(tool).strip()
    )
    capability_requirements = _dedupe_values(
        requirement
        for skill in selected_skills
        for requirement in skill.capability_requirements
        if str(requirement).strip()
    )
    context_refs = [
        {
            "kind": "skill",
            "type": "skill",
            "skill_id": skill.skill_id,
            "source_id": skill.source_id,
            "source_type": skill.source_type,
            "trust_level": skill.trust_level,
            "recommended_tools": list(skill.recommended_tools),
            "capability_requirements": list(skill.capability_requirements),
            "path": str(skill.path),
        }
        for skill in selected_skills
    ]
    resolution_event = {
        "source": selection.selection_source,
        "selected_skill_ids": list(selection.skill_ids),
        "matched_triggers": list(selection.matched_triggers),
        "confidence": selection.confidence,
        "rationale": selection.rationale,
    }
    return {
        "enabled": True,
        "automation_level": str(getattr(settings, "agent_team_automation_level", "assisted")),
        "selected_skill_ids": list(selection.skill_ids),
        "recommended_tools": recommended_tools,
        "capability_requirements": capability_requirements,
        "context_refs": context_refs,
        "resolution_events": [resolution_event],
        "candidates": [
            {
                "skill_id": candidate.skill_id,
                "description": candidate.description,
                "source_id": candidate.source_id,
                "source_type": candidate.source_type,
                "installed": candidate.installed,
                "trust_level": candidate.trust_level,
                "score": candidate.score,
                "rationale": candidate.rationale,
                "recommended_tools": list(candidate.recommended_tools),
                "capability_requirements": list(candidate.capability_requirements),
            }
            for candidate in candidates
        ],
    }


def _dedupe_values(values: Any) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _merge_context_refs(
    base_refs: list[dict[str, Any]],
    extra_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ref in [*base_refs, *extra_refs]:
        if not isinstance(ref, dict):
            continue
        kind = str(ref.get("kind") or ref.get("type") or "").strip()
        ref_id = str(ref.get("id") or ref.get("skill_id") or ref.get("path") or "").strip()
        identity = (kind, ref_id)
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(dict(ref))
    return merged


__all__ = [
    *_models_all,
    "_dedupe_values",
    "_merge_context_refs",
    "_skill_plan_for_session",
    "_task_draft_from_spec",
]
