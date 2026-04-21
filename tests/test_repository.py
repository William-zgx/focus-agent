from pathlib import Path

import pytest

from focus_agent.core.types import ConversationRecord
from focus_agent.repositories.artifact_metadata_repository import ArtifactMetadataRepository
from focus_agent.repositories.sqlite_branch_repository import SQLiteBranchRepository
from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus


class _FakeArtifactMetadataCursor:
    def __init__(self, storage: dict[str, dict[str, object]]):
        self.storage = storage
        self._rows: list[dict[str, object]] = []

    def execute(self, query: str, params: dict[str, object] | None = None) -> None:
        normalized = " ".join(query.split())
        params = params or {}
        if normalized.startswith("CREATE TABLE") or normalized.startswith("CREATE INDEX") or normalized.startswith("CREATE UNIQUE INDEX"):
            self._rows = []
            return
        if normalized.startswith("SELECT version FROM focus_schema_migrations"):
            self._rows = []
            return
        if normalized.startswith("INSERT INTO focus_schema_migrations"):
            self._rows = []
            return
        if "INSERT INTO focus_artifacts" in normalized:
            artifact_id = str(params["relative_path"])
            previous = self.storage.get(artifact_id)
            row = dict(params)
            row["created_at"] = previous["created_at"] if previous is not None else params["created_at"]
            self.storage[artifact_id] = row
            self._rows = [
                {
                    "relative_path": row["relative_path"],
                    "source_thread_id": row["source_thread_id"],
                    "uri": row["uri"],
                    "title": row["title"],
                    "size_bytes": row["size_bytes"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            ]
            return
        if "FROM focus_artifacts WHERE source_thread_id" in normalized:
            thread_id = str(params["thread_id"])
            rows = [
                row
                for row in self.storage.values()
                if str(row["source_thread_id"]) == thread_id or str(row["root_thread_id"]) == thread_id
            ]
            rows.sort(key=lambda row: (-row["updated_at"].timestamp(), str(row["relative_path"])))
            limit = params.get("limit")
            if limit is not None:
                rows = rows[: int(limit)]
            self._rows = [
                {
                    "relative_path": row["relative_path"],
                    "source_thread_id": row["source_thread_id"],
                    "uri": row["uri"],
                    "title": row["title"],
                    "size_bytes": row["size_bytes"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]
            return
        if "FROM focus_artifacts WHERE relative_path" in normalized:
            artifact_id = str(params["artifact_id"])
            row = self.storage.get(artifact_id)
            self._rows = (
                [
                    {
                        "relative_path": row["relative_path"],
                        "source_thread_id": row["source_thread_id"],
                        "uri": row["uri"],
                        "title": row["title"],
                        "size_bytes": row["size_bytes"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    }
                ]
                if row is not None
                else []
            )
            return
        raise AssertionError(f"Unexpected query: {query}")

    def fetchone(self) -> dict[str, object] | None:
        if not self._rows:
            return None
        return dict(self._rows[0])

    def fetchall(self) -> list[dict[str, object]]:
        return [dict(row) for row in self._rows]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeArtifactMetadataConnection:
    def __init__(self, storage: dict[str, dict[str, object]]):
        self.storage = storage

    def cursor(self, row_factory=None):
        del row_factory
        return _FakeArtifactMetadataCursor(self.storage)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


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

    repo.update_branch_role("b1", BranchRole.EXECUTE)
    retyped = repo.get("b1")
    assert retyped.branch_role == BranchRole.EXECUTE

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


def test_artifact_metadata_repository_roundtrip(monkeypatch, tmp_path: Path):
    storage: dict[str, dict[str, object]] = {}
    monkeypatch.setattr(
        "focus_agent.repositories.artifact_metadata_repository.psycopg.connect",
        lambda _database_uri: _FakeArtifactMetadataConnection(storage),
    )
    repo = ArtifactMetadataRepository("postgresql://example.test/focus_agent")
    artifact_one = tmp_path / "launch-plan.md"
    artifact_two = tmp_path / "retro.md"
    artifact_one.write_text("draft one\n", encoding="utf-8")
    artifact_two.write_text("retro\n", encoding="utf-8")
    repo.setup()

    first = repo.upsert_from_file(
        thread_id="thread-1",
        artifact_id="launch-plan.md",
        path=artifact_one,
        title="Launch Plan",
    )
    later_mtime = artifact_two.stat().st_mtime + 30
    artifact_two.touch()
    artifact_two.write_text("retro update\n", encoding="utf-8")
    artifact_two.touch()
    import os
    os.utime(artifact_two, (later_mtime, later_mtime))
    second = repo.upsert_from_file(
        thread_id="thread-1",
        artifact_id="retro.md",
        path=artifact_two,
        title="Retro",
    )

    fetched = repo.get_by_artifact_id("launch-plan.md")
    listed = repo.list_by_thread("thread-1")

    assert first.artifact_id == "launch-plan.md"
    assert fetched is not None
    assert fetched.title == "Launch Plan"
    assert second.size_bytes == artifact_two.stat().st_size
    assert [item.artifact_id for item in listed] == ["retro.md", "launch-plan.md"]


def test_artifact_metadata_repository_preserves_created_at_on_upsert(monkeypatch, tmp_path: Path):
    storage: dict[str, dict[str, object]] = {}
    monkeypatch.setattr(
        "focus_agent.repositories.artifact_metadata_repository.psycopg.connect",
        lambda _database_uri: _FakeArtifactMetadataConnection(storage),
    )
    repo = ArtifactMetadataRepository("postgresql://example.test/focus_agent")
    artifact = tmp_path / "launch-plan.md"
    artifact.write_text("one\n", encoding="utf-8")

    original = repo.upsert_from_file(
        thread_id="thread-1",
        artifact_id="launch-plan.md",
        path=artifact,
        title="Launch Plan",
    )
    later_mtime = artifact.stat().st_mtime + 30
    artifact.write_text("two\n", encoding="utf-8")
    import os
    os.utime(artifact, (later_mtime, later_mtime))
    updated = repo.upsert_from_file(
        thread_id="thread-2",
        artifact_id="launch-plan.md",
        path=artifact,
        title="Launch Plan",
    )

    assert updated.created_at == original.created_at
    assert updated.updated_at >= original.updated_at
    assert updated.thread_id == "thread-2"
