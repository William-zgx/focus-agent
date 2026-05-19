from __future__ import annotations

import psycopg

from focus_agent.core.governance import (
    BranchDecisionAction,
    BranchDecisionEvent,
    BranchDecisionStatus,
)
from focus_agent.repositories.governance_repository import InMemoryGovernanceRepository
from focus_agent.repositories.postgres_governance_repository import PostgresGovernanceRepository
from focus_agent.repositories.postgres_schema import SCHEMA_VERSION
from focus_agent.repositories.postgres_schema_migrations import _MIGRATIONS


def test_in_memory_branch_decision_repository_round_trips_and_filters() -> None:
    repository = InMemoryGovernanceRepository()
    event = BranchDecisionEvent(
        user_id="u-1",
        root_thread_id="root-1",
        source_thread_id="thread-1",
        action=BranchDecisionAction.SPLIT,
        status=BranchDecisionStatus.SHADOWED,
        score=0.82,
        threshold=0.70,
        idempotency_key="turn-1",
    )

    assert repository.save_branch_decision_event(event) == event.decision_id
    assert (
        repository.save_branch_decision_event(event.model_copy(update={"decision_id": "other"}))
        == event.decision_id
    )

    assert repository.get_branch_decision_event(event.decision_id) == event
    assert repository.list_branch_decision_events(user_id="u-1", source_thread_id="thread-1") == [
        event
    ]
    assert repository.list_branch_decision_events(status="shadowed") == [event]
    assert repository.list_branch_decision_events(action="split") == [event]


def test_in_memory_branch_decision_repository_updates_event() -> None:
    repository = InMemoryGovernanceRepository()
    event = BranchDecisionEvent(
        root_thread_id="root-1",
        source_thread_id="thread-1",
        action=BranchDecisionAction.SPLIT,
    )
    repository.save_branch_decision_event(event)

    updated = repository.update_branch_decision_event(
        event.model_copy(update={"status": BranchDecisionStatus.DISMISSED})
    )

    assert updated.status == BranchDecisionStatus.DISMISSED
    assert (
        repository.get_branch_decision_event(event.decision_id).status
        == BranchDecisionStatus.DISMISSED
    )


class _PostgresDecisionSaveState:
    def __init__(
        self,
        existing_decision_id: str | None,
        *,
        raise_unique_on_insert: bool = False,
        select_decision_ids: list[str | None] | None = None,
    ) -> None:
        self.existing_decision_id = existing_decision_id
        self.raise_unique_on_insert = raise_unique_on_insert
        self.select_decision_ids = select_decision_ids
        self.upsert_params: list[dict[str, object]] = []


class _PostgresDecisionCursor:
    def __init__(self, state: _PostgresDecisionSaveState) -> None:
        self.state = state
        self._row: dict[str, object] | None = None

    def __enter__(self) -> _PostgresDecisionCursor:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback

    def execute(self, sql: str, params: object) -> None:
        if "SELECT decision_id FROM focus_branch_decision_events" in sql:
            selected_decision_id = (
                self.state.select_decision_ids.pop(0)
                if self.state.select_decision_ids
                else self.state.existing_decision_id
            )
            self._row = (
                {"decision_id": selected_decision_id} if selected_decision_id is not None else None
            )
            return
        if "INSERT INTO focus_branch_decision_events" in sql:
            assert isinstance(params, dict)
            if self.state.raise_unique_on_insert:
                raise psycopg.errors.UniqueViolation("duplicate idempotency key")
            self.state.upsert_params.append(params)
            return
        raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self) -> dict[str, object] | None:
        return self._row


class _PostgresDecisionConnection:
    def __init__(self, state: _PostgresDecisionSaveState) -> None:
        self.state = state

    def __enter__(self) -> _PostgresDecisionConnection:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback

    def cursor(self) -> _PostgresDecisionCursor:
        return _PostgresDecisionCursor(self.state)


def test_postgres_branch_decision_save_updates_same_idempotent_event(monkeypatch) -> None:
    repository = PostgresGovernanceRepository("postgresql://example")
    state = _PostgresDecisionSaveState(existing_decision_id="decision-1")
    monkeypatch.setattr(repository, "_connect", lambda: _PostgresDecisionConnection(state))
    event = BranchDecisionEvent(
        decision_id="decision-1",
        root_thread_id="root-1",
        source_thread_id="thread-1",
        action=BranchDecisionAction.SPLIT,
        status=BranchDecisionStatus.PROMOTED,
        idempotency_key="turn-1",
    )

    assert repository.save_branch_decision_event(event) == "decision-1"

    assert len(state.upsert_params) == 1
    assert state.upsert_params[0]["status"] == "promoted"


def test_postgres_branch_decision_save_dedupes_different_idempotent_event(monkeypatch) -> None:
    repository = PostgresGovernanceRepository("postgresql://example")
    state = _PostgresDecisionSaveState(existing_decision_id="decision-1")
    monkeypatch.setattr(repository, "_connect", lambda: _PostgresDecisionConnection(state))
    event = BranchDecisionEvent(
        decision_id="decision-2",
        root_thread_id="root-1",
        source_thread_id="thread-1",
        action=BranchDecisionAction.SPLIT,
        status=BranchDecisionStatus.PROMOTED,
        idempotency_key="turn-1",
    )

    assert repository.save_branch_decision_event(event) == "decision-1"

    assert state.upsert_params == []


def test_postgres_branch_decision_save_recovers_racing_idempotent_insert(monkeypatch) -> None:
    repository = PostgresGovernanceRepository("postgresql://example")
    state = _PostgresDecisionSaveState(
        existing_decision_id=None,
        raise_unique_on_insert=True,
        select_decision_ids=[None, "decision-1"],
    )
    monkeypatch.setattr(repository, "_connect", lambda: _PostgresDecisionConnection(state))
    event = BranchDecisionEvent(
        decision_id="decision-2",
        root_thread_id="root-1",
        source_thread_id="thread-1",
        action=BranchDecisionAction.SPLIT,
        status=BranchDecisionStatus.PROMOTED,
        idempotency_key="turn-1",
    )

    assert repository.save_branch_decision_event(event) == "decision-1"


def test_postgres_branch_decision_update_returns_deduped_existing_event(monkeypatch) -> None:
    repository = PostgresGovernanceRepository("postgresql://example")
    existing = BranchDecisionEvent(
        decision_id="decision-1",
        root_thread_id="root-1",
        source_thread_id="thread-1",
        action=BranchDecisionAction.SPLIT,
        status=BranchDecisionStatus.SUGGESTED,
        idempotency_key="turn-1",
    )
    event = existing.model_copy(
        update={
            "decision_id": "decision-2",
            "status": BranchDecisionStatus.PROMOTED,
        }
    )
    monkeypatch.setattr(repository, "save_branch_decision_event", lambda _event: "decision-1")
    monkeypatch.setattr(
        repository,
        "get_branch_decision_event",
        lambda decision_id: existing if decision_id == "decision-1" else None,
    )

    updated = repository.update_branch_decision_event(event)

    assert updated.decision_id == "decision-1"
    assert updated.status == BranchDecisionStatus.SUGGESTED


def test_postgres_schema_registers_branch_decision_migration() -> None:
    assert SCHEMA_VERSION == 18
    versions = [version for version, _migration in _MIGRATIONS]
    assert versions[-1] == 18
