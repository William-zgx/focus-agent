from __future__ import annotations

from dataclasses import dataclass

from focus_agent.core.governance import FeedbackEvent, SkillSelectionEvent
from focus_agent.repositories.governance_repository import (
    GovernanceRepository,
    InMemoryGovernanceRepository,
)
from focus_agent.retrieval.governance_feedback import index_governance_feedback


class SkillSelectionNotFoundError(LookupError):
    pass


@dataclass(slots=True)
class GovernanceService:
    repository: GovernanceRepository
    skill_selection_event_log_enabled: bool = True
    retrieval_index: object | None = None
    embedding_provider: object | None = None

    def record_skill_selection(self, event: SkillSelectionEvent) -> SkillSelectionEvent | None:
        if not self.skill_selection_event_log_enabled:
            return None
        self.repository.save_skill_selection_event(event)
        self._index_best_effort(event)
        return event

    def record_skill_selection_feedback(
        self,
        *,
        selection_id: str,
        user_id: str | None,
        feedback: str,
        reason: str | None,
        user_override: dict[str, object],
    ) -> tuple[SkillSelectionEvent, str]:
        existing = self.repository.get_skill_selection_event(selection_id)
        if existing is None or existing.user_id not in {None, user_id}:
            raise SkillSelectionNotFoundError(selection_id)
        updated = self.repository.update_skill_selection_feedback(
            selection_id=selection_id,
            feedback=feedback,
            reason=reason,
            user_override=dict(user_override),
        )
        if updated is None:
            raise SkillSelectionNotFoundError(selection_id)
        self._index_best_effort(updated)
        feedback_event = FeedbackEvent(
            user_id=user_id,
            source_kind="skill_selection",
            source_id=selection_id,
            sentiment=feedback,
            category="skill_feedback",
            metadata={"reason": reason, "user_override": dict(user_override)},
        )
        feedback_event_id = self.repository.save_feedback_event(feedback_event)
        self._index_best_effort(feedback_event)
        return updated, feedback_event_id

    def _index_best_effort(self, item: object) -> None:
        try:
            index_governance_feedback(
                retrieval_index=self.retrieval_index,
                embedding_provider=self.embedding_provider,
                item=item,
            )
        except Exception:  # noqa: BLE001
            return


def governance_service_for_runtime(runtime: object) -> GovernanceService:
    service = getattr(runtime, "governance_service", None)
    if service is not None:
        return service

    repository = getattr(runtime, "governance_repository", None)
    if repository is None:
        repository = getattr(runtime, "context_memory_evidence_repository", None)
    if repository is None:
        settings = getattr(runtime, "settings", None)
        database_uri = getattr(settings, "database_uri", None)
        if database_uri:
            from focus_agent.repositories.postgres_governance_repository import (
                PostgresGovernanceRepository,
            )

            repository = PostgresGovernanceRepository(
                str(database_uri),
                connection_provider=getattr(runtime, "postgres_connection_provider", None),
            )
        else:
            repository = InMemoryGovernanceRepository()
        try:
            runtime.governance_repository = repository
        except Exception:  # noqa: BLE001 - tests may use immutable runtime stubs.
            pass

    settings = getattr(runtime, "settings", None)
    service = GovernanceService(
        repository=repository,
        skill_selection_event_log_enabled=bool(
            getattr(settings, "skill_selection_event_log_enabled", True)
        ),
        retrieval_index=getattr(runtime, "retrieval_index", None),
        embedding_provider=getattr(runtime, "memory_embedding_provider", None),
    )
    try:
        runtime.governance_service = service
    except Exception:  # noqa: BLE001 - tests may use immutable runtime stubs.
        pass
    return service


__all__ = [
    "GovernanceService",
    "SkillSelectionNotFoundError",
    "governance_service_for_runtime",
]
