from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.base import empty_checkpoint

from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus
from focus_agent.core.types import ConversationRecord
from focus_agent.engine.local_persistence import PersistentInMemorySaver, PersistentInMemoryStore
from focus_agent.migrate_local_state import (
    AppStateSinkDiscovery,
    main,
    parse_args,
    run_migration,
)
from focus_agent.repositories.sqlite_branch_repository import SQLiteBranchRepository


class FakePostgresStore:
    def __init__(self):
        self.setup_calls = 0
        self.items: dict[tuple[tuple[str, ...], str], dict] = {}

    def setup(self) -> None:
        self.setup_calls += 1

    def put(self, namespace: tuple[str, ...], key: str, value: dict) -> None:
        self.items[(tuple(namespace), key)] = dict(value)


class FakePostgresSaver:
    def __init__(self):
        self.setup_calls = 0
        self.checkpoints: dict[tuple[str, str, str], dict] = {}

    def setup(self) -> None:
        self.setup_calls += 1

    def put(self, config: dict, checkpoint: dict, metadata: dict, new_versions: dict) -> dict:
        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        checkpoint_ns = str(configurable.get("checkpoint_ns", ""))
        checkpoint_id = str(checkpoint["id"])
        self.checkpoints[(thread_id, checkpoint_ns, checkpoint_id)] = {
            "metadata": dict(metadata),
            "checkpoint": dict(checkpoint),
            "new_versions": dict(new_versions),
            "parent_checkpoint_id": configurable.get("checkpoint_id"),
        }
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }


class FakeAppStateSink:
    description = "fake-app-state-sink"

    def __init__(self):
        self.setup_calls = 0
        self.thread_access_rows: dict[str, dict] = {}
        self.conversation_rows: dict[str, dict] = {}
        self.branch_rows: dict[str, dict] = {}

    def setup(self) -> None:
        self.setup_calls += 1

    def upsert_thread_access_rows(self, rows):
        for row in rows:
            self.thread_access_rows[str(row["thread_id"])] = dict(row)
        return len(rows)

    def upsert_conversation_rows(self, rows):
        for row in rows:
            self.conversation_rows[str(row["root_thread_id"])] = dict(row)
        return len(rows)

    def upsert_branch_rows(self, rows):
        for row in rows:
            self.branch_rows[str(row["branch_id"])] = dict(row)
        return len(rows)


def _build_source_state(tmp_path: Path) -> tuple[Path, Path]:
    workspace_dir = tmp_path / "workspace"
    state_dir = workspace_dir / ".focus_agent"
    state_dir.mkdir(parents=True)
    (state_dir / "artifacts").mkdir()
    (state_dir / "artifacts" / "summary.md").write_text("# migrated\n", encoding="utf-8")

    repo = SQLiteBranchRepository(str(state_dir / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="user-1")
    repo.ensure_thread_owner(thread_id="child-1", root_thread_id="root-1", owner_user_id="user-1")
    repo.create_conversation(
        ConversationRecord(
            root_thread_id="root-1",
            owner_user_id="user-1",
            title="Root conversation",
            title_pending_ai=False,
        )
    )
    repo.create(
        BranchRecord(
            branch_id="branch-1",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            child_thread_id="child-1",
            return_thread_id="root-1",
            owner_user_id="user-1",
            branch_name="Deep dive",
            branch_role=BranchRole.DEEP_DIVE,
            branch_depth=1,
            branch_status=BranchStatus.ACTIVE,
        )
    )

    store = PersistentInMemoryStore(state_dir / "langgraph-store.pkl")
    store.put(
        ("conversation", "root-1", "main"),
        "memory-1",
        {"type": "imported_conclusion", "summary": "existing state"},
    )

    saver = PersistentInMemorySaver(state_dir / "langgraph-checkpoints.pkl")
    base_config = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}

    stable_checkpoint = empty_checkpoint()
    stable_checkpoint["channel_values"] = {"answer": "stable"}
    stable_checkpoint["channel_versions"] = {"answer": "1"}
    stable_config = saver.put(
        base_config,
        stable_checkpoint,
        {"source": "loop", "step": 0},
        {"answer": "1"},
    )

    unstable_checkpoint = empty_checkpoint()
    unstable_checkpoint["channel_values"] = {"answer": "unstable"}
    unstable_checkpoint["channel_versions"] = {"answer": "2"}
    unstable_config = saver.put(
        stable_config,
        unstable_checkpoint,
        {"source": "loop", "step": 1},
        {"answer": "2"},
    )
    saver.put_writes(
        unstable_config,
        [("tasks", {"pending": True})],
        task_id="task-1",
    )

    return workspace_dir, state_dir


def test_migrate_local_state_main_dry_run_writes_report_without_touching_postgres(tmp_path, monkeypatch):
    workspace_dir, state_dir = _build_source_state(tmp_path)
    report_path = tmp_path / "dry-run-report.json"

    def _unexpected_call(*args, **kwargs):
        raise AssertionError("Postgres should not be touched during dry-run")

    monkeypatch.setattr("focus_agent.migrate_local_state.open_postgres_store", _unexpected_call)
    monkeypatch.setattr("focus_agent.migrate_local_state.open_postgres_saver", _unexpected_call)
    monkeypatch.setattr("focus_agent.migrate_local_state.setup_trajectory_schema", _unexpected_call)

    exit_code = main(
        [
            "--source-dir",
            str(workspace_dir),
            "--database-uri",
            "postgresql://example/focus-agent",
            "--dry-run",
            "--checkpoint-mode",
            "latest-stable",
            "--artifact-scan",
            "--report-path",
            str(report_path),
        ]
    )

    report = report_path.read_text(encoding="utf-8")

    assert exit_code == 0
    assert str(state_dir) in report
    assert '"status": "dry-run"' in report
    assert '"selected_checkpoint_count": 1' in report
    assert '"skipped_due_to_pending_writes": 1' in report
    assert '"artifact_count": 1' in report
    assert '"store_item_count": 1' in report


def test_run_migration_real_is_repeatable_and_uses_app_state_sink(tmp_path, monkeypatch):
    workspace_dir, _state_dir = _build_source_state(tmp_path)
    fake_store = FakePostgresStore()
    fake_saver = FakePostgresSaver()
    fake_sink = FakeAppStateSink()
    trajectory_setup_calls: list[str] = []

    @contextmanager
    def _open_fake_store(_database_uri: str):
        yield fake_store

    @contextmanager
    def _open_fake_saver(_database_uri: str):
        yield fake_saver

    def _setup_fake_trajectory(_database_uri: str) -> None:
        trajectory_setup_calls.append("called")

    monkeypatch.setattr("focus_agent.migrate_local_state.open_postgres_store", _open_fake_store)
    monkeypatch.setattr("focus_agent.migrate_local_state.open_postgres_saver", _open_fake_saver)
    monkeypatch.setattr("focus_agent.migrate_local_state.setup_trajectory_schema", _setup_fake_trajectory)

    args = parse_args(
        [
            "--source-dir",
            str(workspace_dir),
            "--database-uri",
            "postgresql://example/focus-agent",
            "--checkpoint-mode",
            "latest-stable",
            "--report-path",
            str(tmp_path / "real-report.json"),
        ]
    )

    sink_discovery = AppStateSinkDiscovery(
        sink=fake_sink,
        description=fake_sink.description,
        attempts=["test fixture"],
    )

    first_report = run_migration(args, sink_discovery=sink_discovery)
    second_report = run_migration(args, sink_discovery=sink_discovery)

    assert first_report["steps"][0]["status"] == "completed"
    assert first_report["steps"][1]["details"]["branch_migrated"] == 1
    assert first_report["steps"][2]["details"]["migrated_item_count"] == 1
    assert first_report["steps"][3]["details"]["migrated_checkpoint_count"] == 1

    assert len(fake_store.items) == 1
    assert len(fake_saver.checkpoints) == 1
    assert len(fake_sink.thread_access_rows) == 2
    assert len(fake_sink.conversation_rows) == 1
    assert len(fake_sink.branch_rows) == 1
    assert fake_store.setup_calls == 2
    assert fake_saver.setup_calls == 2
    assert fake_sink.setup_calls == 2
    assert len(trajectory_setup_calls) == 2

    assert second_report["steps"][2]["details"]["migrated_item_count"] == 1
    assert second_report["steps"][3]["details"]["migrated_checkpoint_count"] == 1
