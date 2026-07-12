from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from focus_agent.config import Settings
from focus_agent.engine.runtime_persistence import _create_local_app_state_repositories

_RUNTIME_RESTART_SCRIPT = """
import json
import sys
from pathlib import Path

from focus_agent.config import Settings
from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus
from focus_agent.core.types import ConversationRecord
from focus_agent.core.users import User, UserSession
from focus_agent.engine.runtime import create_runtime

mode = sys.argv[1]
state_dir = Path(sys.argv[2])
manifest_path = state_dir / "app-state-manifest.json"
settings = Settings(
    database_uri=None,
    branch_db_path=str(state_dir / "branches.sqlite3"),
    artifact_dir=str(state_dir / "artifacts"),
    local_checkpoint_path=str(state_dir / "langgraph-checkpoints.sqlite3"),
    local_store_path=str(state_dir / "langgraph-store.sqlite3"),
    agent_zvec_enabled=False,
)
runtime = create_runtime(settings)
try:
    assert type(runtime.repo).__name__ == "SQLiteBranchRepository"
    assert type(runtime.user_repository).__name__ == "SQLiteUserRepository"
    assert type(runtime.productivity_repository).__name__ == "SQLiteProductivityRepository"
    assert runtime.user_service.repository is runtime.user_repository
    assert runtime.productivity_service.repository is runtime.productivity_repository

    if mode == "write":
        runtime.repo.create_conversation(
            ConversationRecord(
                root_thread_id="root-1",
                owner_user_id="user-1",
                title="Persistent conversation",
            )
        )
        runtime.repo.ensure_thread_owner(
            thread_id="root-1",
            root_thread_id="root-1",
            owner_user_id="user-1",
        )
        runtime.repo.create(
            BranchRecord(
                branch_id="branch-1",
                root_thread_id="root-1",
                parent_thread_id="root-1",
                child_thread_id="child-1",
                return_thread_id="root-1",
                owner_user_id="user-1",
                branch_name="Persistent branch",
                branch_role=BranchRole.DEEP_DIVE,
                branch_depth=1,
                branch_status=BranchStatus.ACTIVE,
            )
        )
        runtime.repo.ensure_thread_owner(
            thread_id="child-1",
            root_thread_id="root-1",
            owner_user_id="user-1",
        )
        runtime.user_repository.create_user(
            User(
                user_id="user-1",
                username="persistent_user",
                display_name="Persistent User",
                status="active",
                roles=["member"],
                created_at="2026-07-12T00:00:00Z",
                updated_at="2026-07-12T00:00:00Z",
            )
        )
        runtime.user_repository.create_session(
            UserSession(
                session_id="session-1",
                user_id="user-1",
                refresh_token_hash="restart-test-refresh-hash",
                created_at="2026-07-12T00:01:00Z",
                updated_at="2026-07-12T00:01:00Z",
                expires_at="2026-07-13T00:01:00Z",
            )
        )
        note = runtime.productivity_service.create_note(
            user_id="user-1",
            title="Persistent note",
            body="Survives a runtime process restart.",
            source_thread_id="root-1",
        )
        task = runtime.productivity_service.create_task(
            user_id="user-1",
            title="Persistent task",
            source_thread_id="root-1",
            source_note_id=note.note_id,
        )
        manifest_path.write_text(
            json.dumps({"note_id": note.note_id, "task_id": task.task_id}),
            encoding="utf-8",
        )
    elif mode == "read":
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert runtime.repo.get_conversation("root-1").title == "Persistent conversation"
        assert runtime.repo.get("branch-1").child_thread_id == "child-1"
        assert runtime.repo.get_thread_owner(thread_id="child-1") == "user-1"
        assert runtime.user_repository.get_user("user-1").username == "persistent_user"
        assert runtime.user_repository.get_session("session-1").user_id == "user-1"
        assert (
            runtime.productivity_repository.get_note(
                note_id=manifest["note_id"],
                user_id="user-1",
            ).body
            == "Survives a runtime process restart."
        )
        assert (
            runtime.productivity_repository.get_task(
                task_id=manifest["task_id"],
                user_id="user-1",
            ).source_note_id
            == manifest["note_id"]
        )
    else:
        raise AssertionError(f"unknown mode: {mode}")
finally:
    runtime.close()
"""

_INTERRUPTED_INITIALIZATION_SCRIPT = """
import os
import sys
from pathlib import Path

from focus_agent.config import Settings
from focus_agent.core.types import ConversationRecord
from focus_agent.engine.runtime_persistence import _create_local_app_state_repositories
from focus_agent.repositories.sqlite_branch_repository import SQLiteBranchRepository
from focus_agent.repositories.sqlite_user_repository import SQLiteUserRepository

database_path = Path(sys.argv[1])
settings = Settings(branch_db_path=str(database_path))
branch_repository = SQLiteBranchRepository(str(database_path))
branch_repository.create_conversation(
    ConversationRecord(
        root_thread_id="root-before-interruption",
        owner_user_id="user-1",
        title="Created before interrupted startup",
    )
)

def interrupt_initialization(self, db_path):
    os._exit(86)

SQLiteUserRepository.__init__ = interrupt_initialization
_create_local_app_state_repositories(settings)
"""


def _run_runtime_process(mode: str, state_dir: Path) -> None:
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = "test-only-placeholder"
    completed = subprocess.run(
        [sys.executable, "-c", _RUNTIME_RESTART_SCRIPT, mode, str(state_dir)],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, (
        f"runtime {mode} process failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def test_local_runtime_app_state_survives_process_restart(tmp_path: Path) -> None:
    _run_runtime_process("write", tmp_path)

    database_path = tmp_path / "branches.sqlite3"
    assert database_path.is_file()

    _run_runtime_process("read", tmp_path)


def test_local_app_state_schema_initialization_recovers_after_interruption(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "branches.sqlite3"
    settings = Settings(branch_db_path=str(database_path))
    interrupted = subprocess.run(
        [sys.executable, "-c", _INTERRUPTED_INITIALIZATION_SCRIPT, str(database_path)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert interrupted.returncode == 86

    repo, user_repository, productivity_repository = _create_local_app_state_repositories(settings)

    assert (
        repo.get_conversation("root-before-interruption").title
        == "Created before interrupted startup"
    )
    assert user_repository.list_users().count == 0
    assert productivity_repository.list_notes(user_id="user-1") == []
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
