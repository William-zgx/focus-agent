from __future__ import annotations

import hashlib

from focus_agent.core.governance import (
    ContextMemoryEvidence,
    SkillPreference,
    SkillSelectionEvent,
)

from ..contracts import (
    AgentContextEvidenceResponse,
    AgentSkillPreferenceResponse,
    AgentSkillSelectionEventResponse,
)


def _context_evidence_response(evidence: ContextMemoryEvidence) -> AgentContextEvidenceResponse:
    return AgentContextEvidenceResponse(
        evidence_id=evidence.evidence_id,
        user_id=evidence.user_id,
        thread_id=evidence.thread_id,
        turn_id=evidence.turn_id,
        source_kind=evidence.source_kind,
        selected_memories=list(evidence.selected_memories),
        excluded_memories=list(evidence.excluded_memories),
        compaction_summary=dict(evidence.compaction_summary),
        drift_report=dict(evidence.drift_report),
        artifact_refs=list(evidence.artifact_refs),
        token_counting=dict(evidence.token_counting),
        risk_flags=list(evidence.risk_flags),
        metadata=dict(evidence.metadata),
        created_at=evidence.created_at,
    )


def _skill_selection_event_response(event: SkillSelectionEvent) -> AgentSkillSelectionEventResponse:
    return AgentSkillSelectionEventResponse(
        selection_id=event.selection_id,
        user_id=event.user_id,
        message_preview=event.message_preview,
        selection_source=event.selection_source,
        explicit_hints=list(event.explicit_hints),
        activated_skill_ids=list(event.activated_skill_ids),
        matched_triggers=list(event.matched_triggers),
        semantic_candidates=list(event.semantic_candidates),
        confidence=event.confidence,
        rationale=event.rationale,
        feedback=event.feedback,
        feedback_reason=event.feedback_reason,
        user_override=dict(event.user_override),
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def _skill_preference_response(
    preference: SkillPreference | None,
) -> AgentSkillPreferenceResponse | None:
    if preference is None:
        return None
    return AgentSkillPreferenceResponse(
        preference_id=preference.preference_id,
        user_id=preference.user_id,
        skill_id=preference.skill_id,
        state=preference.state,
        metadata=dict(preference.metadata),
        created_at=preference.created_at,
        updated_at=preference.updated_at,
    )


def _message_hash(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def _message_preview(message: str) -> str:
    stripped = " ".join(str(message or "").split())
    return stripped[:180]


def _normalize_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_values = [value]
    else:
        raw_values = list(value) if isinstance(value, list | tuple | set) else [value]
    return list(dict.fromkeys(str(item).strip() for item in raw_values if str(item).strip()))


__all__ = [
    "_context_evidence_response",
    "_message_hash",
    "_message_preview",
    "_normalize_string_list",
    "_skill_preference_response",
    "_skill_selection_event_response",
]
