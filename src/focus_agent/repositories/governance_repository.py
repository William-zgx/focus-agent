from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import Protocol

from focus_agent.core.governance import (
    ContextMemoryEvidence,
    FeedbackEvent,
    SkillPreference,
    SkillSelectionEvent,
)


def _format_time() -> str:
    return datetime.now(UTC).isoformat()


class ContextMemoryEvidenceRepository(Protocol):
    def save_context_evidence(self, evidence: ContextMemoryEvidence) -> str: ...

    def list_context_evidence(
        self,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        memory_id: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[ContextMemoryEvidence]: ...


class SkillOperationsRepository(Protocol):
    def save_skill_selection_event(self, event: SkillSelectionEvent) -> str: ...

    def get_skill_selection_event(self, selection_id: str) -> SkillSelectionEvent | None: ...

    def list_skill_selection_events(
        self,
        *,
        user_id: str | None = None,
        skill_id: str | None = None,
        limit: int = 50,
    ) -> list[SkillSelectionEvent]: ...

    def update_skill_selection_feedback(
        self,
        *,
        selection_id: str,
        feedback: str,
        reason: str | None = None,
        user_override: dict[str, object] | None = None,
    ) -> SkillSelectionEvent | None: ...

    def save_skill_preference(self, preference: SkillPreference) -> SkillPreference: ...

    def get_skill_preference(self, *, user_id: str, skill_id: str) -> SkillPreference | None: ...

    def list_skill_preferences(self, *, user_id: str) -> list[SkillPreference]: ...


class FeedbackRepository(Protocol):
    def save_feedback_event(self, event: FeedbackEvent) -> str: ...


class GovernanceRepository(
    ContextMemoryEvidenceRepository,
    SkillOperationsRepository,
    FeedbackRepository,
    Protocol,
):
    pass


class InMemoryGovernanceRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._context_evidence: dict[str, ContextMemoryEvidence] = {}
        self._skill_events: dict[str, SkillSelectionEvent] = {}
        self._skill_preferences: dict[tuple[str, str], SkillPreference] = {}
        self._feedback_events: dict[str, FeedbackEvent] = {}

    def save_context_evidence(self, evidence: ContextMemoryEvidence) -> str:
        with self._lock:
            self._context_evidence[evidence.evidence_id] = evidence
        return evidence.evidence_id

    def list_context_evidence(
        self,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
        memory_id: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[ContextMemoryEvidence]:
        with self._lock:
            items = list(self._context_evidence.values())
        if thread_id is not None:
            items = [item for item in items if item.thread_id == thread_id]
        if turn_id is not None:
            items = [item for item in items if item.turn_id == turn_id]
        if memory_id is not None:
            items = [item for item in items if memory_id in item.memory_ids]
        if user_id is not None:
            items = [item for item in items if item.user_id in {None, user_id}]
        items.sort(key=lambda item: (item.created_at, item.evidence_id), reverse=True)
        return items[: max(0, limit)]

    def save_skill_selection_event(self, event: SkillSelectionEvent) -> str:
        with self._lock:
            self._skill_events[event.selection_id] = event
        return event.selection_id

    def get_skill_selection_event(self, selection_id: str) -> SkillSelectionEvent | None:
        with self._lock:
            return self._skill_events.get(selection_id)

    def list_skill_selection_events(
        self,
        *,
        user_id: str | None = None,
        skill_id: str | None = None,
        limit: int = 50,
    ) -> list[SkillSelectionEvent]:
        with self._lock:
            items = list(self._skill_events.values())
        if user_id is not None:
            items = [item for item in items if item.user_id in {None, user_id}]
        if skill_id is not None:
            items = [item for item in items if skill_id in item.activated_skill_ids]
        items.sort(key=lambda item: (item.created_at, item.selection_id), reverse=True)
        return items[: max(0, limit)]

    def update_skill_selection_feedback(
        self,
        *,
        selection_id: str,
        feedback: str,
        reason: str | None = None,
        user_override: dict[str, object] | None = None,
    ) -> SkillSelectionEvent | None:
        with self._lock:
            event = self._skill_events.get(selection_id)
            if event is None:
                return None
            updated = event.model_copy(
                update={
                    "feedback": feedback,
                    "feedback_reason": reason,
                    "user_override": dict(user_override or event.user_override),
                    "updated_at": _format_time(),
                }
            )
            self._skill_events[selection_id] = updated
            return updated

    def save_skill_preference(self, preference: SkillPreference) -> SkillPreference:
        with self._lock:
            existing = self._skill_preferences.get((preference.user_id, preference.skill_id))
            if existing is not None:
                preference = preference.model_copy(
                    update={
                        "preference_id": existing.preference_id,
                        "created_at": existing.created_at,
                    }
                )
            self._skill_preferences[(preference.user_id, preference.skill_id)] = preference
        return preference

    def get_skill_preference(self, *, user_id: str, skill_id: str) -> SkillPreference | None:
        with self._lock:
            return self._skill_preferences.get((user_id, skill_id))

    def list_skill_preferences(self, *, user_id: str) -> list[SkillPreference]:
        with self._lock:
            items = [
                item
                for (owner_id, _skill_id), item in self._skill_preferences.items()
                if owner_id == user_id
            ]
        items.sort(key=lambda item: (item.updated_at, item.skill_id), reverse=True)
        return items

    def save_feedback_event(self, event: FeedbackEvent) -> str:
        with self._lock:
            self._feedback_events[event.event_id] = event
        return event.event_id


__all__ = [
    "ContextMemoryEvidenceRepository",
    "FeedbackRepository",
    "GovernanceRepository",
    "InMemoryGovernanceRepository",
    "SkillOperationsRepository",
]
