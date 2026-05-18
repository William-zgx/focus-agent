from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from focus_agent.api.routers.conversation_chat_context import router
from focus_agent.config import Settings
from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus
from focus_agent.repositories.sqlite_branch_repository import SQLiteBranchRepository


def test_thread_resolution_api_resolves_root_child_and_unknown(tmp_path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(
        thread_id="root-1",
        root_thread_id="root-1",
        owner_user_id="anonymous",
    )
    repo.ensure_thread_owner(
        thread_id="child-1",
        root_thread_id="root-1",
        owner_user_id="anonymous",
    )
    repo.create(
        BranchRecord(
            branch_id="branch-1",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            child_thread_id="child-1",
            return_thread_id="root-1",
            owner_user_id="anonymous",
            branch_name="Child Branch",
            branch_role=BranchRole.DEEP_DIVE,
            branch_depth=1,
            branch_status=BranchStatus.PAUSED,
        )
    )

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(settings=Settings(auth_enabled=False), repo=repo)
    client = TestClient(app)

    root = client.get("/v1/threads/root-1/resolution")
    child = client.get("/v1/threads/child-1/resolution")
    unknown = client.get("/v1/threads/unknown-thread/resolution")

    assert root.status_code == 200
    assert root.json()["root_thread_id"] == "root-1"
    assert root.json()["is_root"] is True
    assert root.json()["branch_id"] is None

    assert child.status_code == 200
    assert child.json()["input_thread_id"] == "child-1"
    assert child.json()["root_thread_id"] == "root-1"
    assert child.json()["source_thread_id"] == "child-1"
    assert child.json()["is_root"] is False
    assert child.json()["branch_id"] == "branch-1"
    assert child.json()["branch_status"] == "paused"

    assert unknown.status_code == 200
    assert unknown.json()["root_thread_id"] == "unknown-thread"
    assert unknown.json()["source_thread_id"] == "unknown-thread"
    assert unknown.json()["is_root"] is True
