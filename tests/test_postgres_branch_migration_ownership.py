from __future__ import annotations

from copy import deepcopy

import pytest

from focus_agent.repositories.postgres_branch_repository import (
    PostgresBranchRepository,
    create_local_state_migration_sink,
)


class _FakePostgres:
    def __init__(self) -> None:
        self.thread_access: dict[str, dict[str, object]] = {}
        self.conversations: dict[str, dict[str, object]] = {}
        self.branches: dict[str, dict[str, object]] = {}

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self)


class _FakeConnection:
    def __init__(self, database: _FakePostgres) -> None:
        self.database = database
        self._snapshot: (
            tuple[
                dict[str, dict[str, object]],
                dict[str, dict[str, object]],
                dict[str, dict[str, object]],
            ]
            | None
        ) = None

    def __enter__(self) -> _FakeConnection:
        self._snapshot = (
            deepcopy(self.database.thread_access),
            deepcopy(self.database.conversations),
            deepcopy(self.database.branches),
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            assert self._snapshot is not None
            (
                self.database.thread_access,
                self.database.conversations,
                self.database.branches,
            ) = self._snapshot
        return False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.database)


class _FakeCursor:
    def __init__(self, database: _FakePostgres) -> None:
        self.database = database
        self._fetchone: dict[str, object] | None = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params: object = None) -> None:
        normalized = " ".join(sql.split())
        if normalized.startswith("INSERT INTO focus_thread_access"):
            assert isinstance(params, tuple)
            incoming = {
                "thread_id": str(params[0]),
                "root_thread_id": str(params[1]),
                "owner_user_id": str(params[2]),
            }
            self._upsert(
                table=self.database.thread_access,
                key_field="thread_id",
                incoming=incoming,
                sql=normalized,
                owner_guard_table="focus_thread_access",
            )
            return
        if normalized.startswith("INSERT INTO focus_conversations"):
            assert isinstance(params, tuple)
            incoming = {
                "root_thread_id": str(params[0]),
                "owner_user_id": str(params[1]),
                "title": str(params[2]),
                "title_pending_ai": bool(params[3]),
                "is_archived": bool(params[4]),
                "archived_at": params[5],
            }
            self._upsert(
                table=self.database.conversations,
                key_field="root_thread_id",
                incoming=incoming,
                sql=normalized,
                owner_guard_table="focus_conversations",
            )
            return
        if normalized.startswith("INSERT INTO focus_branches"):
            assert isinstance(params, dict)
            incoming = dict(params)
            incoming["branch_id"] = str(incoming["branch_id"])
            incoming["owner_user_id"] = str(incoming["owner_user_id"])
            self._upsert(
                table=self.database.branches,
                key_field="branch_id",
                incoming=incoming,
                sql=normalized,
                owner_guard_table="focus_branches",
            )
            return
        raise AssertionError(f"Unexpected SQL: {normalized}")

    def _upsert(
        self,
        *,
        table: dict[str, dict[str, object]],
        key_field: str,
        incoming: dict[str, object],
        sql: str,
        owner_guard_table: str,
    ) -> None:
        key = str(incoming[key_field])
        existing = table.get(key)
        owner_matches = existing is None or existing["owner_user_id"] == incoming["owner_user_id"]
        has_owner_guard = f"WHERE {owner_guard_table}.owner_user_id = EXCLUDED.owner_user_id" in sql
        if not owner_matches and has_owner_guard:
            self._fetchone = None
            return

        if existing is None:
            table[key] = dict(incoming)
        else:
            existing.update(incoming)
        self._fetchone = (
            {"owner_user_id": incoming["owner_user_id"]} if " RETURNING " in f" {sql} " else None
        )

    def fetchone(self) -> dict[str, object] | None:
        return self._fetchone


@pytest.fixture
def migration_repository(monkeypatch) -> tuple[PostgresBranchRepository, _FakePostgres]:
    database = _FakePostgres()
    monkeypatch.setattr(
        "focus_agent.repositories.postgres_branch_repository.psycopg.connect",
        lambda uri, row_factory=None: database.connect(),
    )
    return PostgresBranchRepository("postgresql://migration-test"), database


def test_thread_access_migration_rejects_cross_owner_conflict_without_partial_writes(
    migration_repository,
) -> None:
    repository, database = migration_repository
    database.thread_access["occupied-thread"] = {
        "thread_id": "occupied-thread",
        "root_thread_id": "owner-b-root",
        "owner_user_id": "owner-b",
    }

    with pytest.raises(PermissionError, match="occupied-thread.*owner-a"):
        repository.upsert_thread_access_rows(
            [
                {
                    "thread_id": "new-thread",
                    "root_thread_id": "owner-a-root",
                    "owner_user_id": "owner-a",
                },
                {
                    "thread_id": "occupied-thread",
                    "root_thread_id": "owner-a-root",
                    "owner_user_id": "owner-a",
                },
            ]
        )

    assert database.thread_access == {
        "occupied-thread": {
            "thread_id": "occupied-thread",
            "root_thread_id": "owner-b-root",
            "owner_user_id": "owner-b",
        }
    }


def test_conversation_migration_rejects_cross_owner_conflict_without_partial_writes(
    migration_repository,
) -> None:
    repository, database = migration_repository
    database.conversations["occupied-root"] = {
        "root_thread_id": "occupied-root",
        "owner_user_id": "owner-b",
        "title": "Owner B",
    }

    with pytest.raises(PermissionError, match="occupied-root.*owner-a"):
        repository.upsert_conversation_rows(
            [
                {
                    "root_thread_id": "new-root",
                    "owner_user_id": "owner-a",
                    "title": "New",
                },
                {
                    "root_thread_id": "occupied-root",
                    "owner_user_id": "owner-a",
                    "title": "Takeover",
                },
            ]
        )

    assert database.conversations == {
        "occupied-root": {
            "root_thread_id": "occupied-root",
            "owner_user_id": "owner-b",
            "title": "Owner B",
        }
    }


def test_branch_migration_rejects_cross_owner_conflict_without_partial_writes(
    migration_repository,
) -> None:
    repository, database = migration_repository
    database.branches["occupied-branch"] = {
        "branch_id": "occupied-branch",
        "owner_user_id": "owner-b",
        "branch_name": "Owner B",
    }

    with pytest.raises(PermissionError, match="occupied-branch.*owner-a"):
        repository.upsert_branch_rows(
            [
                _branch_row("new-branch", "owner-a", "New"),
                _branch_row("occupied-branch", "owner-a", "Takeover"),
            ]
        )

    assert database.branches == {
        "occupied-branch": {
            "branch_id": "occupied-branch",
            "owner_user_id": "owner-b",
            "branch_name": "Owner B",
        }
    }


def test_migration_upserts_remain_idempotent_for_the_same_owner(
    migration_repository,
) -> None:
    repository, database = migration_repository
    database.thread_access["thread-1"] = {
        "thread_id": "thread-1",
        "root_thread_id": "old-root",
        "owner_user_id": "owner-a",
    }
    database.conversations["root-1"] = {
        "root_thread_id": "root-1",
        "owner_user_id": "owner-a",
        "title": "Old",
    }
    database.branches["branch-1"] = {
        "branch_id": "branch-1",
        "owner_user_id": "owner-a",
        "branch_name": "Old",
    }

    assert (
        repository.upsert_thread_access_rows(
            [
                {
                    "thread_id": "thread-1",
                    "root_thread_id": "root-1",
                    "owner_user_id": "owner-a",
                }
            ]
        )
        == 1
    )
    assert (
        repository.upsert_conversation_rows(
            [
                {
                    "root_thread_id": "root-1",
                    "owner_user_id": "owner-a",
                    "title": "Updated",
                }
            ]
        )
        == 1
    )
    assert repository.upsert_branch_rows([_branch_row("branch-1", "owner-a", "Updated")]) == 1

    assert database.thread_access["thread-1"]["root_thread_id"] == "root-1"
    assert database.thread_access["thread-1"]["owner_user_id"] == "owner-a"
    assert database.conversations["root-1"]["title"] == "Updated"
    assert database.conversations["root-1"]["owner_user_id"] == "owner-a"
    assert database.branches["branch-1"]["branch_name"] == "Updated"
    assert database.branches["branch-1"]["owner_user_id"] == "owner-a"


@pytest.mark.parametrize("conflict_table", ["thread", "conversation", "branch"])
def test_app_state_migration_rolls_back_all_tables_on_any_owner_conflict(
    monkeypatch,
    conflict_table: str,
) -> None:
    database = _FakePostgres()
    if conflict_table == "thread":
        database.thread_access["thread-1"] = {
            "thread_id": "thread-1",
            "root_thread_id": "owner-b-root",
            "owner_user_id": "owner-b",
        }
    elif conflict_table == "conversation":
        database.conversations["root-1"] = {
            "root_thread_id": "root-1",
            "owner_user_id": "owner-b",
            "title": "Owner B",
        }
    else:
        database.branches["branch-1"] = {
            "branch_id": "branch-1",
            "owner_user_id": "owner-b",
            "branch_name": "Owner B",
        }
    expected_thread_access = deepcopy(database.thread_access)
    expected_conversations = deepcopy(database.conversations)
    expected_branches = deepcopy(database.branches)
    monkeypatch.setattr(
        "focus_agent.repositories.postgres_branch_repository.psycopg.connect",
        lambda uri, row_factory=None: database.connect(),
    )
    sink = create_local_state_migration_sink("postgresql://migration-test")

    assert (
        sink.upsert_thread_access_rows(
            [
                {
                    "thread_id": "thread-1",
                    "root_thread_id": "root-1",
                    "owner_user_id": "owner-a",
                }
            ]
        )
        == 1
    )
    assert (
        sink.upsert_conversation_rows(
            [
                {
                    "root_thread_id": "root-1",
                    "owner_user_id": "owner-a",
                    "title": "Owner A",
                }
            ]
        )
        == 1
    )
    with pytest.raises(PermissionError, match="owner-a"):
        sink.upsert_branch_rows([_branch_row("branch-1", "owner-a", "Owner A")])

    assert database.thread_access == expected_thread_access
    assert database.conversations == expected_conversations
    assert database.branches == expected_branches


def test_app_state_migration_commits_all_tables_for_the_same_owner(monkeypatch) -> None:
    database = _FakePostgres()
    monkeypatch.setattr(
        "focus_agent.repositories.postgres_branch_repository.psycopg.connect",
        lambda uri, row_factory=None: database.connect(),
    )
    sink = create_local_state_migration_sink("postgresql://migration-test")

    assert (
        sink.upsert_thread_access_rows(
            [
                {
                    "thread_id": "thread-1",
                    "root_thread_id": "root-1",
                    "owner_user_id": "owner-a",
                }
            ]
        )
        == 1
    )
    assert (
        sink.upsert_conversation_rows(
            [
                {
                    "root_thread_id": "root-1",
                    "owner_user_id": "owner-a",
                    "title": "Owner A",
                }
            ]
        )
        == 1
    )
    assert sink.upsert_branch_rows([_branch_row("branch-1", "owner-a", "Owner A")]) == 1

    assert database.thread_access["thread-1"]["owner_user_id"] == "owner-a"
    assert database.conversations["root-1"]["owner_user_id"] == "owner-a"
    assert database.branches["branch-1"]["owner_user_id"] == "owner-a"


def _branch_row(branch_id: str, owner_user_id: str, branch_name: str) -> dict[str, object]:
    return {
        "branch_id": branch_id,
        "root_thread_id": "root-1",
        "parent_thread_id": "root-1",
        "child_thread_id": f"{branch_id}-child",
        "return_thread_id": "root-1",
        "owner_user_id": owner_user_id,
        "branch_name": branch_name,
        "branch_role": "explore_alternatives",
        "branch_depth": 1,
        "branch_status": "active",
    }
