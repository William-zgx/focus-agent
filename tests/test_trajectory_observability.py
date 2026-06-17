from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.core.state import make_agent_state_record
from focus_agent.observability.tracing import build_trace_correlation
from focus_agent.observability.trajectory import (
    build_turn_trajectory_record,
    extract_trajectory_steps,
    utc_now,
)
from focus_agent.repositories.postgres_trajectory_repository import PostgresTrajectoryRepository


def test_extract_trajectory_steps_preserves_runtime_metadata():
    steps = extract_trajectory_steps(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tool-1",
                        "name": "web_search",
                        "args": {"query": "focus agent"},
                    }
                ],
            ),
            ToolMessage(
                content="search result",
                tool_call_id="tool-1",
                artifact={
                    "runtime": {
                        "cache_hit": True,
                        "fallback_used": True,
                        "fallback_group": "web_search",
                        "parallel_batch_size": 2,
                    }
                },
            ),
        ],
        observation_max_chars=100,
    )

    assert len(steps) == 1
    assert steps[0].tool == "web_search"
    assert steps[0].args == {"query": "focus agent"}
    assert steps[0].observation == "search result"
    assert steps[0].cache_hit is True
    assert steps[0].fallback_used is True
    assert steps[0].fallback_group == "web_search"
    assert steps[0].parallel_batch_size == 2


def test_build_turn_trajectory_record_uses_only_current_turn_messages():
    started = utc_now()
    finished = started + timedelta(milliseconds=25)
    trace_correlation = build_trace_correlation(
        settings=SimpleNamespace(
            app_version="1.2.3",
            app_environment="staging",
            deployment_name="focus-agent-blue",
        ),
        request_id="req-123",
    )
    record = build_turn_trajectory_record(
        thread_id="thread-1",
        user_id="owner-1",
        root_thread_id="root-1",
        kind="chat.turn",
        status="succeeded",
        final_values={
            "messages": [
                AIMessage(content="old answer"),
                HumanMessage(content="read README"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "tool-1",
                            "name": "read_file",
                            "args": {"path": "README.md"},
                        }
                    ],
                ),
                ToolMessage(content="abcdef", tool_call_id="tool-1"),
                AIMessage(content="done"),
            ],
            "llm_calls": 3,
            "selected_model": "openai:gpt-4.1-mini",
            "selected_thinking_mode": "disabled",
            "task_brief": "read README",
        },
        initial_message_count=1,
        initial_llm_calls=1,
        started_at=started,
        finished_at=finished,
        trace_correlation=trace_correlation,
        observation_max_chars=3,
        answer_max_chars=4,
    )

    assert record.root_thread_id == "root-1"
    assert record.user_id_hash != "owner-1"
    assert record.request_id == "req-123"
    assert record.trace_id
    assert record.root_span_id
    assert record.environment == "staging"
    assert record.deployment == "focus-agent-blue"
    assert record.app_version == "1.2.3"
    assert record.user_message == "read README"
    assert record.answer == "done"
    assert record.metrics["llm_calls"] == 2
    assert record.metrics["tool_calls"] == 1
    assert record.trajectory[0].observation == "abc"
    assert record.trajectory[0].observation_truncated is True


def test_failed_turn_trajectory_does_not_fallback_to_old_answer():
    started = utc_now()
    record = build_turn_trajectory_record(
        thread_id="thread-1",
        user_id="owner-1",
        root_thread_id="root-1",
        kind="chat.turn",
        status="failed",
        final_values={
            "messages": [
                HumanMessage(content="old question"),
                AIMessage(content="old answer"),
                HumanMessage(content="new question"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "run_workspace_command",
                            "args": {"command": ["python3", "scripts/stocks_client.py"]},
                        }
                    ],
                ),
            ],
            "llm_calls": 3,
            "task_brief": "new question",
        },
        initial_message_count=2,
        initial_llm_calls=2,
        started_at=started,
        finished_at=started + timedelta(milliseconds=10),
        error="insufficient tool messages following tool_calls",
    )

    assert record.answer is None
    assert record.error == "insufficient tool messages following tool_calls"
    assert record.user_message == "new question"


def test_interrupted_success_turn_trajectory_does_not_fallback_to_old_answer():
    started = utc_now()
    record = build_turn_trajectory_record(
        thread_id="thread-1",
        user_id="owner-1",
        root_thread_id="root-1",
        kind="chat.turn",
        status="succeeded",
        final_values={
            "messages": [
                HumanMessage(content="old question"),
                AIMessage(content="old answer"),
                HumanMessage(content="new question"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "run_workspace_command",
                            "args": {"command": ["python3", "scripts/stocks_client.py"]},
                        }
                    ],
                ),
            ],
            "llm_calls": 3,
            "task_brief": "new question",
        },
        initial_message_count=2,
        initial_llm_calls=2,
        started_at=started,
        finished_at=started + timedelta(milliseconds=10),
    )

    assert record.answer is None
    assert record.user_message == "new question"


def test_build_turn_trajectory_record_hides_process_narration_answer():
    started = utc_now()
    record = build_turn_trajectory_record(
        thread_id="thread-1",
        user_id="owner-1",
        root_thread_id="root-1",
        kind="chat.turn",
        status="succeeded",
        final_values={
            "messages": [
                HumanMessage(content="search"),
                AIMessage(content="Let me fetch one more source first."),
                AIMessage(content="Let me produce the final answer. Final answer: 最终答案。"),
            ],
            "llm_calls": 2,
        },
        initial_message_count=0,
        initial_llm_calls=0,
        started_at=started,
        finished_at=started + timedelta(milliseconds=10),
    )

    assert record.answer == "最终答案。"


def test_build_turn_trajectory_record_mirrors_governance_records_to_plan_meta():
    started = utc_now()
    record = build_turn_trajectory_record(
        thread_id="thread-1",
        user_id="owner-1",
        root_thread_id="root-1",
        kind="chat.turn",
        status="succeeded",
        final_values={
            "messages": [HumanMessage(content="route tools"), AIMessage(content="done")],
            "llm_calls": 1,
            "tool_route_plan": {"enabled": True, "denied_tools": ["legacy_tool"], "enforce": False},
            "governance_records": [
                make_agent_state_record(
                    "tool_route_plan",
                    {"enabled": True, "denied_tools": ["write_text_artifact"], "enforce": True},
                    source="test",
                )
            ],
        },
        initial_message_count=0,
        initial_llm_calls=0,
        started_at=started,
        finished_at=started + timedelta(milliseconds=5),
    )

    assert record.plan_meta["tool_route_plan"]["denied_tools"] == ["write_text_artifact"]
    assert record.plan_meta["governance_records"][0]["name"] == "tool_route_plan"
    assert record.plan_meta["governance_records"][0]["schema_version"] == 2
    assert record.metrics["tool_router_denied"] == 1
    assert record.metrics["tool_router_enforced"] == 1


def test_build_turn_trajectory_record_uses_descriptor_metrics_and_legacy_fallback():
    started = utc_now()
    record = build_turn_trajectory_record(
        thread_id="thread-1",
        user_id="owner-1",
        root_thread_id="root-1",
        kind="chat.turn",
        status="succeeded",
        final_values={
            "messages": [HumanMessage(content="governance"), AIMessage(content="done")],
            "llm_calls": 1,
            "tool_route_plan": {"enabled": True, "denied_tools": ["legacy_tool"], "enforce": True},
            "agent_task_ledger": {"tasks": [{"task_id": "task-1"}, {"task_id": "task-2"}]},
            "delegated_artifacts": [{"artifact_id": "artifact-1"}],
        },
        initial_message_count=0,
        initial_llm_calls=0,
        started_at=started,
        finished_at=started + timedelta(milliseconds=5),
    )

    assert record.plan_meta["tool_route_plan"]["denied_tools"] == ["legacy_tool"]
    assert record.metrics["tool_router_denied"] == 1
    assert record.metrics["tool_router_enforced"] == 1
    assert record.metrics["agent_task_ledger_tasks"] == 2
    assert record.metrics["delegated_artifacts"] == 1


def test_build_turn_trajectory_record_includes_tool_approval_governance_record():
    started = utc_now()
    approval_record = make_agent_state_record(
        "tool_approval_decision",
        {
            "kind": "tool_approval",
            "tool_name": "write_file",
            "tool_call_id": "call-approval",
            "args": {"path": "README.md"},
            "risk_level": "high",
            "approved": False,
            "decision": "denied",
        },
        source="tool_executor:call-approval",
        metadata={"tool_call_id": "call-approval"},
        request_id="req-approval",
        actor="tool_executor",
    )

    record = build_turn_trajectory_record(
        thread_id="thread-1",
        user_id="owner-1",
        root_thread_id="root-1",
        kind="chat.resume",
        status="succeeded",
        final_values={
            "messages": [HumanMessage(content="resume approval"), AIMessage(content="done")],
            "llm_calls": 1,
            "governance_records": [approval_record],
        },
        initial_message_count=0,
        initial_llm_calls=0,
        started_at=started,
        finished_at=started + timedelta(milliseconds=5),
    )

    [stored_record] = record.plan_meta["governance_records"]
    assert stored_record["name"] == "tool_approval_decision"
    assert stored_record["payload"]["approved"] is False
    assert stored_record["payload"]["tool_call_id"] == "call-approval"
    assert stored_record["metadata"]["tool_call_id"] == "call-approval"
    assert stored_record["request_id"] == "req-approval"
    assert stored_record["actor"] == "tool_executor"


def test_postgres_trajectory_repository_executes_setup_and_insert(monkeypatch):
    executed: list[tuple[str, object]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.repositories.postgres_trajectory_repository.psycopg.connect",
        lambda uri, **kwargs: FakeConnection(),
    )

    repo = PostgresTrajectoryRepository("postgresql://example")
    repo.setup()
    record = build_turn_trajectory_record(
        thread_id="thread-1",
        user_id="owner-1",
        root_thread_id="root-1",
        kind="chat.turn",
        status="succeeded",
        final_values={
            "messages": [HumanMessage(content="hi"), AIMessage(content="hello")],
            "llm_calls": 1,
        },
        initial_message_count=0,
        initial_llm_calls=0,
        started_at=utc_now(),
        finished_at=utc_now(),
        trace_correlation=build_trace_correlation(
            settings=SimpleNamespace(
                app_version="1.2.3",
                app_environment="production",
                deployment_name="focus-agent-prod",
            ),
            request_id="req-setup",
        ),
    )
    repo.record_turn(record)

    statements = [sql for sql, _ in executed]
    assert any("CREATE TABLE IF NOT EXISTS focus_trajectory_turns" in sql for sql in statements)
    assert any("CREATE TABLE IF NOT EXISTS focus_trajectory_steps" in sql for sql in statements)
    assert any("ALTER TABLE focus_trajectory_turns" in sql for sql in statements)
    assert any("INSERT INTO focus_trajectory_turns" in sql for sql in statements)
    insert_params = next(
        params for sql, params in executed if "INSERT INTO focus_trajectory_turns" in sql
    )
    assert insert_params["request_id"] == "req-setup"
    assert insert_params["trace_id"]


def test_postgres_trajectory_repository_accepts_cli_style_filters(monkeypatch):
    executed: list[tuple[str, Any]] = []

    class FakeCursor:
        def __init__(self):
            self._rows = [
                {
                    "id": "turn-1",
                    "schema_version": 1,
                    "kind": "chat.turn",
                    "status": "failed",
                    "thread_id": "thread-1",
                    "root_thread_id": "root-1",
                    "request_id": "req-1",
                    "trace_id": "trace-1",
                    "root_span_id": "span-1",
                    "environment": "staging",
                    "deployment": "focus-agent-blue",
                    "app_version": "1.2.3",
                    "parent_thread_id": None,
                    "branch_id": None,
                    "branch_role": "executor",
                    "user_id_hash": "hashed",
                    "scene": "long_dialog_research",
                    "turn_index": 2,
                    "task_brief": "search docs",
                    "user_message": "search docs",
                    "answer": "done",
                    "selected_model": "openai:gpt-4.1-mini",
                    "selected_thinking_mode": "disabled",
                    "plan_meta": {},
                    "metrics": {"latency_ms": 123.0, "tool_calls": 2},
                    "error": None,
                    "started_at": utc_now(),
                    "finished_at": utc_now(),
                    "created_at": utc_now(),
                }
            ]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))

        def fetchall(self):
            return list(self._rows)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.repositories.postgres_trajectory_repository.psycopg.connect",
        lambda uri, **kwargs: FakeConnection(),
    )

    repo = PostgresTrajectoryRepository("postgresql://example")
    rows = repo.list_turns(
        filters={
            "request_id": "req-1",
            "trace_id": "trace-1",
            "thread_id": "thread-1",
            "status": ["failed"],
            "tool": ["web_search"],
            "started_after": "2026-04-21T00:00:00+00:00",
            "has_error": True,
        },
        limit=5,
        offset=2,
    )

    assert rows[0]["id"] == "turn-1"
    assert rows[0]["request_id"] == "req-1"
    assert rows[0]["trace_id"] == "trace-1"
    _, params = executed[-1]
    assert params["request_id"] == "req-1"
    assert params["trace_id"] == "trace-1"
    assert params["thread_id"] == "thread-1"
    assert params["status"] == ["failed"]
    assert params["step_tool"] == ["web_search"]
    assert params["since"] == datetime(2026, 4, 21, 0, 0, tzinfo=UTC)
    assert params["limit"] == 5
    assert params["offset"] == 2


def test_postgres_trajectory_repository_get_turn_and_stats(monkeypatch):
    executed: list[str] = []
    responses = [
        [
            {
                "id": "turn-1",
                "schema_version": 1,
                "kind": "chat.turn",
                "status": "failed",
                "thread_id": "thread-1",
                "root_thread_id": "root-1",
                "request_id": "req-1",
                "trace_id": "trace-1",
                "root_span_id": "span-1",
                "environment": "staging",
                "deployment": "focus-agent-blue",
                "app_version": "1.2.3",
                "parent_thread_id": None,
                "branch_id": None,
                "branch_role": None,
                "user_id_hash": "hashed",
                "scene": "long_dialog_research",
                "turn_index": 1,
                "task_brief": "search docs",
                "user_message": "search docs",
                "answer": "answer",
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "medium",
                "plan": None,
                "reflection": None,
                "plan_meta": {},
                "metrics": {"latency_ms": 250.0, "tool_calls": 1},
                "error": "boom",
                "started_at": utc_now(),
                "finished_at": utc_now(),
                "created_at": utc_now(),
            }
        ],
        [
            {
                "turn_id": "turn-1",
                "step_index": 0,
                "tool": "web_search",
                "args": {"query": "docs"},
                "observation": "found it",
                "observation_truncated": False,
                "duration_ms": 12.5,
                "error": None,
                "cache_hit": True,
                "fallback_used": True,
                "fallback_group": "web_search",
                "parallel_batch_size": 2,
                "runtime": {"cache_hit": True},
                "created_at": utc_now(),
            }
        ],
        [
            {
                "turn_count": 1,
                "succeeded_count": 0,
                "non_succeeded_count": 1,
                "total_tool_calls": 1,
                "total_llm_calls": 1,
                "total_cache_hits": 1,
                "total_fallback_uses": 1,
                "avg_latency_ms": 250.0,
                "max_latency_ms": 250.0,
            }
        ],
        [{"key": "failed", "turn_count": 1, "avg_latency_ms": 250.0}],
        [{"key": "long_dialog_research", "turn_count": 1, "avg_latency_ms": 250.0}],
        [{"key": "unassigned", "turn_count": 1}],
        [{"key": "openai:gpt-4.1-mini", "turn_count": 1, "avg_latency_ms": 250.0}],
        [{"key": "2026-04-22", "turn_count": 1, "non_succeeded_count": 1, "avg_latency_ms": 250.0}],
        [
            {
                "key": "web_search",
                "step_count": 1,
                "turn_count": 1,
                "cache_hit_steps": 1,
                "fallback_steps": 1,
                "avg_duration_ms": 12.5,
            }
        ],
    ]

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append(sql)

        def fetchone(self):
            rows = responses.pop(0)
            return rows[0] if rows else None

        def fetchall(self):
            return responses.pop(0)

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.repositories.postgres_trajectory_repository.psycopg.connect",
        lambda uri, **kwargs: FakeConnection(),
    )

    repo = PostgresTrajectoryRepository("postgresql://example")
    record = repo.get_turn("turn-1")
    stats = repo.stats(filters={"fallback_used": True})

    assert record is not None
    assert record.id == "turn-1"
    assert record.request_id == "req-1"
    assert record.trace_id == "trace-1"
    assert record.trajectory[0].tool == "web_search"
    assert stats["overview"]["turn_count"] == 1
    assert stats["by_model"][0]["key"] == "openai:gpt-4.1-mini"
    assert stats["by_day"][0]["key"] == "2026-04-22"
    assert stats["by_tool"][0]["key"] == "web_search"
    assert any("focus_trajectory_steps" in sql for sql in executed)
