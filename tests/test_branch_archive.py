from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage, HumanMessage

from focus_agent.services.branches import BranchService
from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus


def _record(
    *,
    branch_id: str,
    parent_thread_id: str,
    child_thread_id: str,
    branch_name: str,
    branch_depth: int,
    branch_status: BranchStatus = BranchStatus.ACTIVE,
    is_archived: bool = False,
    archived_at: str | None = None,
) -> BranchRecord:
    return BranchRecord(
        branch_id=branch_id,
        root_thread_id="root-1",
        parent_thread_id=parent_thread_id,
        child_thread_id=child_thread_id,
        return_thread_id=parent_thread_id,
        owner_user_id="user-1",
        branch_name=branch_name,
        branch_role=BranchRole.DEEP_DIVE,
        branch_depth=branch_depth,
        branch_status=branch_status,
        is_archived=is_archived,
        archived_at=archived_at,
    )


class FakeRepo:
    def __init__(self, records: list[BranchRecord]):
        self.records = {record.branch_id: record for record in records}
        self.by_thread_id = {record.child_thread_id: record.branch_id for record in records}
        self.thread_owners = {"root-1": "user-1"} | {record.child_thread_id: record.owner_user_id for record in records}

    def assert_thread_owner(self, *, thread_id: str, owner_user_id: str) -> None:
        if self.thread_owners.get(thread_id) != owner_user_id:
            raise PermissionError(thread_id)

    def list_by_root_thread_id(self, root_thread_id: str) -> list[BranchRecord]:
        return [record for record in self.records.values() if record.root_thread_id == root_thread_id]

    def get_by_child_thread_id(self, child_thread_id: str) -> BranchRecord:
        return deepcopy(self.records[self.by_thread_id[child_thread_id]])

    def get(self, branch_id: str) -> BranchRecord:
        return deepcopy(self.records[branch_id])

    def ensure_thread_owner(self, *, thread_id: str, root_thread_id: str, owner_user_id: str) -> None:
        del root_thread_id
        self.thread_owners[thread_id] = owner_user_id

    def create(self, record: BranchRecord) -> None:
        self.records[record.branch_id] = record
        self.by_thread_id[record.child_thread_id] = record.branch_id
        self.thread_owners[record.child_thread_id] = record.owner_user_id

    def update_archive_state(self, branch_id: str, *, is_archived: bool) -> None:
        record = self.records[branch_id]
        self.records[branch_id] = record.model_copy(
            update={
                "is_archived": is_archived,
                "archived_at": "2026-04-12 10:00:00" if is_archived else None,
            }
        )

    def update_branch_name(self, branch_id: str, branch_name: str) -> None:
        record = self.records[branch_id]
        self.records[branch_id] = record.model_copy(update={"branch_name": branch_name})


class FakeGraph:
    def __init__(self, initial_values: dict):
        self.values = deepcopy(initial_values)
        self.last_update: dict | None = None

    def get_state(self, config):
        del config
        return SimpleNamespace(values=deepcopy(self.values))

    def update_state(self, config, values, as_node):
        del config, as_node
        self.values.update(deepcopy(values))
        self.last_update = deepcopy(values)


def test_get_branch_tree_hides_archived_subtrees_and_lists_archived_branches():
    service = object.__new__(BranchService)
    service.repo = FakeRepo(
        [
            _record(
                branch_id="b-active",
                parent_thread_id="root-1",
                child_thread_id="child-active",
                branch_name="active branch",
                branch_depth=1,
            ),
            _record(
                branch_id="b-archived",
                parent_thread_id="root-1",
                child_thread_id="child-archived",
                branch_name="archived branch",
                branch_depth=1,
                is_archived=True,
                archived_at="2026-04-12 09:00:00",
            ),
            _record(
                branch_id="b-hidden-grandchild",
                parent_thread_id="child-archived",
                child_thread_id="hidden-grandchild",
                branch_name="hidden grandchild",
                branch_depth=2,
            ),
            _record(
                branch_id="b-visible-grandchild",
                parent_thread_id="child-active",
                child_thread_id="visible-grandchild",
                branch_name="visible grandchild",
                branch_depth=2,
            ),
        ]
    )

    tree = service.get_branch_tree(root_thread_id="root-1", user_id="user-1")
    archived = service.list_archived_branches(root_thread_id="root-1", user_id="user-1")

    assert [child.thread_id for child in tree.children] == ["child-active"]
    assert [child.thread_id for child in tree.children[0].children] == ["visible-grandchild"]
    assert [node.thread_id for node in archived] == ["child-archived"]
    assert archived[0].is_archived is True


def test_archive_and_activate_branch_update_repo_and_graph_metadata():
    service = object.__new__(BranchService)
    service.repo = FakeRepo(
        [
            _record(
                branch_id="b-1",
                parent_thread_id="root-1",
                child_thread_id="child-1",
                branch_name="branch one",
                branch_depth=1,
            )
        ]
    )
    service.graph = FakeGraph(
        {
            "branch_meta": {
                "branch_id": "b-1",
                "root_thread_id": "root-1",
                "parent_thread_id": "root-1",
                "return_thread_id": "root-1",
                "branch_name": "branch one",
                "branch_role": "deep_dive",
                "branch_depth": 1,
                "branch_status": "active",
                "is_archived": False,
                "archived_at": None,
            }
        }
    )

    archived = service.archive_branch(child_thread_id="child-1", user_id="user-1")
    assert archived.is_archived is True
    assert archived.archived_at == "2026-04-12 10:00:00"
    assert service.graph.last_update["branch_meta"]["is_archived"] is True
    assert service.graph.last_update["branch_meta"]["archived_at"] == "2026-04-12 10:00:00"

    activated = service.activate_branch(child_thread_id="child-1", user_id="user-1")
    assert activated.is_archived is False
    assert activated.archived_at is None
    assert service.graph.last_update["branch_meta"]["is_archived"] is False
    assert service.graph.last_update["branch_meta"]["archived_at"] is None


def test_archive_repairs_incomplete_branch_meta_payload():
    service = object.__new__(BranchService)
    service.repo = FakeRepo(
        [
            _record(
                branch_id="b-2",
                parent_thread_id="root-1",
                child_thread_id="child-2",
                branch_name="repair me",
                branch_depth=1,
            )
        ]
    )
    service.graph = FakeGraph(
        {
            "branch_meta": {
                "is_archived": False,
                "archived_at": None,
            }
        }
    )

    archived = service.archive_branch(child_thread_id="child-2", user_id="user-1")

    assert archived.is_archived is True
    assert service.graph.last_update["branch_meta"]["branch_id"] == "b-2"
    assert service.graph.last_update["branch_meta"]["branch_name"] == "repair me"
    assert service.graph.last_update["branch_meta"]["parent_thread_id"] == "root-1"


def test_fork_branch_recovers_root_and_depth_from_repo_when_parent_meta_is_incomplete():
    parent = _record(
        branch_id="b-parent",
        parent_thread_id="root-1",
        child_thread_id="child-parent",
        branch_name="parent branch",
        branch_depth=2,
    )
    service = object.__new__(BranchService)
    service.repo = FakeRepo([parent])
    service.graph = FakeGraph({"branch_meta": {"is_archived": False}})
    service.thread_client = None
    service.proposal_model = None

    record = service.fork_branch(
        parent_thread_id="child-parent",
        user_id="user-1",
        branch_name=None,
        name_source="Investigate retry loop",
    )

    assert record.root_thread_id == "root-1"
    assert record.branch_depth == 3


def test_fork_branch_rejects_when_max_depth_would_be_exceeded():
    parent = _record(
        branch_id="b-parent-limit",
        parent_thread_id="root-1",
        child_thread_id="child-parent-limit",
        branch_name="deep parent",
        branch_depth=5,
    )
    service = object.__new__(BranchService)
    service.settings = SimpleNamespace(branch_max_depth=5)
    service.repo = FakeRepo([parent])
    service.graph = FakeGraph({"branch_meta": {"branch_depth": 5}})
    service.thread_client = None
    service.proposal_model = None

    with pytest.raises(ValueError, match="Maximum branch depth is 5"):
        service.fork_branch(
            parent_thread_id="child-parent-limit",
            user_id="user-1",
            branch_name=None,
            name_source="One more nested branch",
        )


def test_refresh_branch_name_after_first_turn_updates_repo_and_clears_pending_flag():
    parent = _record(
        branch_id="b-parent-rename",
        parent_thread_id="root-1",
        child_thread_id="child-parent-rename",
        branch_name="parent branch",
        branch_depth=1,
    )
    child = _record(
        branch_id="b-child-rename",
        parent_thread_id="child-parent-rename",
        child_thread_id="child-rename",
        branch_name="Import Retry Bug",
        branch_depth=2,
    )
    service = object.__new__(BranchService)
    service.repo = FakeRepo([parent, child])
    service.graph = FakeGraph(
        {
            "messages": [
                HumanMessage(content="帮我写一个 C 语言版本的快速排序。"),
                AIMessage(content="我先给你一个基础实现，再解释关键步骤。"),
            ],
            "rolling_summary": "用户在这个分支里继续深入快速排序的实现方式。",
            "branch_meta": {
                "branch_id": "b-child-rename",
                "root_thread_id": "root-1",
                "parent_thread_id": "child-parent-rename",
                "return_thread_id": "child-parent-rename",
                "branch_name": "Import Retry Bug",
                "branch_role": "deep_dive",
                "branch_depth": 2,
                "branch_status": "active",
                "is_archived": False,
                "archived_at": None,
                "branch_name_pending_ai": True,
            }
        }
    )

    class FakeModel:
        def invoke(self, _messages):
            return "Retry Loop Hotfix"

    service.proposal_model = FakeModel()

    updated = service.refresh_branch_name_after_first_turn(
        child_thread_id="child-rename",
        user_id="user-1",
    )

    assert updated is not None
    assert updated.branch_name == "Retry Loop Hotfix"
    assert service.repo.get("b-child-rename").branch_name == "Retry Loop Hotfix"
    assert service.graph.last_update["branch_meta"]["branch_name"] == "Retry Loop Hotfix"
    assert service.graph.last_update["branch_meta"]["branch_name_pending_ai"] is False
