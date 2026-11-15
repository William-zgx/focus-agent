from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from langgraph.store.memory import InMemoryStore

from focus_agent.engine.local_persistence_store import PersistentSQLiteStore
from focus_agent.services.attention import AttentionReviewConflictError, AttentionService
from focus_agent.storage.namespaces import attention_cursor_namespace


def _state() -> dict:
    return {
        "messages": [
            {"id": "m1", "type": "human", "content": "Investigate cache consistency"},
            {"id": "m2", "type": "ai", "content": "Initial result"},
        ],
        "tool_outcomes": [
            {
                "outcome_id": "outcome-1",
                "tool_name": "workspace_search",
                "status": "succeeded",
            }
        ],
        "branch_actions": [
            {
                "action_id": "action-1",
                "kind": "fork_child_branch",
                "status": "executed",
                "handoff_message": "Check invalidation ordering",
            }
        ],
        "interrupts": [],
        "task_outcome": {"status": "answered"},
    }


def _service(store=None) -> AttentionService:
    return AttentionService(store if store is not None else InMemoryStore())


def _snapshot(service: AttentionService, state: dict, *, user="user", tenant="tenant"):
    return service.get_snapshot(
        tenant_id=tenant,
        user_id=user,
        thread_id="thread",
        state=state,
    )


def _review(service: AttentionService, state: dict, *, user="user", tenant="tenant"):
    presented_cursor = _snapshot(service, state, user=user, tenant=tenant).current_cursor
    return service.review(
        tenant_id=tenant,
        user_id=user,
        thread_id="thread",
        state=state,
        presented_cursor=presented_cursor,
    )


def test_first_visit_is_quiet_and_review_is_idempotent():
    service = _service()
    state = _state()

    first = _snapshot(service, state)
    assert first.diff.first_visit is True
    assert first.diff.new_message_count == 0
    assert first.policy.level == "quiet"
    assert first.resume.goal == "Investigate cache consistency"
    assert first.current_cursor.last_message_id == "m2"

    reviewed = _review(service, state)
    reviewed_again = _review(service, state)
    assert reviewed.reviewed_at is not None
    assert reviewed_again.reviewed_at == reviewed.reviewed_at

    after = _snapshot(service, state)
    assert after.diff.first_visit is False
    assert after.diff.new_message_count == 0
    assert after.current_cursor.reviewed_at == reviewed.reviewed_at


def test_diff_counts_new_work_and_action_transitions_exactly_once():
    service = _service()
    state = _state()
    _review(service, state)

    state["messages"].append({"id": "m3", "type": "ai", "content": "New final answer"})
    state["tool_outcomes"].append(
        {"outcome_id": "outcome-2", "tool_name": "memory_save", "status": "failed"}
    )
    state["branch_actions"][0]["status"] = "pending"

    changed = _snapshot(service, state)
    assert changed.diff.new_message_count == 1
    assert changed.diff.new_outcome_count == 1
    assert changed.diff.new_failed_outcome_count == 1
    assert changed.diff.action_transition_count == 1
    assert changed.policy.level == "ask"
    assert changed.resume.next_action.source_id == "action-1"
    assert any(item.text == "New final answer" for item in changed.diff.highlights)

    _review(service, state)
    reviewed = _snapshot(service, state)
    assert reviewed.diff.new_message_count == 0
    assert reviewed.diff.new_outcome_count == 0
    assert reviewed.diff.action_transition_count == 0


def test_review_acknowledges_only_the_presented_snapshot():
    service = _service()
    state = _state()
    presented = _snapshot(service, state).current_cursor

    state["messages"].append({"id": "m3", "type": "ai", "content": "Arrived later"})
    reviewed = service.review(
        tenant_id="tenant",
        user_id="user",
        thread_id="thread",
        state=state,
        presented_cursor=presented,
    )

    assert reviewed.last_message_id == "m2"
    remaining = _snapshot(service, state)
    assert remaining.diff.new_message_count == 1
    assert remaining.diff.highlights[0].text == "Arrived later"


def test_missing_message_frontier_does_not_fabricate_message_diff():
    service = _service()
    _review(service, _state())
    state = _state()
    state["messages"] = [{"id": "replacement", "type": "ai", "content": "Replacement"}]

    snapshot = _snapshot(service, state)
    assert snapshot.diff.frontier_missing is True
    assert snapshot.diff.new_message_count == 0
    assert snapshot.diff.highlights == []


def test_review_rejects_a_frontier_that_is_not_in_the_current_thread():
    service = _service()
    state = _state()
    presented = _snapshot(service, state).current_cursor.model_copy(
        update={"last_message_id": "not-present"}
    )

    with pytest.raises(AttentionReviewConflictError):
        service.review(
            tenant_id="tenant",
            user_id="user",
            thread_id="thread",
            state=state,
            presented_cursor=presented,
        )


def test_pending_visible_action_outranks_failure_and_audit_only_is_ignored():
    service = _service()
    state = _state()
    state["task_outcome"] = {"status": "failed"}
    state["branch_actions"] = [
        {
            "action_id": "audit-only",
            "kind": "fork_child_branch",
            "status": "pending",
            "recommendation_user_visible": False,
        }
    ]
    assert _snapshot(service, state).policy.level == "notify"

    state["branch_actions"].append(
        {
            "action_id": "needs-review",
            "kind": "fork_child_branch",
            "status": "pending",
            "recommendation_user_visible": True,
            "handoff_message": "Review this option",
        }
    )
    snapshot = _snapshot(service, state)
    assert snapshot.policy.level == "ask"
    assert snapshot.policy.reasons[0].code == "branch_action_pending"
    assert snapshot.policy.reasons[0].source_ids == ["needs-review"]
    assert snapshot.resume.next_action.source_id == "needs-review"


def test_recovered_tool_failure_does_not_create_current_alert():
    service = _service()
    state = _state()
    state["tool_outcomes"].append({"outcome_id": "failed-then-recovered", "status": "failed"})
    assert _snapshot(service, state).policy.level == "quiet"

    state["task_outcome"] = {"status": "answered", "degraded_reason": "fallback"}
    assert _snapshot(service, state).policy.level == "notify"

    state["task_outcome"] = {"status": "failed"}
    snapshot = _snapshot(service, state)
    assert snapshot.policy.level == "notify"
    assert snapshot.resume.next_action.kind == "task_outcome"


def test_failed_branch_action_is_notify_even_with_successful_task_outcome():
    service = _service()
    state = _state()
    state["branch_actions"][0]["status"] = "failed"

    snapshot = _snapshot(service, state)
    assert snapshot.policy.level == "notify"
    assert snapshot.policy.reasons[0].code == "branch_action_failed"
    assert snapshot.resume.next_action.kind == "branch_action"


def test_out_of_order_review_does_not_move_cursor_backwards():
    service = _service()
    state = _state()
    older = _snapshot(service, state).current_cursor
    state["messages"].append({"id": "m3", "type": "ai", "content": "Newer answer"})
    newer = _snapshot(service, state).current_cursor

    service.review(
        tenant_id="tenant",
        user_id="user",
        thread_id="thread",
        state=state,
        presented_cursor=newer,
    )
    service.review(
        tenant_id="tenant",
        user_id="user",
        thread_id="thread",
        state=state,
        presented_cursor=older,
    )

    snapshot = _snapshot(service, state)
    assert snapshot.current_cursor.last_message_id == "m3"
    assert snapshot.diff.new_message_count == 0


def test_merge_decisions_and_pending_merge_are_distinguished():
    service = _service()
    state = _state()
    state["branch_meta"] = {"branch_id": "branch-1", "branch_status": "merged"}
    state["merge_decision"] = {
        "decision_id": "merge-1",
        "approved": True,
        "summary": "Approved cache policy",
    }

    decided = _snapshot(service, state)
    assert decided.resume.decisions[0].text == "Approved cache policy"
    assert decided.policy.level == "quiet"

    state["branch_meta"]["branch_status"] = "awaiting_merge_review"
    state["merge_decision"] = None
    state["merge_proposal"] = {"proposal_id": "merge-1", "summary": "Review cache policy"}
    pending = _snapshot(service, state)
    assert pending.policy.level == "ask"
    assert pending.resume.next_action.text == "Review cache policy"


def test_sqlite_cursor_survives_restart_and_isolates_principal_and_tenant(tmp_path):
    path = tmp_path / "attention.sqlite3"
    store = PersistentSQLiteStore(path)
    try:
        service = _service(store)
        state = _state()
        _review(service, state)
    finally:
        store.close()

    reopened = PersistentSQLiteStore(path)
    try:
        service = _service(reopened)
        assert _snapshot(service, _state()).diff.new_message_count == 0
        assert _snapshot(service, _state(), user="other").diff.first_visit is True
        assert _snapshot(service, _state(), tenant="other").diff.first_visit is True
    finally:
        reopened.close()


def test_branch_goal_and_interrupt_use_authoritative_sources():
    service = _service()
    state = _state()
    state["branch_meta"] = {"fork_brief": {"goal": "Verify the branch goal"}}
    state["interrupts"] = [{"interrupt_id": "approval-1", "tool_name": "workspace_write"}]

    snapshot = _snapshot(service, state)
    assert snapshot.resume.goal == "Verify the branch goal"
    assert snapshot.resume.next_action.source_id == "approval-1"
    assert snapshot.policy.level == "ask"
    assert snapshot.resume.next_action.kind == "interrupt"


def test_attention_namespace_supports_empty_tenant_and_periods_in_sqlite(tmp_path):
    namespace = attention_cursor_namespace("", "john.doe", "thread/with.periods")
    assert all(label and "." not in label for label in namespace)
    store = PersistentSQLiteStore(tmp_path / "attention.sqlite3")
    try:
        service = AttentionService(store)
        state = _state()
        service.review(
            tenant_id="",
            user_id="john.doe",
            thread_id="thread/with.periods",
            state=state,
            presented_cursor=service.get_snapshot(
                tenant_id="",
                user_id="john.doe",
                thread_id="thread/with.periods",
                state=state,
            ).current_cursor,
        )
        after = service.get_snapshot(
            tenant_id="",
            user_id="john.doe",
            thread_id="thread/with.periods",
            state=state,
        )
        assert after.diff.first_visit is False
    finally:
        store.close()


def test_goal_prefers_durable_goal_over_retained_history():
    service = _service()
    state = _state()
    state["active_goal"] = "Durable root goal"
    state["messages"][0]["content"] = "Later retained user message"

    snapshot = _snapshot(service, state)
    assert snapshot.resume.goal == "Durable root goal"


def test_handoff_timeout_is_notify_with_run_evidence():
    service = _service()
    state = _state()
    state["branch_decision_summary"] = {
        "latest_decision": {
            "decision_id": "decision-1",
            "error": "",
            "metadata": {"handoff_run_id": "run-1", "handoff_run_status": "timeout"},
        }
    }

    snapshot = _snapshot(service, state)
    assert snapshot.policy.level == "notify"
    assert snapshot.policy.reasons[0].code == "branch_handoff_failed"
    assert snapshot.policy.reasons[0].source_ids == ["run-1"]
    evidence = next(item for item in snapshot.resume.evidence if item.kind == "branch_handoff")
    assert evidence.run_id == "run-1"


def test_concurrent_reviews_cannot_move_cursor_backwards():
    store = InMemoryStore()
    older_service = AttentionService(store)
    newer_service = AttentionService(store)
    state = _state()
    older = _snapshot(older_service, state).current_cursor
    state["messages"].append({"id": "m3", "type": "ai", "content": "Newer answer"})
    newer = _snapshot(newer_service, state).current_cursor

    def review(service, presented):
        return service.review(
            tenant_id="tenant",
            user_id="user",
            thread_id="thread",
            state=state,
            presented_cursor=presented,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        pool.submit(review, newer_service, newer)
        pool.submit(review, older_service, older)

    snapshot = _snapshot(older_service, state)
    assert snapshot.current_cursor.last_message_id == "m3"
    assert snapshot.diff.new_message_count == 0


def test_action_status_cursor_is_bounded():
    service = _service()
    state = _state()
    state["branch_actions"] = [
        {"action_id": f"action-{index}", "status": "executed"} for index in range(513)
    ]

    reviewed = _review(service, state)
    assert len(reviewed.action_statuses) == 512
