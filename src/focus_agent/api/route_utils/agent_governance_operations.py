from __future__ import annotations

from fastapi import HTTPException, status

from focus_agent.core.governance import (
    ContextMemoryEvidence,
    FeedbackEvent,
    SkillPreference,
    SkillSelectionEvent,
)
from focus_agent.engine.runtime import AppRuntime
from focus_agent.repositories.governance_repository import InMemoryGovernanceRepository
from focus_agent.security.tokens import Principal

from ..contracts import (
    AgentContextEvidenceListResponse,
    AgentContextEvidenceResponse,
    AgentContextExplainRequest,
    AgentContextExplainResponse,
    AgentSkillCatalogItemResponse,
    AgentSkillCatalogResponse,
    AgentSkillPreferenceRequest,
    AgentSkillPreferenceResponse,
    AgentSkillSelectionEventListResponse,
    AgentSkillSelectionEventResponse,
    AgentSkillSelectionFeedbackRequest,
    AgentSkillSelectionFeedbackResponse,
    AgentSkillSelectionResponse,
    AgentSkillSelectRequest,
)
from .agent_governance_serializers import (
    _context_evidence_response,
    _message_hash,
    _message_preview,
    _normalize_string_list,
    _skill_preference_response,
    _skill_selection_event_response,
)

_VALID_SKILL_PREFERENCE_STATES = {"default", "pinned", "disabled"}


def _governance_repository(runtime: AppRuntime) -> object:
    repository = getattr(runtime, "governance_repository", None)
    if repository is not None:
        return repository
    repository = getattr(runtime, "context_memory_evidence_repository", None)
    if repository is not None:
        return repository
    database_uri = getattr(getattr(runtime, "settings", None), "database_uri", None)
    if database_uri:
        from focus_agent.repositories.postgres_governance_repository import (
            PostgresGovernanceRepository,
        )

        repository = PostgresGovernanceRepository(str(database_uri))
    else:
        repository = InMemoryGovernanceRepository()
    try:
        runtime.governance_repository = repository
    except Exception:  # noqa: BLE001 - tests may use immutable runtime stubs.
        pass
    return repository


def _agent_context_explain_response(
    *,
    payload: AgentContextExplainRequest,
    runtime: AppRuntime,
    principal: Principal,
) -> AgentContextExplainResponse:
    if not bool(getattr(runtime.settings, "context_memory_evidence_enabled", True)):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Context/memory evidence capture is disabled.",
        )
    repository = _governance_repository(runtime)
    evidence = ContextMemoryEvidence(
        user_id=principal.user_id,
        thread_id=payload.thread_id,
        turn_id=payload.turn_id,
        selected_memories=list(payload.selected_memories),
        excluded_memories=list(payload.excluded_memories),
        compaction_summary=dict(payload.compaction_summary),
        drift_report=dict(payload.drift_report),
        artifact_refs=list(payload.artifact_refs),
        token_counting=dict(payload.token_counting),
        risk_flags=_normalize_string_list(payload.risk_flags),
        metadata=dict(payload.metadata),
    )
    repository.save_context_evidence(evidence)
    return AgentContextExplainResponse(item=_context_evidence_response(evidence))


def _agent_context_evidence_list_response(
    *,
    runtime: AppRuntime,
    principal: Principal,
    thread_id: str | None,
    turn_id: str | None,
    limit: int,
) -> AgentContextEvidenceListResponse:
    repository = _governance_repository(runtime)
    items = repository.list_context_evidence(
        thread_id=thread_id,
        turn_id=turn_id,
        user_id=principal.user_id,
        limit=limit,
    )
    return AgentContextEvidenceListResponse(
        items=[_context_evidence_response(item) for item in items],
        count=len(items),
        filters={"thread_id": thread_id, "turn_id": turn_id},
        limit=limit,
    )


def _skill_selection_event_for_response(
    *,
    payload: AgentSkillSelectRequest,
    response: AgentSkillSelectionResponse,
    principal: Principal,
) -> SkillSelectionEvent:
    return SkillSelectionEvent(
        user_id=principal.user_id,
        message_hash=_message_hash(payload.message),
        message_preview=_message_preview(payload.message),
        selection_source=response.selection_source,
        explicit_hints=_normalize_string_list(payload.skill_hints),
        activated_skill_ids=_normalize_string_list(response.skill_ids),
        matched_triggers=_normalize_string_list(response.matched_triggers),
        semantic_candidates=[
            candidate.model_dump(mode="json") for candidate in response.semantic_candidates
        ],
        confidence=response.confidence,
        rationale=response.rationale,
        semantic_enabled=response.semantic_enabled,
        semantic_threshold=response.semantic_threshold,
        metadata={
            "stripped_message": response.stripped_message,
            "prompt_mode": response.prompt_mode,
        },
    )


def _persist_skill_selection_event(
    *,
    runtime: AppRuntime,
    principal: Principal,
    payload: AgentSkillSelectRequest,
    response: AgentSkillSelectionResponse,
) -> AgentSkillSelectionResponse:
    if not bool(getattr(runtime.settings, "skill_selection_event_log_enabled", True)):
        return response
    repository = _governance_repository(runtime)
    event = _skill_selection_event_for_response(
        payload=payload,
        response=response,
        principal=principal,
    )
    repository.save_skill_selection_event(event)
    return response.model_copy(update={"selection_id": event.selection_id})


def _agent_skill_selection_events_response(
    *,
    runtime: AppRuntime,
    principal: Principal,
    skill_id: str | None,
    limit: int,
) -> AgentSkillSelectionEventListResponse:
    repository = _governance_repository(runtime)
    items = repository.list_skill_selection_events(
        user_id=principal.user_id,
        skill_id=skill_id,
        limit=limit,
    )
    return AgentSkillSelectionEventListResponse(
        items=[_skill_selection_event_response(item) for item in items],
        count=len(items),
        filters={"skill_id": skill_id},
        limit=limit,
    )


def _agent_skill_selection_feedback_response(
    *,
    runtime: AppRuntime,
    principal: Principal,
    selection_id: str,
    payload: AgentSkillSelectionFeedbackRequest,
) -> AgentSkillSelectionFeedbackResponse:
    repository = _governance_repository(runtime)
    existing = repository.get_skill_selection_event(selection_id)
    if existing is None or existing.user_id not in {None, principal.user_id}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Skill selection not found."
        )
    updated = repository.update_skill_selection_feedback(
        selection_id=selection_id,
        feedback=payload.feedback,
        reason=payload.reason,
        user_override=dict(payload.user_override),
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Skill selection not found."
        )
    feedback_event = FeedbackEvent(
        user_id=principal.user_id,
        source_kind="skill_selection",
        source_id=selection_id,
        sentiment=payload.feedback,
        category="skill_feedback",
        metadata={"reason": payload.reason, "user_override": dict(payload.user_override)},
    )
    feedback_event_id = repository.save_feedback_event(feedback_event)
    return AgentSkillSelectionFeedbackResponse(
        item=_skill_selection_event_response(updated),
        feedback_event_id=feedback_event_id,
    )


def _agent_skill_catalog_response(
    *,
    runtime: AppRuntime,
    principal: Principal,
) -> AgentSkillCatalogResponse:
    repository = _governance_repository(runtime)
    preferences = {
        item.skill_id: item for item in repository.list_skill_preferences(user_id=principal.user_id)
    }
    items = []
    for skill in runtime.skill_registry.list_skills():
        skill_id = str(skill.get("name") or skill.get("skill_id") or "")
        items.append(
            AgentSkillCatalogItemResponse(
                skill_id=skill_id,
                description=str(skill.get("description") or ""),
                triggers=_normalize_string_list(skill.get("triggers")),
                when_to_use=_normalize_string_list(skill.get("when_to_use")),
                recommended_tools=_normalize_string_list(skill.get("recommended_tools")),
                prompt_mode=skill.get("prompt_mode"),
                path=skill.get("path"),
                preference=_skill_preference_response(preferences.get(skill_id)),
            )
        )
    return AgentSkillCatalogResponse(items=items, count=len(items))


def _agent_skill_preference_response(
    *,
    runtime: AppRuntime,
    principal: Principal,
    skill_id: str,
    payload: AgentSkillPreferenceRequest,
) -> AgentSkillPreferenceResponse:
    if runtime.skill_registry.resolve(skill_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found.")
    state = str(payload.state or "default").strip().lower()
    if state not in _VALID_SKILL_PREFERENCE_STATES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Skill preference state must be one of: {', '.join(sorted(_VALID_SKILL_PREFERENCE_STATES))}.",
        )
    repository = _governance_repository(runtime)
    preference = SkillPreference(
        user_id=principal.user_id,
        skill_id=skill_id,
        state=state,
        metadata=dict(payload.metadata),
    )
    saved = repository.save_skill_preference(preference)
    return _skill_preference_response(saved)


__all__ = [
    "AgentContextEvidenceResponse",
    "AgentSkillSelectionEventResponse",
    "_agent_context_evidence_list_response",
    "_agent_context_explain_response",
    "_agent_skill_catalog_response",
    "_agent_skill_preference_response",
    "_agent_skill_selection_events_response",
    "_agent_skill_selection_feedback_response",
    "_context_evidence_response",
    "_governance_repository",
    "_persist_skill_selection_event",
]
