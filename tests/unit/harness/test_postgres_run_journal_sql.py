from __future__ import annotations

import inspect

from focus_agent.harness.observability.postgres_run_journal import PostgresRunJournal


def test_background_job_insert_value_arity_matches_target_columns():
    source = inspect.getsource(PostgresRunJournal.put)
    statement = source.split("INSERT INTO focus_background_jobs", 1)[1]
    target_columns = statement.split(")", 1)[0].split(",")
    values = statement.split("VALUES", 1)[1].split("ON CONFLICT", 1)[0].split(",")

    assert len(target_columns) == len(values) == 19
    assert "NULL, NULL, NULL, NULL, NULL" not in values
