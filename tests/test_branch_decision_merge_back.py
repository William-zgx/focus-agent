"""Merge-back intent on a child branch surfaces a visible review card, never a silent merge."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage, HumanMessage

from focus_agent.branch_decision import BranchDecisionService
from focus_agent.branch_decision.intent import merge_back_match
from focus_agent.config import Settings
from focus_agent.core.branching import BranchActionKind, BranchActionStatus
from focus_agent.core.governance import BranchDecisionAction, BranchDecisionStatus
from focus_agent.repositories.governance_repository import InMemoryGovernanceRepository
from focus_agent.services.branches.actions import normalize_branch_actions
from focus_agent.services.chat import ChatService
from focus_agent.services.coordination import create_in_memory_coordination_backend
from tests.test_chat_service import (
    BranchActionBranchService,
    BranchRecommendationGraph,
    _branch_recommendation_service,
    _repo_with_child_branch,
)

_BRANCH_META = {
    "branch_id": "branch-1",
    "root_thread_id": "root-1",
    "parent_thread_id": "root-1",
    "return_thread_id": "root-1",
    "branch_name": "济州岛旅行",
    "branch_role": "deep_dive",
    "branch_depth": 1,
    "branch_status": "active",
}


@pytest.mark.parametrize(
    "message",
    [
        "这个结论可以带回主线了",
        "合并回去吧",
        "可以合并了",
        "回到主线继续",
        "merge it back to main",
        "bring this back to main",
        "OK, ready to merge.",
    ],
)
def test_merge_back_phrases_are_detected(message: str) -> None:
    assert merge_back_match(message)


@pytest.mark.parametrize(
    "message",
    [
        "帮我整理一下要点",
        "好的，整理成表格",
        "先别合并，还有两个问题",
        "这个方案还不能合并",
        "don't merge it back yet",
        "在这个分支里研究亲子旅行和雨天备选，给出可合并回主线的明确结论。",
        "把 feature 分支 merge back 到 main 的 git 命令是什么",
    ],
)
def test_non_merge_back_phrases_are_ignored(message: str) -> None:
    assert merge_back_match(message) is None


# ----------------------------------------------------------------- pre-turn path


def _child_chat(tmp_path: Path, graph: object, **ports: object) -> ChatService:
    settings = Settings(
        agent_branch_recommendation_enabled=True,
        agent_branch_recommendation_mode="suggest",
    )
    repo = _repo_with_child_branch(tmp_path)
    decision_service = _branch_recommendation_service(settings, graph)
    decision_service.branch_service = SimpleNamespace(repo=repo)
    return ChatService(
        SimpleNamespace(
            settings=settings,
            graph=graph,
            repo=repo,
            branch_decision_service=decision_service,
            **ports,
        )
    )


def _branch_graph() -> BranchRecommendationGraph:
    return BranchRecommendationGraph(
        {
            "messages": [
                HumanMessage(content="研究南网能源的财报。"),
                AIMessage(content="结论：现金流稳定，估值合理。"),
            ]
        }
    )


def test_merge_back_on_child_branch_answers_then_shows_review_card(tmp_path: Path) -> None:
    graph = _branch_graph()
    chat = _child_chat(tmp_path, graph)

    payload = chat.send_message(
        thread_id="child-1", user_id="owner-1", message="这个结论可以带回主线了"
    )

    assert graph.invoke_calls == 1
    action = payload["branch_actions"][-1]
    assert action["kind"] == "return_parent_branch"
    assert action["status"] == "pending"
    assert action["delivery"] == "after_answer"
    assert action["merge_review_thread_id"] == "child-1"
    assert action["target_parent_thread_id"] == "root-1"
    assert action["target_parent_branch_name"] is None
    assert action["suggested_branch_name"] == "Nanwang Energy Deep Dive"
    assert action["reason"] == "你想把这个分支的结论带回上一层。"


def test_merge_back_wording_on_root_thread_shows_no_card(tmp_path: Path) -> None:
    graph = _branch_graph()
    chat = _child_chat(tmp_path, graph)

    payload = chat.send_message(thread_id="root-1", user_id="owner-1", message="可以合并了")

    assert graph.invoke_calls == 1
    assert payload.get("branch_actions") in (None, [])


def test_return_to_parent_executes_navigation_without_forking(tmp_path: Path) -> None:
    graph = _branch_graph()
    branch_service = BranchActionBranchService()
    chat = _child_chat(tmp_path, graph, branch_service=branch_service)
    chat.send_message(thread_id="child-1", user_id="owner-1", message="merge it back to main")
    action = graph.values["branch_actions"][-1]

    result = chat.execute_branch_action(
        thread_id="child-1", action_id=action["action_id"], user_id="owner-1"
    )

    assert branch_service.fork_calls == []
    assert result["navigation"] == {"root_thread_id": "root-1", "thread_id": "root-1"}
    assert result["handoff_message"] is None
    assert result["message"] == "Returned to the main thread."


# ----------------------------------------------------------------- after-turn path


class _Graph:
    def __init__(self, values: dict):
        self.values = deepcopy(values)

    def get_state(self, _config):
        return SimpleNamespace(values=deepcopy(self.values), interrupts=[])

    def update_state(self, _config, values, as_node=None):
        del _config, as_node
        self.values.update(deepcopy(values))


class _MergeSpyBranchService:
    def __init__(self) -> None:
        self.repo = SimpleNamespace(
            assert_thread_owner=lambda **_: None,
            get_by_child_thread_id=lambda _thread_id: None,
        )
        self.prepare_calls: list[dict] = []

    def prepare_merge_proposal(self, **kwargs):
        self.prepare_calls.append(kwargs)
        raise AssertionError("after-turn evaluation must not prepare a merge proposal")


def _after_turn(messages: list, *, branch: bool = True):
    values: dict = {"messages": messages}
    if branch:
        values["branch_meta"] = dict(_BRANCH_META)
    graph = _Graph(values)
    repository = InMemoryGovernanceRepository()
    branch_service = _MergeSpyBranchService()
    service = BranchDecisionService(
        settings=Settings(
            auth_enabled=False,
            agent_branch_decision_enabled=True,
            agent_branch_decision_mode="suggest",
            agent_branch_decision_min_confidence=0.70,
        ),
        graph=graph,
        governance_repository=repository,
        branch_service=branch_service,
        coordination_backend=create_in_memory_coordination_backend(),
    )
    service.evaluate_thread_turn(thread_id="child-1", root_thread_id="root-1", user_id="u-1")
    event = repository.list_branch_decision_events(source_thread_id="child-1")[0]
    return event, normalize_branch_actions(graph.values.get("branch_actions")), branch_service


def _turns(*pairs: tuple[str, str]) -> list:
    messages: list = []
    for human, ai in pairs:
        messages.extend([HumanMessage(content=human), AIMessage(content=ai)])
    return messages


def test_after_turn_merge_back_surfaces_card_instead_of_silent_merge() -> None:
    event, actions, branch_service = _after_turn(
        _turns(("研究亲子旅行路线。", "整理好了三条路线。"), ("可以合并了", "好的。"))
    )

    assert event.action == BranchDecisionAction.MERGE_CANDIDATE
    assert event.status == BranchDecisionStatus.PROMOTED
    assert branch_service.prepare_calls == []
    assert actions[-1].kind == BranchActionKind.RETURN_PARENT_BRANCH
    assert actions[-1].status == BranchActionStatus.PENDING
    assert actions[-1].merge_review_thread_id == "child-1"
    assert actions[-1].target_parent_thread_id == "root-1"
    assert actions[-1].delivery == "after_answer"


def test_after_turn_explicit_conclusion_surfaces_review_card() -> None:
    event, actions, branch_service = _after_turn(
        _turns(
            ("研究亲子旅行路线。", "列出了三条路线。"),
            ("补充雨天备选。", "补充了室内项目。"),
            ("总结一下这个分支的结论吧", "结论：路线二最合适。"),
        )
    )

    assert event.action == BranchDecisionAction.CONCLUDE
    assert event.status == BranchDecisionStatus.PROMOTED
    assert branch_service.prepare_calls == []
    assert actions[-1].kind == BranchActionKind.RETURN_PARENT_BRANCH
    assert actions[-1].reason == "这个分支看起来可以收尾了，审阅后再合并回上一层。"


@pytest.mark.parametrize("message", ["帮我整理一下要点", "summary please", "final check"])
def test_after_turn_tidy_up_wording_is_not_merge_evidence(message: str) -> None:
    event, actions, branch_service = _after_turn(
        _turns(
            ("研究亲子旅行路线。", "列出了三条路线。"),
            ("补充雨天备选。", "补充了室内项目。"),
            (message, "好的。"),
        )
    )

    assert (
        event.action
        not in {
            BranchDecisionAction.MERGE_CANDIDATE,
            BranchDecisionAction.CONCLUDE,
        }
        or event.status != BranchDecisionStatus.PROMOTED
    )
    assert actions == []
    assert branch_service.prepare_calls == []


def test_after_turn_conclusion_on_root_is_not_a_merge_candidate() -> None:
    event, actions, _ = _after_turn(
        _turns(("a", "b"), ("c", "d"), ("总结一下这个分支的结论吧", "结论。")),
        branch=False,
    )

    assert event.status != BranchDecisionStatus.PROMOTED
    assert actions == []
