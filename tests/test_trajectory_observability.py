from __future__ import annotations

from datetime import timedelta

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
        lambda uri: FakeConnection(),
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
