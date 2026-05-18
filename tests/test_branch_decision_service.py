from copy import deepcopy
from types import SimpleNamespace

from langchain.messages import HumanMessage

from focus_agent.branch_decision import BranchDecisionService
from focus_agent.config import Settings
from focus_agent.config_parts.agent import load_agent_config
from focus_agent.core.branching import BranchActionKind, BranchActionStatus
from focus_agent.core.governance import BranchDecisionAction, BranchDecisionStatus
from focus_agent.repositories.governance_repository import InMemoryGovernanceRepository
from focus_agent.services.branch_actions import (
    build_branch_action_proposal,
    normalize_branch_actions,
)
from focus_agent.services.coordination import create_in_memory_coordination_backend


class FakeGraph:
    def __init__(self, values: dict):
        self.values = deepcopy(values)
        self.last_update: dict | None = None

    def get_state(self, _config):
        return SimpleNamespace(values=deepcopy(self.values), interrupts=[])

    def update_state(self, _config, values, as_node=None):
        del _config, as_node
        self.values.update(deepcopy(values))
        self.last_update = deepcopy(values)


class FakeBranchRepo:
    def assert_thread_owner(self, *, thread_id: str, owner_user_id: str) -> None:
        del thread_id, owner_user_id


class FakeBranchService:
    def __init__(self) -> None:
        self.repo = FakeBranchRepo()


def _settings(**overrides) -> Settings:
    return Settings(
        auth_enabled=False,
        agent_branch_decision_enabled=True,
        agent_branch_decision_mode=overrides.pop("mode", "shadow"),
        agent_branch_decision_min_confidence=0.70,
        agent_branch_recommendation_enabled=overrides.pop("recommendation_enabled", False),
        agent_branch_recommendation_mode=overrides.pop("recommendation_mode", "shadow"),
        agent_branch_recommendation_min_confidence=overrides.pop(
            "recommendation_min_confidence",
            0.70,
        ),
        **overrides,
    )


def _service(
    *, mode: str = "shadow"
) -> tuple[BranchDecisionService, FakeGraph, InMemoryGovernanceRepository]:
    graph = FakeGraph(
        {
            "messages": [
                HumanMessage(content="请另开一个分支，并行探索另一个方案。"),
                HumanMessage(content="这个方向和主线差异比较大，适合分支继续。"),
            ],
        }
    )
    repository = InMemoryGovernanceRepository()
    service = BranchDecisionService(
        settings=_settings(mode=mode),
        graph=graph,
        governance_repository=repository,
        branch_service=FakeBranchService(),
        coordination_backend=create_in_memory_coordination_backend(),
    )
    return service, graph, repository


def _recommendation_service(
    *,
    mode: str = "suggest",
    values: dict | None = None,
) -> tuple[BranchDecisionService, FakeGraph, InMemoryGovernanceRepository]:
    graph = FakeGraph(values or {"messages": [HumanMessage(content="继续分析主线。")]})
    repository = InMemoryGovernanceRepository()
    service = BranchDecisionService(
        settings=_settings(
            recommendation_enabled=True,
            recommendation_mode=mode,
            recommendation_min_confidence=0.70,
        ),
        graph=graph,
        governance_repository=repository,
        branch_service=FakeBranchService(),
        coordination_backend=create_in_memory_coordination_backend(),
    )
    return service, graph, repository


def test_branch_decision_shadow_records_without_creating_branch_action() -> None:
    service, graph, repository = _service()

    payload = service.evaluate_thread_turn(
        thread_id="thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        request_id="req-1",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    assert payload["decision_id"] == event.decision_id
    assert event.status == BranchDecisionStatus.SHADOWED
    assert event.score >= 0.70
    assert "branch_actions" not in graph.values


def test_branch_decision_promote_creates_pending_branch_action() -> None:
    service, graph, repository = _service()
    service.evaluate_thread_turn(
        thread_id="thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        request_id="req-1",
    )
    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]

    promoted = service.promote_decision(
        thread_id="thread-1",
        decision_id=event.decision_id,
        user_id="u-1",
    )
    actions = normalize_branch_actions(graph.values.get("branch_actions"))

    assert promoted.status == BranchDecisionStatus.PROMOTED
    assert promoted.promoted_action_id == actions[0].action_id
    assert actions[0].status == BranchActionStatus.PENDING
    assert actions[0].source == "branch_decision"
    assert actions[0].source_decision_id == event.decision_id


def test_branch_decision_execute_mode_downgrades_to_suggest() -> None:
    service, graph, repository = _service(mode="execute")

    service.evaluate_thread_turn(
        thread_id="thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        request_id="req-1",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    actions = normalize_branch_actions(graph.values.get("branch_actions"))
    assert event.status == BranchDecisionStatus.PROMOTED
    assert event.metadata["downgraded_from_execute"] is True
    assert actions[0].status == BranchActionStatus.PENDING


def test_branch_recommendation_suggests_child_pending_action() -> None:
    service, graph, repository = _recommendation_service()

    payload = service.recommend_for_message(
        thread_id="thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message="请新开一个子分支深入研究方案 B。",
        request_id="req-rec-1",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    actions = normalize_branch_actions(graph.values.get("branch_actions"))
    assert payload["decision_id"] == event.decision_id
    assert event.action == BranchDecisionAction.FORK_CHILD_BRANCH
    assert event.status == BranchDecisionStatus.PROMOTED
    assert event.recommendation_target == "fork_child_branch"
    assert event.target_parent_thread_id == "thread-1"
    assert event.confidence == event.score
    assert event.metadata["phase"] == "pre_turn"
    assert event.metadata["recommendation_target"] == "fork_child_branch"
    assert actions[0].kind == BranchActionKind.FORK_CHILD_BRANCH
    assert actions[0].target_parent_thread_id == "thread-1"
    assert actions[0].status == BranchActionStatus.PENDING
    assert actions[0].source_decision_id == event.decision_id


def test_branch_recommendation_retry_reuses_promoted_event_without_repromoting() -> None:
    service, graph, repository = _recommendation_service()

    first = service.recommend_for_message(
        thread_id="thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message="请新开一个子分支深入研究方案 B。",
        request_id="req-rec-idempotent",
    )
    first_action_id = normalize_branch_actions(graph.values.get("branch_actions"))[0].action_id
    graph.values["branch_actions"] = []

    second = service.recommend_for_message(
        thread_id="thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message="请新开一个子分支深入研究方案 B。",
        request_id="req-rec-idempotent",
    )

    events = repository.list_branch_decision_events(source_thread_id="thread-1")
    assert len(events) == 1
    assert second["decision_id"] == first["decision_id"]
    assert events[0].status == BranchDecisionStatus.PROMOTED
    assert events[0].promoted_action_id == first_action_id
    assert graph.values["branch_actions"] == []


def test_branch_recommendation_suggests_sibling_from_child_branch() -> None:
    service, graph, repository = _recommendation_service(
        values={
            "messages": [HumanMessage(content="当前分支已经在研究方案 A。")],
            "branch_meta": {
                "branch_id": "branch-1",
                "root_thread_id": "root-1",
                "parent_thread_id": "parent-1",
                "return_thread_id": "parent-1",
                "branch_name": "方案 A",
            },
        }
    )

    service.recommend_for_message(
        thread_id="thread-1",
        user_id="u-1",
        message="这个新问题适合另开同级分支并列研究。",
        request_id="req-rec-2",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    actions = normalize_branch_actions(graph.values.get("branch_actions"))
    assert event.action == BranchDecisionAction.FORK_SIBLING_BRANCH
    assert event.status == BranchDecisionStatus.PROMOTED
    assert event.recommendation_target == "fork_sibling_branch"
    assert event.target_parent_thread_id == "parent-1"
    assert actions[0].kind == BranchActionKind.FORK_SIBLING_BRANCH
    assert actions[0].target_parent_thread_id == "parent-1"
    assert actions[0].status == BranchActionStatus.PENDING


def test_branch_recommendation_can_continue_without_branch_action() -> None:
    service, graph, repository = _recommendation_service()

    service.evaluate_pre_turn_recommendation(
        thread_id="thread-1",
        user_id="u-1",
        message="不用分支，继续在当前线程回答这个问题。",
        request_id="req-rec-3",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    assert event.action == BranchDecisionAction.CONTINUE_CURRENT
    assert event.status == BranchDecisionStatus.SKIPPED
    assert "branch_actions" not in graph.values


def test_branch_recommendation_downgrades_root_sibling_to_child() -> None:
    service, graph, repository = _recommendation_service()

    service.recommend_for_message(
        thread_id="thread-1",
        user_id="u-1",
        message="换个方向同级研究备用方案。",
        request_id="req-rec-4",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    actions = normalize_branch_actions(graph.values.get("branch_actions"))
    assert event.action == BranchDecisionAction.FORK_CHILD_BRANCH
    assert event.recommendation_target == "fork_child_branch"
    assert actions[0].kind == BranchActionKind.FORK_CHILD_BRANCH
    assert actions[0].target_parent_thread_id == "thread-1"


def test_branch_recommendation_blocks_when_pending_action_exists() -> None:
    pending = build_branch_action_proposal(
        kind=BranchActionKind.FORK_CHILD_BRANCH,
        root_thread_id="root-1",
        source_thread_id="thread-1",
        target_parent_thread_id="thread-1",
        suggested_branch_name="Pending",
        reason="Existing pending action.",
    )
    service, graph, repository = _recommendation_service(
        values={
            "messages": [HumanMessage(content="继续分析主线。")],
            "branch_actions": [pending.model_dump(mode="json")],
        }
    )

    service.recommend_for_message(
        thread_id="thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message="请新开一个子分支深入研究方案 B。",
        request_id="req-rec-5",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    actions = normalize_branch_actions(graph.values.get("branch_actions"))
    assert event.status == BranchDecisionStatus.BLOCKED
    assert [action.action_id for action in actions] == [pending.action_id]


def test_branch_recommendation_blocks_when_child_depth_limit_would_be_exceeded() -> None:
    service, graph, repository = _recommendation_service(
        values={
            "messages": [HumanMessage(content="当前已经很深。")],
            "branch_meta": {
                "branch_id": "branch-limit",
                "root_thread_id": "root-1",
                "parent_thread_id": "parent-1",
                "return_thread_id": "parent-1",
                "branch_name": "Depth Limit",
                "branch_depth": 5,
            },
        }
    )

    service.recommend_for_message(
        thread_id="thread-1",
        user_id="u-1",
        message="继续开子分支深入分析。",
        request_id="req-rec-6",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    assert event.status == BranchDecisionStatus.BLOCKED
    assert "branch_actions" not in graph.values


def test_branch_recommendation_config_loads_from_env() -> None:
    values = load_agent_config(
        {
            "AGENT_BRANCH_RECOMMENDATION_ENABLED": "true",
            "AGENT_BRANCH_RECOMMENDATION_MODE": "suggest",
            "AGENT_BRANCH_RECOMMENDATION_MIN_CONFIDENCE": "0.82",
        },
        Settings(),
    )

    assert values["agent_branch_recommendation_enabled"] is True
    assert values["agent_branch_recommendation_mode"] == "suggest"
    assert values["agent_branch_recommendation_min_confidence"] == 0.82
