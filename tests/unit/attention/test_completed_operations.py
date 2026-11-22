from __future__ import annotations

from langgraph.store.memory import InMemoryStore

from focus_agent.services.attention import AttentionService


def test_resume_completed_operations_preserve_identity_version_and_cache_flags():
    service = AttentionService(InMemoryStore())
    snapshot = service.get_snapshot(
        tenant_id="tenant",
        user_id="user",
        thread_id="thread",
        state={
            "messages": [{"id": "m1", "type": "human", "content": "Continue"}],
            "tool_outcomes": [
                {
                    "outcome_id": "call-1:1",
                    "tool_call_id": "call-1",
                    "tool_name": "record_operation",
                    "status": "succeeded",
                    "turn_id": "turn-1",
                    "operation_fingerprint": "a" * 64,
                    "operation_fingerprint_redacted_args": True,
                    "side_effect_serialized": True,
                    "operation_id": "update_address",
                    "execution_version": "v1",
                    "superseded_by": "v2",
                },
                {
                    "outcome_id": "call-1:1",
                    "tool_call_id": "call-1",
                    "tool_name": "record_operation",
                    "status": "recovered",
                    "turn_id": "turn-2",
                    "cache_hit": True,
                    "deduplicated": True,
                    "side_effect_serialized": True,
                    "operation_fingerprint": "a" * 64,
                },
                {"outcome_id": "failed-1", "tool_name": "record_operation", "status": "failed"},
                {"outcome_id": "skipped-1", "tool_name": "record_operation", "status": "skipped"},
            ],
            "task_outcome": {"status": "answered"},
        },
    )

    completed = snapshot.resume.completed_operations
    assert len(completed) == 2
    assert snapshot.resume.completed_operations_total == 2
    first, second = completed
    assert first.outcome_id == "call-1:1"
    assert first.tool_call_id == "call-1"
    assert first.tool_name == "record_operation"
    assert first.turn_id == "turn-2"
    assert first.operation_fingerprint == "a" * 64
    assert first.cache_hit is True
    assert first.deduplicated is True
    assert first.operation_id is None
    assert first.execution_version is None
    assert first.superseded_by is None
    assert second.operation_id == "update_address"
    assert second.execution_version == "v1"
    assert second.superseded_by == "v2"
    assert second.turn_id == "turn-1"
    assert "args" not in first.model_dump()
    assert "args" not in second.model_dump()


def test_completed_operation_flags_do_not_coerce_string_false_to_true():
    snapshot = AttentionService(InMemoryStore()).get_snapshot(
        tenant_id="tenant",
        user_id="user",
        thread_id="thread",
        state={
            "messages": [{"id": "m1", "type": "human", "content": "Continue"}],
            "tool_outcomes": [
                {
                    "outcome_id": "call-1:1",
                    "tool_call_id": "call-1",
                    "tool_name": "record_operation",
                    "status": "succeeded",
                    "side_effect_serialized": True,
                    "operation_fingerprint": "a" * 64,
                    "operation_fingerprint_redacted_args": "false",
                    "cache_hit": "false",
                    "deduplicated": "false",
                }
            ],
            "task_outcome": {"status": "answered"},
        },
    )

    operation = snapshot.resume.completed_operations[0]
    assert operation.operation_fingerprint_redacted_args is False
    assert operation.cache_hit is False
    assert operation.deduplicated is False


def test_resume_execution_uses_only_explicit_canonical_version_metadata():
    snapshot = AttentionService(InMemoryStore()).get_snapshot(
        tenant_id="tenant",
        user_id="user",
        thread_id="thread",
        state={
            "messages": [{"id": "m1", "type": "human", "content": "Continue"}],
            "task_outcome": {
                "status": "answered",
                "execution_version": "v2",
                "superseded_execution_versions": ["v1", "v0"],
            },
        },
    )
    assert snapshot.resume.execution is not None
    assert snapshot.resume.execution.version == "v2"
    assert snapshot.resume.execution.superseded_versions == ["v1", "v0"]

    missing = AttentionService(InMemoryStore()).get_snapshot(
        tenant_id="tenant",
        user_id="user",
        thread_id="thread",
        state={
            "messages": [{"id": "m1", "type": "human", "content": "Continue"}],
            "task_outcome": {"status": "answered"},
        },
    )
    assert missing.resume.execution is None


def test_completed_operations_are_bounded_newest_first_without_outcome_id_dedupe():
    outcomes = [
        {
            "outcome_id": "shared:1",
            "tool_call_id": "shared",
            "tool_name": "record_operation",
            "status": "succeeded",
            "side_effect_serialized": True,
            "turn_id": f"turn-{index}",
            "operation_fingerprint": f"{index:064x}",
        }
        for index in range(34)
    ]
    snapshot = AttentionService(InMemoryStore()).get_snapshot(
        tenant_id="tenant",
        user_id="user",
        thread_id="thread",
        state={
            "messages": [{"id": "m1", "type": "human", "content": "Continue"}],
            "tool_outcomes": outcomes,
            "task_outcome": {"status": "answered"},
        },
    )

    assert snapshot.resume.completed_operations_total == 34
    assert len(snapshot.resume.completed_operations) == 32
    assert snapshot.resume.completed_operations[0].turn_id == "turn-33"
    assert snapshot.resume.completed_operations[-1].turn_id == "turn-2"
    assert len({item.outcome_id for item in snapshot.resume.completed_operations}) == 1
