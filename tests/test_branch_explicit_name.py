"""A user-provided branch name is explicit and never overwritten by AI naming, whatever the role."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage, HumanMessage

from focus_agent.config import Settings
from focus_agent.core.branching import (
    BranchActionKind,
    BranchRole,
)
from focus_agent.services.branches import BranchService
from focus_agent.services.branches.actions import (
    build_branch_action_proposal,
    explicit_branch_name_from_text,
)
from focus_agent.services.chat import ChatService
from focus_agent.services.chat.branch_navigation import execute_branch_action_navigation
from tests.test_branch_archive import FakeGraph, FakeRepo, _record
from tests.test_chat_service import (
    BranchActionBranchService,
    BranchActionGraph,
    _repo_with_child_branch,
)


class _RoleRepo(FakeRepo):
    def update_branch_role(self, branch_id: str, branch_role: BranchRole) -> None:
        record = self.records[branch_id]
        self.records[branch_id] = record.model_copy(update={"branch_role": branch_role})


class _NamingModel:
    """Reclassifies the role and proposes an AI name, like the real helper model."""

    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        system = str(getattr(messages[0], "content", "")) if messages else ""
        return "deep_dive" if "Classify the branch" in system else "AI Generated Name"


def _service() -> BranchService:
    parent = _record(
        branch_id="b-parent",
        parent_thread_id="root-1",
        child_thread_id="child-parent",
        branch_name="parent branch",
        branch_depth=1,
    )
    service = object.__new__(BranchService)
    service.repo = _RoleRepo([parent])
    service.graph = FakeGraph(
        {
            "branch_meta": {"is_archived": False},
            "messages": [HumanMessage(content="first"), AIMessage(content="reply")],
        }
    )
    service.thread_client = None
    service.proposal_model = _NamingModel()
    return service


def _run_first_turn_and_refresh(service: BranchService, child_thread_id: str):
    service.graph.values["messages"] = [
        *service.graph.values["messages"],
        HumanMessage(content="比较 Temporal 和 Cadence 的授权差异。"),
        AIMessage(content="两者都使用 MIT 许可……"),
    ]
    service.refresh_branch_metadata_after_first_turn(
        child_thread_id=child_thread_id, user_id="user-1"
    )
    return service.repo.get_by_child_thread_id(child_thread_id)


@pytest.mark.parametrize("role", [BranchRole.EXPLORE_ALTERNATIVES, BranchRole.DEEP_DIVE])
def test_fork_dialog_name_survives_first_turn_refresh_for_every_role(role: BranchRole) -> None:
    service = _service()

    record = service.fork_branch(
        parent_thread_id="child-parent",
        user_id="user-1",
        branch_name="授权对比",
        name_source="授权对比",
        branch_role=role,
    )
    meta = service.graph.values["branch_meta"]
    refreshed = _run_first_turn_and_refresh(service, record.child_thread_id)

    assert meta["branch_name_pending_ai"] is False
    assert refreshed.branch_name == "授权对比"
    assert service.graph.values["branch_meta"]["branch_name"] == "授权对比"


@pytest.mark.parametrize("role", [BranchRole.EXPLORE_ALTERNATIVES, BranchRole.DEEP_DIVE])
def test_card_edited_name_survives_first_turn_refresh_for_every_role(role: BranchRole) -> None:
    service = _service()
    action = build_branch_action_proposal(
        kind=BranchActionKind.FORK_CHILD_BRANCH,
        root_thread_id="root-1",
        source_thread_id="child-parent",
        target_parent_thread_id="child-parent",
        suggested_branch_name="授权对比",
        branch_role=role,
        reason="",
    ).model_copy(update={"suggested_branch_name_source": "explicit"})

    record, _ = execute_branch_action_navigation(
        action=action, user_id="user-1", branch_service=service
    )
    refreshed = _run_first_turn_and_refresh(service, record.child_thread_id)

    assert refreshed.branch_name == "授权对比"


@pytest.mark.parametrize(
    ("message", "name"),
    [
        ("新建一个分支叫授权对比，研究 Temporal 和 Cadence 的授权差异", "授权对比"),
        ("开一个分支，命名为授权对比", "授权对比"),
        ("新开分支，取名叫授权对比", "授权对比"),
        ("新建分支，名字叫授权对比", "授权对比"),
        ("Open a new branch called License Comparison", "License Comparison"),
    ],
)
def test_typed_branch_name_in_chat_is_explicit(message: str, name: str) -> None:
    assert explicit_branch_name_from_text(message) == name


def test_chat_command_name_is_forked_as_explicit_name(tmp_path: Path) -> None:
    repo = _repo_with_child_branch(tmp_path)
    graph = BranchActionGraph({"messages": [HumanMessage(content="根线程里的基础上下文。")]})
    branch_service = BranchActionBranchService()
    chat = ChatService(
        SimpleNamespace(settings=Settings(), graph=graph, repo=repo, branch_service=branch_service)
    )

    chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="新建一个分支叫授权对比，研究 Temporal 和 Cadence 的授权差异",
    )
    action = graph.values["branch_actions"][0]
    chat.execute_branch_action(thread_id="root-1", action_id=action["action_id"], user_id="owner-1")

    assert action["suggested_branch_name_source"] == "explicit"
    assert branch_service.fork_calls[-1]["branch_name"] == "授权对比"


def test_ai_suggested_name_still_refreshes_after_first_turn() -> None:
    service = _service()
    action = build_branch_action_proposal(
        kind=BranchActionKind.FORK_CHILD_BRANCH,
        root_thread_id="root-1",
        source_thread_id="child-parent",
        target_parent_thread_id="child-parent",
        suggested_branch_name="授权对比",
        branch_role=BranchRole.EXPLORE_ALTERNATIVES,
        reason="",
    )

    record, _ = execute_branch_action_navigation(
        action=action, user_id="user-1", branch_service=service
    )

    assert service.graph.values["branch_meta"]["branch_name_pending_ai"] is True
    refreshed = _run_first_turn_and_refresh(service, record.child_thread_id)
    assert refreshed.branch_name == "AI Generated Name"
