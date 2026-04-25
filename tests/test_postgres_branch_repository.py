from __future__ import annotations

import pytest

from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus
from focus_agent.core.types import ConversationRecord
from focus_agent.repositories.postgres_branch_repository import PostgresBranchRepository
from focus_agent.repositories.postgres_schema import ensure_app_postgres_schema


def test_postgres_schema_setup_creates_app_tables(monkeypatch):
    executed: list[tuple[str, object]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))

        def fetchone(self):
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.repositories.postgres_schema.psycopg.connect",
        lambda uri: FakeConnection(),
    )

    ensure_app_postgres_schema("postgresql://example")

    statements = [sql for sql, _ in executed]
    assert any("CREATE TABLE IF NOT EXISTS focus_schema_migrations" in sql for sql in statements)
    assert any("CREATE TABLE IF NOT EXISTS focus_conversations" in sql for sql in statements)
    assert any("CREATE TABLE IF NOT EXISTS focus_thread_access" in sql for sql in statements)
    assert any("CREATE TABLE IF NOT EXISTS focus_branches" in sql for sql in statements)
    assert any("CREATE TABLE IF NOT EXISTS focus_artifacts" in sql for sql in statements)
    assert any("CREATE TABLE IF NOT EXISTS focus_agent_team_sessions" in sql for sql in statements)
    assert any("CREATE TABLE IF NOT EXISTS focus_agent_team_tasks" in sql for sql in statements)
    assert any("CREATE TABLE IF NOT EXISTS focus_agent_team_outputs" in sql for sql in statements)


def test_postgres_schema_setup_runs_v2_when_v1_already_exists(monkeypatch):
    executed: list[tuple[str, object]] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))
            self._params = params

        def fetchone(self):
            if self._params == (1,):
                return {"version": 1}
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.repositories.postgres_schema.psycopg.connect",
        lambda uri: FakeConnection(),
    )

    ensure_app_postgres_schema("postgresql://example")

    statements = [sql for sql, _ in executed]
    assert not any("CREATE TABLE IF NOT EXISTS focus_conversations" in sql for sql in statements)
    assert any("CREATE TABLE IF NOT EXISTS focus_agent_team_sessions" in sql for sql in statements)
    assert any(params == (2,) for _, params in executed)


def test_postgres_branch_repository_setup_and_write_queries(monkeypatch):
    executed: list[tuple[str, object]] = []
    conversations: dict[str, dict[str, object]] = {}
    thread_access: dict[str, dict[str, object]] = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))
            normalized = " ".join(sql.split())
            if normalized.startswith("INSERT INTO focus_conversations"):
                conversations[str(params[0])] = {
                    "root_thread_id": params[0],
                    "owner_user_id": params[1],
                    "title": params[2],
                    "title_pending_ai": params[3],
                    "is_archived": params[4],
                    "archived_at": params[5],
                    "created_at": "2026-04-20T00:00:00+00:00",
                    "updated_at": "2026-04-20T00:00:00+00:00",
                }
            if normalized.startswith("INSERT INTO focus_thread_access"):
                thread_access[str(params[0])] = {
                    "thread_id": params[0],
                    "root_thread_id": params[1],
                    "owner_user_id": params[2],
                }
            if normalized.startswith("SELECT owner_user_id FROM focus_thread_access"):
                self._fetchone = thread_access.get(str(params[0]))
                return
            if normalized.startswith("SELECT * FROM focus_conversations"):
                self._fetchone = conversations.get(str(params[0]))
            else:
                self._fetchone = None

        def fetchone(self):
            return self._fetchone

        def fetchall(self):
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.repositories.postgres_branch_repository.psycopg.connect",
        lambda uri, row_factory=None: FakeConnection(),
    )

    repo = PostgresBranchRepository("postgresql://example")
    repo.setup()
    repo.create(
        BranchRecord(
            branch_id="branch-1",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            child_thread_id="child-1",
            return_thread_id="root-1",
            owner_user_id="owner-1",
            branch_name="Explore",
            branch_role=BranchRole.EXPLORE_ALTERNATIVES,
            branch_depth=1,
            branch_status=BranchStatus.ACTIVE,
        )
    )
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    repo.create_conversation(
        ConversationRecord(
            root_thread_id="root-1",
            owner_user_id="owner-1",
            title="Main",
        )
    )

    statements = [sql for sql, _ in executed]
    assert any("CREATE TABLE IF NOT EXISTS focus_schema_migrations" in sql for sql in statements)
    assert any("INSERT INTO focus_branches" in sql for sql in statements)
    assert any("INSERT INTO focus_thread_access" in sql for sql in statements)
    assert any("INSERT INTO focus_conversations" in sql for sql in statements)


def test_postgres_branch_repository_row_conversion_round_trips_payloads():
    record = PostgresBranchRepository._row_to_record(
        {
            "branch_id": "branch-1",
            "root_thread_id": "root-1",
            "parent_thread_id": "root-1",
            "child_thread_id": "child-1",
            "return_thread_id": "root-1",
            "owner_user_id": "owner-1",
            "branch_name": "Explore",
            "branch_role": "explore_alternatives",
            "branch_depth": 1,
            "branch_status": "active",
            "is_archived": False,
            "archived_at": None,
            "fork_checkpoint_id": "checkpoint-1",
            "fork_strategy": "copy_thread",
            "merge_proposal": {"summary": "done"},
            "merge_decision": {"approved": True},
        }
    )
    conversation = PostgresBranchRepository._row_to_conversation(
        {
            "root_thread_id": "root-1",
            "owner_user_id": "owner-1",
            "title": "Main",
            "title_pending_ai": True,
            "is_archived": False,
            "archived_at": None,
            "created_at": "2026-04-20T00:00:00+00:00",
            "updated_at": "2026-04-20T00:00:00+00:00",
        }
    )

    assert record.branch_role == BranchRole.EXPLORE_ALTERNATIVES
    assert record.branch_status == BranchStatus.ACTIVE
    assert record.merge_proposal == {"summary": "done"}
    assert conversation.title_pending_ai is True
    assert conversation.title == "Main"


def test_ensure_thread_owner_rechecks_final_owner_after_insert_conflict(monkeypatch):
    thread_access: dict[str, str] = {}

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            normalized = " ".join(sql.split())
            if normalized.startswith("INSERT INTO focus_thread_access"):
                thread_id = str(params[0])
                thread_access.setdefault(thread_id, "owner-2")
                self._fetchone = None
                return
            if normalized.startswith("SELECT owner_user_id FROM focus_thread_access WHERE thread_id = %s"):
                owner = thread_access.get(str(params[0]))
                self._fetchone = None if owner is None else {"owner_user_id": owner}
                return
            self._fetchone = None

        def fetchone(self):
            return self._fetchone

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

    monkeypatch.setattr(
        "focus_agent.repositories.postgres_branch_repository.psycopg.connect",
        lambda uri, row_factory=None: FakeConnection(),
    )

    repo = PostgresBranchRepository("postgresql://example")

    with pytest.raises(PermissionError, match="owner-1"):
        repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    assert thread_access["root-1"] == "owner-2"
