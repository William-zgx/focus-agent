from types import SimpleNamespace

import pytest

import focus_agent.services.governance as governance_module
from focus_agent.config import Settings
from focus_agent.core.governance import SkillSelectionEvent
from focus_agent.repositories.governance_repository import InMemoryGovernanceRepository
from focus_agent.repositories.postgres_governance_repository import PostgresGovernanceRepository
from focus_agent.services.governance import (
    GovernanceService,
    SkillSelectionNotFoundError,
    governance_service_for_runtime,
)


def test_governance_service_records_selection_and_feedback(monkeypatch) -> None:
    indexed = []
    monkeypatch.setattr(
        governance_module,
        "index_governance_feedback",
        lambda **kwargs: indexed.append(kwargs["item"]),
    )
    repository = InMemoryGovernanceRepository()
    service = GovernanceService(
        repository=repository,
        retrieval_index=object(),
        embedding_provider=object(),
    )
    event = SkillSelectionEvent(user_id="user-1")

    assert service.record_skill_selection(event) is event
    updated, feedback_event_id = service.record_skill_selection_feedback(
        selection_id=event.selection_id,
        user_id="user-1",
        feedback="useful",
        reason="matched",
        user_override={"skill_ids": ["plan"]},
    )

    feedback_events = repository.list_feedback_events(
        user_id="user-1", source_kind="skill_selection"
    )
    assert updated.feedback == "useful"
    assert repository.get_skill_selection_event(event.selection_id) == updated
    assert feedback_event_id == feedback_events[0].event_id
    assert feedback_events[0].metadata == {
        "reason": "matched",
        "user_override": {"skill_ids": ["plan"]},
    }
    assert indexed == [event, updated, feedback_events[0]]


def test_governance_service_can_disable_selection_logging() -> None:
    repository = InMemoryGovernanceRepository()
    service = GovernanceService(
        repository=repository,
        skill_selection_event_log_enabled=False,
    )

    assert service.record_skill_selection(SkillSelectionEvent(user_id="user-1")) is None
    assert repository.list_skill_selection_events(user_id="user-1") == []


def test_governance_service_hides_missing_and_other_users_selections() -> None:
    repository = InMemoryGovernanceRepository()
    other_user_event = repository.save_skill_selection_event(
        SkillSelectionEvent(user_id="other-user")
    )
    service = GovernanceService(repository=repository)

    for selection_id in (other_user_event, "missing-selection"):
        with pytest.raises(SkillSelectionNotFoundError):
            service.record_skill_selection_feedback(
                selection_id=selection_id,
                user_id="user-1",
                feedback="useful",
                reason=None,
                user_override={},
            )
    assert repository.list_feedback_events(user_id="user-1") == []


def test_governance_runtime_fallback_reuses_postgres_provider() -> None:
    provider = object()
    runtime = SimpleNamespace(
        settings=Settings(database_uri="postgresql://example/db"),
        postgres_connection_provider=provider,
    )

    service = governance_service_for_runtime(runtime)

    assert isinstance(service.repository, PostgresGovernanceRepository)
    assert service.repository.connection_provider is provider
    assert runtime.governance_repository is service.repository
    assert runtime.governance_service is service
    assert governance_service_for_runtime(runtime) is service
