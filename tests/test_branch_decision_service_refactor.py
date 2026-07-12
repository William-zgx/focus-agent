from __future__ import annotations

from types import SimpleNamespace

import focus_agent.branch_decision.service as service_module
from focus_agent.branch_decision import BranchDecisionService
from focus_agent.branch_decision.service_decision_operations import (
    BranchDecisionServiceDecisionOperationsMixin,
)
from focus_agent.core.governance import (
    BranchDecisionAction,
    BranchDecisionEvent,
    BranchDecisionStatus,
)
from focus_agent.repositories.governance_repository import InMemoryGovernanceRepository


def test_decision_event_operations_preserve_public_api_and_timestamp_patch_seam(
    monkeypatch,
) -> None:
    repository = InMemoryGovernanceRepository()
    service = BranchDecisionService(
        settings=SimpleNamespace(),
        graph=SimpleNamespace(),
        governance_repository=repository,
    )
    event = BranchDecisionEvent(
        user_id="user-1",
        root_thread_id="root-1",
        source_thread_id="thread-1",
        action=BranchDecisionAction.SPLIT,
        score=0.8,
        threshold=0.7,
    )
    repository.save_branch_decision_event(event)
    monkeypatch.setattr(service_module, "_now_iso", lambda: "2030-01-02T03:04:05+00:00")

    dismissed = service.dismiss_decision(
        thread_id="thread-1",
        decision_id=event.decision_id,
        user_id="user-1",
        reason="not_now",
    )
    summary = service.summary_for_thread(thread_id="thread-1", user_id="user-1")

    assert BranchDecisionServiceDecisionOperationsMixin in BranchDecisionService.__mro__
    assert service.list_decisions(thread_id="thread-1", user_id="user-1") == [dismissed]
    assert dismissed.status == BranchDecisionStatus.DISMISSED
    assert dismissed.dismiss_reason == "not_now"
    assert dismissed.executed_at == "2030-01-02T03:04:05+00:00"
    assert summary.latest_decision == dismissed
    assert summary.dismissed_count == 1
