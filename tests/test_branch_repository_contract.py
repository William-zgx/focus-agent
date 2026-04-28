from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from focus_agent.core.branching import (
    BranchRecord,
    BranchRole,
    BranchStatus,
    MergeDecision,
    MergeMode,
    MergeProposal,
    MergeTarget,
)
from focus_agent.core.types import ConversationRecord
from focus_agent.repositories.branch_repository import BranchRepository
from focus_agent.repositories.postgres_branch_repository import PostgresBranchRepository
from focus_agent.repositories.sqlite_branch_repository import SQLiteBranchRepository
from focus_agent.security.ownership import OwnershipAuditEvent


@dataclass(frozen=True)
class RepositoryFactory:
    backend: str

    def create(self, tmp_path: Path) -> BranchRepository:
        if self.backend == "sqlite":
            return SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
        if self.backend == "postgres":
            database_uri = os.environ["DATABASE_URI"]
            repository = PostgresBranchRepository(database_uri)
            repository.setup()
            return repository
        raise AssertionError(f"Unknown backend: {self.backend}")


POSTGRES_SKIP_REASON = "DATABASE_URI is not set; skipping Postgres BranchRepository contract cases"


def _repository_params() -> list[pytest.ParameterSet]:
    params = [pytest.param(RepositoryFactory("sqlite"), id="sqlite")]
    postgres_mark = []
    if not os.environ.get("DATABASE_URI"):
        postgres_mark.append(pytest.mark.skip(reason=POSTGRES_SKIP_REASON))
    params.append(pytest.param(RepositoryFactory("postgres"), marks=postgres_mark, id="postgres"))
    return params


@pytest.fixture(params=_repository_params())
def repo_factory(request: pytest.FixtureRequest) -> RepositoryFactory:
    return request.param


@pytest.fixture
def repository(repo_factory: RepositoryFactory, tmp_path: Path) -> Iterator[BranchRepository]:
    repo = repo_factory.create(tmp_path)
    if isinstance(repo, PostgresBranchRepository):
        _clear_postgres_state(repo)
    yield repo
    if isinstance(repo, PostgresBranchRepository):
        _clear_postgres_state(repo)


def _clear_postgres_state(repo: PostgresBranchRepository) -> None:
    with repo._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM focus_branches")
            cur.execute("DELETE FROM focus_conversations")
            cur.execute("DELETE FROM focus_thread_access")


def _branch(
    branch_id: str,
    *,
    root_thread_id: str = "root-1",
    parent_thread_id: str = "root-1",
    child_thread_id: str | None = None,
    return_thread_id: str | None = None,
    owner_user_id: str = "user-1",
    branch_name: str | None = None,
    branch_role: BranchRole = BranchRole.EXPLORE_ALTERNATIVES,
    branch_depth: int = 1,
    branch_status: BranchStatus = BranchStatus.ACTIVE,
    is_archived: bool = False,
) -> BranchRecord:
    return BranchRecord(
        branch_id=branch_id,
        root_thread_id=root_thread_id,
        parent_thread_id=parent_thread_id,
        child_thread_id=child_thread_id or f"{branch_id}-thread",
        return_thread_id=return_thread_id or parent_thread_id,
        owner_user_id=owner_user_id,
        branch_name=branch_name or branch_id,
        branch_role=branch_role,
        branch_depth=branch_depth,
        branch_status=branch_status,
        is_archived=is_archived,
    )


def _conversation(
    root_thread_id: str,
    *,
    owner_user_id: str = "user-1",
    title: str | None = None,
    title_pending_ai: bool = False,
    is_archived: bool = False,
) -> ConversationRecord:
    return ConversationRecord(
        root_thread_id=root_thread_id,
        owner_user_id=owner_user_id,
        title=title or root_thread_id,
        title_pending_ai=title_pending_ai,
        is_archived=is_archived,
    )


def test_thread_owner_contract(repository: BranchRepository):
    audit_events: list[OwnershipAuditEvent] = []

    repository.ensure_thread_owner(
        thread_id="root-1",
        root_thread_id="root-1",
        owner_user_id="user-1",
        audit_events=audit_events,
        request_id="req-1",
    )
    repository.ensure_thread_owner(
        thread_id="child-1",
        root_thread_id="root-1",
        owner_user_id="user-1",
        audit_events=audit_events,
    )

    assert repository.get_thread_owner(thread_id="root-1") == "user-1"
    assert repository.get_thread_owner(thread_id="child-1") == "user-1"
    assert repository.get_thread_owner(thread_id="missing") is None
    repository.assert_thread_owner(thread_id="root-1", owner_user_id="user-1")
    repository.ensure_thread_owner(
        thread_id="root-1",
        root_thread_id="root-1",
        owner_user_id="user-1",
        audit_events=audit_events,
    )
    assert [event.decision for event in audit_events] == ["allow", "allow", "allow"]

    with pytest.raises(PermissionError):
        repository.assert_thread_owner(thread_id="root-1", owner_user_id="user-2")
    with pytest.raises(PermissionError):
        repository.assert_thread_owner(thread_id="missing", owner_user_id="user-1")
    with pytest.raises(PermissionError):
        repository.ensure_thread_owner(
            thread_id="root-1",
            root_thread_id="root-1",
            owner_user_id="user-2",
        )
    assert repository.get_thread_owner(thread_id="root-1") == "user-1"


def test_conversation_crud_contract(repository: BranchRepository):
    repository.ensure_thread_owner(thread_id="user-1-main", root_thread_id="user-1-main", owner_user_id="user-1")
    repository.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="user-1")
    repository.ensure_thread_owner(thread_id="root-2", root_thread_id="root-2", owner_user_id="user-2")

    created = repository.create_conversation(
        _conversation(
            "root-1",
            title="Conversation 1",
            title_pending_ai=True,
        )
    )

    assert created.root_thread_id == "root-1"
    assert created.owner_user_id == "user-1"
    assert created.title == "Conversation 1"
    assert created.title_pending_ai is True
    assert created.is_archived is False
    assert created.archived_at is None

    assert repository.get_conversation("root-1").title == "Conversation 1"

    user_one_conversations = repository.list_conversations(owner_user_id="user-1")
    user_one_titles = {item.root_thread_id: item.title for item in user_one_conversations}
    assert user_one_titles["root-1"] == "Conversation 1"
    assert user_one_titles["user-1-main"] == "Main"
    assert "root-2" not in user_one_titles

    renamed = repository.update_conversation_title(
        root_thread_id="root-1",
        owner_user_id="user-1",
        title="Renamed conversation",
        title_pending_ai=False,
    )
    assert renamed.title == "Renamed conversation"
    assert renamed.title_pending_ai is False

    title_only_update = repository.update_conversation_title(
        root_thread_id="root-1",
        owner_user_id="user-1",
        title="Title only",
    )
    assert title_only_update.title == "Title only"
    assert title_only_update.title_pending_ai is False

    archived = repository.update_conversation_archive_state(
        root_thread_id="root-1",
        owner_user_id="user-1",
        is_archived=True,
    )
    assert archived.is_archived is True
    assert archived.archived_at is not None

    restored = repository.update_conversation_archive_state(
        root_thread_id="root-1",
        owner_user_id="user-1",
        is_archived=False,
    )
    assert restored.is_archived is False
    assert restored.archived_at is None

    with pytest.raises(PermissionError):
        repository.update_conversation_title(
            root_thread_id="root-1",
            owner_user_id="user-2",
            title="Forbidden",
        )
    with pytest.raises(PermissionError):
        repository.update_conversation_archive_state(
            root_thread_id="root-1",
            owner_user_id="user-2",
            is_archived=True,
        )


def test_branch_crud_updates_and_merge_payload_contract(repository: BranchRepository):
    branch = _branch(
        "branch-1",
        child_thread_id="child-1",
        branch_name="Explore options",
        branch_role=BranchRole.DEEP_DIVE,
        branch_depth=1,
        branch_status=BranchStatus.ACTIVE,
    )
    repository.create(branch)

    loaded = repository.get("branch-1")
    assert loaded == branch
    assert repository.get_by_child_thread_id("child-1") == branch

    repository.update_status("branch-1", BranchStatus.PAUSED)
    repository.update_branch_name("branch-1", "Paused options")
    repository.update_branch_role("branch-1", BranchRole.EXECUTE)
    updated = repository.get("branch-1")
    assert updated.branch_status == BranchStatus.PAUSED
    assert updated.branch_name == "Paused options"
    assert updated.branch_role == BranchRole.EXECUTE

    proposal = MergeProposal(
        summary="Decision summary",
        key_findings=["finding-1"],
        open_questions=["question-1"],
        evidence_refs=["artifact://evidence"],
        artifacts=["artifact-1"],
        recommended_import_mode=MergeMode.SUMMARY_PLUS_EVIDENCE,
    )
    decision = MergeDecision(
        approved=False,
        mode=MergeMode.SELECTED_ARTIFACTS,
        target=MergeTarget.ROOT_THREAD,
        rationale="Needs more work",
        selected_artifacts=["artifact-1"],
    )
    repository.save_merge_proposal("branch-1", proposal)
    repository.save_merge_decision("branch-1", decision)
    merged = repository.get("branch-1")
    assert merged.merge_proposal == proposal.model_dump(mode="json")
    assert merged.merge_decision == decision.model_dump(mode="json")


def test_branch_archive_activate_and_list_contract(repository: BranchRepository):
    records = [
        _branch(
            "branch-child-b",
            child_thread_id="child-b",
            branch_name="Beta",
            branch_depth=1,
        ),
        _branch(
            "branch-child-a",
            child_thread_id="child-a",
            branch_name="Alpha",
            branch_depth=1,
        ),
        _branch(
            "branch-grandchild",
            parent_thread_id="child-a",
            child_thread_id="grandchild-a",
            return_thread_id="child-a",
            branch_name="Gamma",
            branch_role=BranchRole.VERIFY,
            branch_depth=2,
        ),
        _branch(
            "other-root-branch",
            root_thread_id="root-2",
            parent_thread_id="root-2",
            child_thread_id="other-child",
            branch_name="Other",
        ),
    ]
    for record in records:
        repository.create(record)

    repository.update_archive_state("branch-child-a", is_archived=True)
    archived = repository.get("branch-child-a")
    assert archived.is_archived is True
    assert archived.archived_at is not None

    repository.update_archive_state("branch-child-a", is_archived=False)
    activated = repository.get("branch-child-a")
    assert activated.is_archived is False
    assert activated.archived_at is None

    assert [record.branch_id for record in repository.list_by_root_thread_id("root-1")] == [
        "branch-child-a",
        "branch-child-b",
        "branch-grandchild",
    ]
    assert [record.branch_id for record in repository.list_by_parent_thread_id("root-1")] == [
        "branch-child-a",
        "branch-child-b",
    ]
    assert [record.branch_id for record in repository.list_by_parent_thread_id("child-a")] == [
        "branch-grandchild"
    ]
    assert repository.list_by_root_thread_id("missing-root") == []
    assert repository.list_by_parent_thread_id("missing-parent") == []


def test_missing_record_contract(repository: BranchRepository):
    with pytest.raises(KeyError, match="Unknown branch_id: missing-branch"):
        repository.get("missing-branch")
    with pytest.raises(KeyError, match="Unknown child_thread_id: missing-child"):
        repository.get_by_child_thread_id("missing-child")
    with pytest.raises(KeyError, match="Unknown root_thread_id: missing-root"):
        repository.get_conversation("missing-root")
    with pytest.raises(KeyError, match="Unknown root_thread_id: missing-root"):
        repository.update_conversation_title(
            root_thread_id="missing-root",
            owner_user_id="user-1",
            title="Missing",
        )
    with pytest.raises(KeyError, match="Unknown root_thread_id: missing-root"):
        repository.update_conversation_archive_state(
            root_thread_id="missing-root",
            owner_user_id="user-1",
            is_archived=True,
        )
