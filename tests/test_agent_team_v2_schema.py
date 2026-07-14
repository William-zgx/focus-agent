from __future__ import annotations

import importlib.util
from pathlib import Path

from focus_agent.repositories.postgres_schema import (
    _MIGRATIONS,
    SCHEMA_VERSION,
    _run_migration_v19,
    app_postgres_schema_baseline_statements,
    app_postgres_schema_baseline_tables,
    ensure_app_postgres_schema_on_connection,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "migrations" / "versions" / "20260713_agent_team_v2_schema.py"

_V2_TABLES = {
    "focus_agent_team_revisions",
    "focus_agent_team_task_edges",
    "focus_agent_team_task_attempts",
    "focus_agent_team_checkpoints",
    "focus_agent_team_approvals",
    "focus_agent_team_jobs",
    "focus_agent_team_resource_leases",
    "focus_agent_team_side_effect_receipts",
    "focus_agent_team_evidence",
    "focus_agent_team_events",
}


def _normalized(statements: list[str] | tuple[str, ...]) -> str:
    return "\n".join(" ".join(statement.split()) for statement in statements)


def _load_alembic_revision():
    spec = importlib.util.spec_from_file_location("agent_team_v2_schema", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_team_v2_runtime_migration_snapshot_is_additive() -> None:
    statements: list[str] = []

    _run_migration_v19(statements.append)

    ddl = _normalized(statements)
    versions = [version for version, _migration in _MIGRATIONS]
    assert SCHEMA_VERSION == 19
    assert versions[-2:] == [18, 19]
    assert dict(_MIGRATIONS)[18] is not _run_migration_v19
    assert dict(_MIGRATIONS)[19] is _run_migration_v19
    assert all(f"CREATE TABLE IF NOT EXISTS {table}" in ddl for table in _V2_TABLES)
    assert "ALTER TABLE focus_agent_team_sessions" not in ddl
    assert "ALTER TABLE focus_agent_team_tasks" not in ddl
    assert "DROP TABLE" not in ddl
    assert "REFERENCES focus_agent_team_sessions(session_id) ON DELETE CASCADE" in ddl
    assert "REFERENCES focus_agent_team_tasks(task_id) ON DELETE CASCADE" in ddl
    assert "UNIQUE (session_id, revision_number)" in ddl
    assert "UNIQUE (task_id, attempt_number)" in ddl
    assert "UNIQUE (session_id, sequence)" in ddl
    assert "CHECK (upstream_task_id <> downstream_task_id)" in ddl
    assert "CHECK (lease_mode IN ('shared', 'exclusive'))" in ddl
    assert "idx_focus_agent_team_jobs_due" in ddl
    assert "uq_focus_agent_team_resource_leases_active_exclusive" in ddl


def test_agent_team_v2_is_included_in_app_schema_baseline_snapshot() -> None:
    statements = app_postgres_schema_baseline_statements()
    ddl = _normalized(statements)

    assert "VALUES (19)" in ddl
    assert _V2_TABLES.issubset(set(app_postgres_schema_baseline_tables()))


def test_agent_team_v2_runtime_initializer_applies_only_unrecorded_v19() -> None:
    class FakeCursor:
        def __init__(self) -> None:
            self.executed: list[tuple[str, object]] = []
            self._fetchone: object = None

        def __enter__(self) -> FakeCursor:
            return self

        def __exit__(self, exc_type, exc, traceback) -> bool:
            return False

        def execute(self, sql: str, params: object = None) -> None:
            self.executed.append((sql, params))
            normalized = " ".join(sql.split())
            if normalized.startswith("SELECT version FROM focus_schema_migrations"):
                self._fetchone = None if params == (19,) else {"version": params[0]}
            else:
                self._fetchone = None

        def fetchone(self) -> object:
            return self._fetchone

    class FakeConnection:
        def __init__(self) -> None:
            self.cursor_instance = FakeCursor()

        def cursor(self) -> FakeCursor:
            return self.cursor_instance

    connection = FakeConnection()

    ensure_app_postgres_schema_on_connection(connection)

    statements = [statement for statement, _params in connection.cursor_instance.executed]
    v19_statements = [
        statement for statement in statements if "focus_agent_team_revisions" in statement
    ]
    inserted_versions = [
        params
        for statement, params in connection.cursor_instance.executed
        if statement.startswith("INSERT INTO focus_schema_migrations")
    ]
    assert v19_statements
    assert (19,) in inserted_versions


def test_agent_team_v2_alembic_revision_reuses_runtime_ddl_and_reverses_dependencies(
    monkeypatch,
) -> None:
    revision = _load_alembic_revision()
    executed: list[str] = []

    monkeypatch.setattr(revision.op, "execute", executed.append)
    revision.upgrade()
    upgrade_ddl = _normalized(executed)

    assert revision.revision == "20260713_agent_team_v2_schema"
    assert revision.down_revision == "add_memory_embedding_status"
    assert all(f"CREATE TABLE IF NOT EXISTS {table}" in upgrade_ddl for table in _V2_TABLES)

    executed.clear()
    revision.downgrade()

    assert executed == [
        "DROP TABLE IF EXISTS focus_agent_team_events",
        "DROP TABLE IF EXISTS focus_agent_team_evidence",
        "DROP TABLE IF EXISTS focus_agent_team_side_effect_receipts",
        "DROP TABLE IF EXISTS focus_agent_team_resource_leases",
        "DROP TABLE IF EXISTS focus_agent_team_jobs",
        "DROP TABLE IF EXISTS focus_agent_team_approvals",
        "DROP TABLE IF EXISTS focus_agent_team_checkpoints",
        "DROP TABLE IF EXISTS focus_agent_team_task_attempts",
        "DROP TABLE IF EXISTS focus_agent_team_task_edges",
        "DROP TABLE IF EXISTS focus_agent_team_revisions",
    ]
