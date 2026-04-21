from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from langchain.messages import AIMessage, HumanMessage, ToolMessage

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
        observation_max_chars=3,
        answer_max_chars=4,
    )

    assert record.root_thread_id == "root-1"
    assert record.user_id_hash != "owner-1"
    assert record.user_message == "read README"
    assert record.answer == "done"
    assert record.metrics["llm_calls"] == 2
    assert record.metrics["tool_calls"] == 1
    assert record.trajectory[0].observation == "abc"
    assert record.trajectory[0].observation_truncated is True


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
    )
    repo.record_turn(record)

    statements = [sql for sql, _ in executed]
    assert any("CREATE TABLE IF NOT EXISTS focus_trajectory_turns" in sql for sql in statements)
    assert any("CREATE TABLE IF NOT EXISTS focus_trajectory_steps" in sql for sql in statements)
    assert any("INSERT INTO focus_trajectory_turns" in sql for sql in statements)


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
    _, params = executed[-1]
    assert params["thread_id"] == "thread-1"
    assert params["status"] == ["failed"]
    assert params["step_tool"] == ["web_search"]
    assert params["since"] == datetime(2026, 4, 21, 0, 0, tzinfo=timezone.utc)
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
        [{"turn_count": 1, "succeeded_count": 0, "non_succeeded_count": 1, "total_tool_calls": 1, "total_llm_calls": 1, "total_cache_hits": 1, "total_fallback_uses": 1, "avg_latency_ms": 250.0, "max_latency_ms": 250.0}],
        [{"key": "failed", "turn_count": 1, "avg_latency_ms": 250.0}],
        [{"key": "long_dialog_research", "turn_count": 1, "avg_latency_ms": 250.0}],
        [{"key": "unassigned", "turn_count": 1}],
        [{"key": "web_search", "step_count": 1, "turn_count": 1, "cache_hit_steps": 1, "fallback_steps": 1, "avg_duration_ms": 12.5}],
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
    assert record.trajectory[0].tool == "web_search"
    assert stats["overview"]["turn_count"] == 1
    assert stats["by_tool"][0]["key"] == "web_search"
    assert any("focus_trajectory_steps" in sql for sql in executed)
