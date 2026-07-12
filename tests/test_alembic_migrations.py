from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from focus_agent.repositories.postgres_schema import (
    app_postgres_schema_baseline_statements,
    app_postgres_schema_baseline_tables,
)

ROOT = Path(__file__).resolve().parents[1]
_CREATED_TABLE_PATTERN = re.compile(
    r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r'(?:"(?P<quoted>[A-Za-z_][A-Za-z0-9_]*)"|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))\b',
    re.IGNORECASE,
)
_DROPPED_TABLE_PATTERN = re.compile(
    r'\bDROP\s+TABLE\s+IF\s+EXISTS\s+"(?P<table>[A-Za-z_][A-Za-z0-9_]*)"\s+CASCADE\b',
    re.IGNORECASE,
)


def _run_alembic(*args: str) -> str:
    env = os.environ.copy()
    env["DATABASE_URI"] = "postgresql://unused/focus_agent"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_alembic_upgrade_head_renders_offline_sql() -> None:
    sql = _run_alembic("upgrade", "head", "--sql")

    assert "CREATE TABLE IF NOT EXISTS focus_schema_migrations" in sql
    assert "CREATE TABLE IF NOT EXISTS focus_branch_decision_events" in sql
    assert "ALTER TABLE focus_memories" in sql
    assert "add_memory_embedding_status" in sql


def test_baseline_downgrade_drops_every_table_created_by_baseline() -> None:
    upgrade_sql = _run_alembic("upgrade", "001_baseline", "--sql")
    downgrade_sql = _run_alembic("downgrade", "001_baseline:base", "--sql")

    created_tables = {
        match.group("quoted") or match.group("plain")
        for match in _CREATED_TABLE_PATTERN.finditer(upgrade_sql)
    } - {"alembic_version"}
    dropped_tables = set(_DROPPED_TABLE_PATTERN.findall(downgrade_sql))

    assert created_tables == set(app_postgres_schema_baseline_tables())
    assert dropped_tables == created_tables


def test_baseline_preserves_optional_memory_embedding_migration_behavior() -> None:
    baseline_sql = "\n".join(app_postgres_schema_baseline_statements())

    assert "focus_memory_embeddings" not in baseline_sql
    assert "VALUES (10)" not in baseline_sql
    assert "VALUES (18)" in baseline_sql
    assert "focus_memory_embeddings" not in app_postgres_schema_baseline_tables()


def test_head_downgrade_only_reverts_embedding_status_for_legacy_baselines() -> None:
    sql = _run_alembic("downgrade", "head:base", "--sql")

    legacy_baseline_guard = sql.index("IF NOT EXISTS (")
    schema_version_check = sql.index("WHERE version = 18")
    drop_embedding_status = sql.index("DROP COLUMN IF EXISTS embedding_status")
    drop_focus_memories = sql.index('DROP TABLE IF EXISTS "focus_memories" CASCADE')

    assert (
        legacy_baseline_guard < schema_version_check < drop_embedding_status < drop_focus_memories
    )
