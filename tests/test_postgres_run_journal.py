import asyncio
import os
import uuid

import pytest

from focus_agent.harness.observability import PostgresRunJournal
from focus_agent.repositories.postgres_schema import _MIGRATIONS, SCHEMA_VERSION


def test_postgres_harness_journal_migration_shape():
    executed: list[str] = []
    migration = dict(_MIGRATIONS)[11]

    migration(lambda sql, params=None: executed.append(sql))

    assert SCHEMA_VERSION == 17
    combined = " ".join(" ".join(sql.split()) for sql in executed)
    assert "CREATE TABLE IF NOT EXISTS focus_harness_runs" in combined
    assert "CREATE TABLE IF NOT EXISTS focus_harness_run_events" in combined
    assert "CREATE TABLE IF NOT EXISTS focus_harness_tool_events" in combined
    assert "on_disconnect TEXT NOT NULL DEFAULT 'cancel'" in combined
    assert "UNIQUE (run_id, sequence)" in combined
    assert "idx_focus_harness_run_events_stream_event" in combined
    assert "idx_focus_harness_tool_events_tool_name" in combined


def test_postgres_run_journal_contract_with_real_database():
    database_uri = os.environ.get("DATABASE_URI")
    if not database_uri:
        pytest.skip("DATABASE_URI is required for real Postgres run journal contract")

    async def scenario():
        journal = PostgresRunJournal(database_uri)
        journal.setup()
        run_id = f"test-harness-run-journal-{uuid.uuid4()}"
        await journal.put(
            run_id,
            thread_id="thread-postgres",
            assistant_id="focus-agent",
            status="pending",
            on_disconnect="rollback",
            metadata={"suite": "postgres"},
            kwargs={"input": {"message": "hello"}},
        )
        await journal.update_status(run_id, "running")
        await journal.update_run_completion(run_id, prompt_tokens=3)
        first = await journal.append_event(
            run_id,
            "message.delta",
            {
                "run_id": run_id,
                "thread_id": "thread-postgres",
                "sequence": 1,
                "delta": "hi",
            },
            stream_event_id="stream-1",
        )
        second = await journal.append_event(
            run_id,
            "tool.result",
            {
                "tool_call_id": "call-1",
                "tool_name": "search_code",
                "args": {"query": "harness"},
                "result": "found",
            },
        )

        assert first.sequence == 1
        assert second.sequence == 2
        run = await journal.get_run(run_id)
        assert run is not None
        assert run.on_disconnect == "rollback"
        assert run.completion == {"prompt_tokens": 3}
        assert await journal.count_events(run_id) >= 2
        assert await journal.count_tool_events(run_id, tool_name="search_code") == 1
        snapshot = await journal.snapshot(run_id)
        assert snapshot["run"]["metadata"] == {"suite": "postgres"}
        assert snapshot["tool_events"][0]["result"] == "found"

    asyncio.run(scenario())
