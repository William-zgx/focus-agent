from pathlib import Path

import pytest

from focus_agent.core.types import ConversationRecord
from focus_agent.repositories.sqlite_branch_repository import SQLiteBranchRepository
from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus


def test_sqlite_branch_repository_roundtrip(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="user-1")
    record = BranchRecord(
        branch_id="b1",
        root_thread_id="root-1",
        parent_thread_id="parent-1",
        child_thread_id="child-1",
        return_thread_id="parent-1",
        owner_user_id="user-1",
        branch_name="branch",
        branch_role=BranchRole.DEEP_DIVE,
        branch_depth=1,
        branch_status=BranchStatus.ACTIVE,
    )
    repo.create(record)
    repo.ensure_thread_owner(thread_id="child-1", root_thread_id="root-1", owner_user_id="user-1")
    loaded = repo.get("b1")
    assert loaded.child_thread_id == "child-1"
    assert loaded.branch_role == BranchRole.DEEP_DIVE
    assert loaded.is_archived is False
    assert loaded.archived_at is None
    assert repo.list_by_root_thread_id("root-1")[0].branch_id == "b1"
    assert repo.list_by_parent_thread_id("parent-1")[0].child_thread_id == "child-1"
    repo.assert_thread_owner(thread_id="child-1", owner_user_id="user-1")
    assert repo.get_thread_owner(thread_id="root-1") == "user-1"

    repo.update_archive_state("b1", is_archived=True)
    archived = repo.get("b1")
    assert archived.is_archived is True
    assert archived.archived_at is not None

    repo.update_archive_state("b1", is_archived=False)
    restored = repo.get("b1")
    assert restored.is_archived is False
    assert restored.archived_at is None

def test_sqlite_branch_repository_loads_old_rows_without_policy_column(tmp_path: Path):
    db_path = tmp_path / "branches.sqlite3"
    repo = SQLiteBranchRepository(str(db_path))
    with repo._connect() as conn:
        conn.execute("DROP TABLE branches")
        conn.execute(
            """
            CREATE TABLE branches (
                branch_id TEXT PRIMARY KEY,
                root_thread_id TEXT NOT NULL,
                parent_thread_id TEXT NOT NULL,
                child_thread_id TEXT NOT NULL UNIQUE,
                return_thread_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                branch_name TEXT NOT NULL,
                branch_role TEXT NOT NULL,
                branch_depth INTEGER NOT NULL,
                branch_status TEXT NOT NULL,
                is_archived INTEGER NOT NULL DEFAULT 0,
                archived_at TEXT,
                fork_checkpoint_id TEXT,
                fork_strategy TEXT NOT NULL,
                merge_proposal_json TEXT,
                merge_decision_json TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO branches (
                branch_id, root_thread_id, parent_thread_id, child_thread_id, return_thread_id,
                owner_user_id, branch_name, branch_role, branch_depth, branch_status,
                is_archived, archived_at, fork_checkpoint_id, fork_strategy,
                merge_proposal_json, merge_decision_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "b-old",
                "root-1",
                "root-1",
                "child-old",
                "root-1",
                "user-1",
                "legacy branch",
                "deep_dive",
                1,
                "active",
                0,
                None,
                None,
                "copy_thread",
                None,
                None,
            ),
        )
        conn.commit()

    repo._setup()
    loaded = repo.get("b-old")
    assert loaded.branch_name == "legacy branch"


def test_thread_access_rejects_other_user(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="user-1")
    with pytest.raises(PermissionError):
        repo.assert_thread_owner(thread_id="root-1", owner_user_id="user-2")


def test_conversation_roundtrip_and_backfill(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="user-1-main", root_thread_id="user-1-main", owner_user_id="user-1")
    repo.ensure_thread_owner(thread_id="root-2", root_thread_id="root-2", owner_user_id="user-1")

    created = repo.create_conversation(
        ConversationRecord(
            root_thread_id="root-2",
            owner_user_id="user-1",
            title="Conversation 2",
            title_pending_ai=True,
            is_archived=False,
        )
    )

    assert created.root_thread_id == "root-2"
    assert created.title == "Conversation 2"
    assert created.title_pending_ai is True
    assert created.is_archived is False
    assert created.archived_at is None

    listed = repo.list_conversations(owner_user_id="user-1")
    titles_by_id = {item.root_thread_id: item.title for item in listed}

    assert titles_by_id["root-2"] == "Conversation 2"
    assert titles_by_id["user-1-main"] == "Main"

    archived = repo.update_conversation_archive_state(
        root_thread_id="root-2",
        owner_user_id="user-1",
        is_archived=True,
    )

    assert archived.is_archived is True
    assert archived.archived_at is not None

    renamed = repo.update_conversation_title(
        root_thread_id="root-2",
        owner_user_id="user-1",
        title="Renamed conversation",
        title_pending_ai=False,
    )

    assert renamed.title == "Renamed conversation"
    assert renamed.title_pending_ai is False
    assert renamed.is_archived is True
