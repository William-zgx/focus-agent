from copy import deepcopy
from types import SimpleNamespace

import pytest
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
    recommendation_min_confidence: float = 0.70,
) -> tuple[BranchDecisionService, FakeGraph, InMemoryGovernanceRepository]:
    graph = FakeGraph(values or {"messages": [HumanMessage(content="继续分析主线。")]})
    repository = InMemoryGovernanceRepository()
    service = BranchDecisionService(
        settings=_settings(
            recommendation_enabled=True,
            recommendation_mode=mode,
            recommendation_min_confidence=recommendation_min_confidence,
        ),
        graph=graph,
        governance_repository=repository,
        branch_service=FakeBranchService(),
        coordination_backend=create_in_memory_coordination_backend(),
    )
    return service, graph, repository


class _FakeSemanticClassifier:
    def __init__(self, *, result: object = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict] = []
        self.results: list[object] = []

    def classify_topic_relation(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if callable(self.result):
            result = self.result(**kwargs)
        else:
            result = self.result
        self.results.append(result)
        return result


def _attach_semantic_classifier(
    service: BranchDecisionService,
    classifier: _FakeSemanticClassifier,
) -> None:
    service.branch_service.branch_recommendation_semantic_classifier = classifier


def _semantic_topic_shift_result(
    *,
    confidence: float = 0.91,
    topic_shift: bool = True,
    recommended_action: BranchDecisionAction = BranchDecisionAction.FORK_CHILD_BRANCH,
    raw_response: object | None = None,
) -> dict:
    return {
        "status": "success",
        "topic_shift": topic_shift,
        "confidence": confidence,
        "recommended_action": recommended_action.value,
        "relatedness": "low" if topic_shift else "high",
        "raw_response": raw_response,
        "rationale": "fake deterministic semantic classifier",
    }


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
    assert event.metadata["recommendation_user_visible"] is True
    assert event.metadata["diagnostic"]["gate_reason"] == "eligible"
    assert actions[0].kind == BranchActionKind.FORK_CHILD_BRANCH
    assert actions[0].target_parent_thread_id == "thread-1"
    assert actions[0].status == BranchActionStatus.PENDING
    assert actions[0].source_decision_id == event.decision_id
    assert actions[0].handoff_message == "深入研究方案 B"


def test_branch_recommendation_topic_drift_without_branch_words_forks_child() -> None:
    service, graph, repository = _recommendation_service()

    service.recommend_for_message(
        thread_id="thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message="换个主题，先看另一个问题：酒店取消政策怎么处理？",
        request_id="req-topic-drift-root",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    actions = normalize_branch_actions(graph.values.get("branch_actions"))
    topic_drift_signal = next(
        signal for signal in event.signals if signal.name == "recommendation_topic_drift"
    )
    assert event.action == BranchDecisionAction.FORK_CHILD_BRANCH
    assert event.status == BranchDecisionStatus.PROMOTED
    assert event.recommendation_target == "fork_child_branch"
    assert topic_drift_signal.value["has_topic_drift"] is True
    assert topic_drift_signal.value["recommendation_target"] == "fork_child_branch"
    assert actions[0].kind == BranchActionKind.FORK_CHILD_BRANCH
    assert actions[0].target_parent_thread_id == "thread-1"
    assert actions[0].handoff_message == "酒店取消政策怎么处理？"


def test_branch_recommendation_explicit_continue_wins_over_semantic_topic_shift() -> None:
    classifier = _FakeSemanticClassifier(
        result=_semantic_topic_shift_result(),
    )
    service, graph, repository = _recommendation_service(
        values={
            "messages": [HumanMessage(content="当前分支已经在研究济州岛旅行。")],
            "branch_meta": {
                "branch_id": "branch-1",
                "root_thread_id": "root-1",
                "parent_thread_id": "parent-1",
                "return_thread_id": "parent-1",
                "branch_name": "济州岛旅行",
            },
        }
    )
    _attach_semantic_classifier(service, classifier)

    payload = service.recommend_for_message(
        thread_id="thread-1",
        user_id="u-1",
        message="不用分支，继续在当前线程回答济州岛自然风光。",
        request_id="req-semantic-explicit-continue",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    assert payload is not None
    assert classifier.calls == []
    assert payload["action"] == "continue_current"
    assert event.action == BranchDecisionAction.CONTINUE_CURRENT
    assert event.status == BranchDecisionStatus.SKIPPED
    assert event.metadata["reason"] == "continue_current"
    assert "branch_actions" not in graph.values


@pytest.mark.parametrize(
    ("values", "thread_id", "message", "expected_action", "expected_parent"),
    [
        (
            {
                "messages": [HumanMessage(content="当前在讨论济州岛美食。")],
                "selected_model": "openai:semantic-selected",
            },
            "root-thread",
            "酒店取消政策有哪些注意事项？",
            BranchDecisionAction.FORK_CHILD_BRANCH,
            "root-thread",
        ),
        (
            {
                "messages": [HumanMessage(content="当前分支已经在研究济州岛美食。")],
                "branch_meta": {
                    "branch_id": "branch-1",
                    "root_thread_id": "root-1",
                    "parent_thread_id": "parent-1",
                    "return_thread_id": "parent-1",
                    "branch_name": "济州岛美食",
                },
            },
            "child-thread",
            "酒店取消政策有哪些注意事项？",
            BranchDecisionAction.FORK_SIBLING_BRANCH,
            "parent-1",
        ),
    ],
)
def test_branch_recommendation_semantic_low_related_topic_shift_routes_by_branch_context(
    values: dict,
    thread_id: str,
    message: str,
    expected_action: BranchDecisionAction,
    expected_parent: str,
) -> None:
    classifier = _FakeSemanticClassifier(
        result=_semantic_topic_shift_result(
            recommended_action=BranchDecisionAction.FORK_SIBLING_BRANCH,
        ),
    )
    service, graph, repository = _recommendation_service(values=values)
    _attach_semantic_classifier(service, classifier)

    service.recommend_for_message(
        thread_id=thread_id,
        user_id="u-1",
        message=message,
        request_id=f"req-semantic-{expected_action.value}",
    )

    event = repository.list_branch_decision_events(source_thread_id=thread_id)[0]
    actions = normalize_branch_actions(graph.values.get("branch_actions"))
    assert classifier.calls
    if values.get("selected_model"):
        assert classifier.calls[0]["selected_model"] == "openai:semantic-selected"
    assert event.action == expected_action
    assert event.status == BranchDecisionStatus.PROMOTED
    assert event.metadata["semantic_classifier_status"] == "success"
    assert event.recommendation_target == expected_action.value
    assert event.target_parent_thread_id == expected_parent
    assert actions[0].kind.value == expected_action.value
    assert actions[0].target_parent_thread_id == expected_parent


@pytest.mark.parametrize(
    "message",
    [
        "我不想探索美食了，我现在想探索一下济州岛的自然风光。",
        "我想看一下，如果10月份去日本旅行的话，有什么好看的建议？",
    ],
)
def test_branch_recommendation_semantic_travel_regressions_suggest_sibling(
    message: str,
) -> None:
    classifier = _FakeSemanticClassifier(
        result=_semantic_topic_shift_result(
            recommended_action=BranchDecisionAction.FORK_CHILD_BRANCH,
        ),
    )
    service, graph, repository = _recommendation_service(
        values={
            "messages": [HumanMessage(content="当前分支已经在探索济州岛美食。")],
            "branch_meta": {
                "branch_id": "branch-food",
                "root_thread_id": "root-1",
                "parent_thread_id": "parent-1",
                "return_thread_id": "parent-1",
                "branch_name": "济州岛美食",
            },
        }
    )
    _attach_semantic_classifier(service, classifier)

    service.recommend_for_message(
        thread_id="thread-1",
        user_id="u-1",
        message=message,
        request_id=f"req-semantic-travel-{abs(hash(message))}",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    actions = normalize_branch_actions(graph.values.get("branch_actions"))
    assert classifier.calls
    assert event.action == BranchDecisionAction.FORK_SIBLING_BRANCH
    assert event.status == BranchDecisionStatus.PROMOTED
    assert event.metadata["semantic_classifier_status"] == "success"
    assert event.recommendation_target == "fork_sibling_branch"
    assert event.target_parent_thread_id == "parent-1"
    assert actions[0].kind == BranchActionKind.FORK_SIBLING_BRANCH
    assert actions[0].target_parent_thread_id == "parent-1"


@pytest.mark.parametrize(
    "message",
    [
        "今年10月去济州岛旅行，请用100字以内给出美食市场主题。",
        "换个主题，先研究大阪环球影城预算。",
    ],
)
def test_branch_recommendation_requires_history_before_topic_shift_routing(
    message: str,
) -> None:
    classifier = _FakeSemanticClassifier(
        result=_semantic_topic_shift_result(
            recommended_action=BranchDecisionAction.FORK_CHILD_BRANCH,
        ),
    )
    service, graph, repository = _recommendation_service(values={"messages": []})
    _attach_semantic_classifier(service, classifier)

    service.recommend_for_message(
        thread_id="thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message=message,
        request_id=f"req-no-history-{abs(hash(message))}",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    assert classifier.calls == []
    assert event.action == BranchDecisionAction.CONTINUE_CURRENT
    assert event.status == BranchDecisionStatus.SKIPPED
    assert event.metadata["reason"] == "continue_current"
    assert "branch_actions" not in graph.values


@pytest.mark.parametrize(
    ("classifier_result", "classifier_error", "expected_status"),
    [
        (None, RuntimeError("model unavailable"), "unavailable"),
        ("not-json", None, "error"),
        (_semantic_topic_shift_result(confidence=0.41), None, "success"),
    ],
)
def test_branch_recommendation_semantic_failures_fail_closed_to_continue_current(
    classifier_result: object,
    classifier_error: Exception | None,
    expected_status: str,
) -> None:
    classifier = _FakeSemanticClassifier(
        result=classifier_result,
        error=classifier_error,
    )
    service, graph, repository = _recommendation_service(
        values={"messages": [HumanMessage(content="当前在讨论济州岛美食。")]}
    )
    _attach_semantic_classifier(service, classifier)

    service.recommend_for_message(
        thread_id="thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message="酒店取消政策有哪些注意事项？",
        request_id=f"req-semantic-fail-{expected_status}",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    assert classifier.calls
    assert event.action == BranchDecisionAction.CONTINUE_CURRENT
    assert event.status == BranchDecisionStatus.SKIPPED
    assert event.metadata["reason"] == "continue_current"
    assert event.metadata["semantic_classifier_status"] == expected_status
    assert "branch_actions" not in graph.values


@pytest.mark.parametrize(
    ("values", "expected_reason"),
    [
        (
            {
                "messages": [HumanMessage(content="当前在讨论济州岛美食。")],
                "branch_actions": [
                    build_branch_action_proposal(
                        kind=BranchActionKind.FORK_CHILD_BRANCH,
                        root_thread_id="root-1",
                        source_thread_id="thread-1",
                        target_parent_thread_id="thread-1",
                        suggested_branch_name="Pending",
                        reason="Existing pending action.",
                    ).model_dump(mode="json")
                ],
            },
            "pending_branch_action",
        ),
        (
            {
                "messages": [HumanMessage(content="当前分支已经关闭。")],
                "branch_meta": {
                    "branch_id": "branch-closed",
                    "root_thread_id": "root-1",
                    "parent_thread_id": "parent-1",
                    "return_thread_id": "parent-1",
                    "branch_name": "Closed",
                    "branch_status": "closed",
                },
            },
            "closed_branch",
        ),
    ],
)
def test_branch_recommendation_semantic_topic_shift_respects_existing_guards(
    values: dict,
    expected_reason: str,
) -> None:
    classifier = _FakeSemanticClassifier(
        result=lambda **kwargs: _semantic_topic_shift_result(
            recommended_action=(
                BranchDecisionAction.FORK_CHILD_BRANCH
                if getattr(kwargs.get("branch_meta"), "branch_depth", 0) == 5
                else BranchDecisionAction.FORK_SIBLING_BRANCH
                if kwargs.get("branch_meta") is not None
                else BranchDecisionAction.FORK_CHILD_BRANCH
            ),
        ),
    )
    service, graph, repository = _recommendation_service(values=values)
    _attach_semantic_classifier(service, classifier)

    service.recommend_for_message(
        thread_id="thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message="酒店取消政策有哪些注意事项？",
        request_id=f"req-semantic-guard-{expected_reason}",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    assert classifier.calls
    assert event.status == BranchDecisionStatus.BLOCKED
    assert event.metadata["reason"] == expected_reason
    if expected_reason == "pending_branch_action":
        actions = normalize_branch_actions(graph.values.get("branch_actions"))
        assert len(actions) == 1
        assert actions[0].suggested_branch_name == "Pending"
    else:
        assert "branch_actions" not in graph.values


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


def test_branch_handoff_auto_run_records_non_promotable_continue_event() -> None:
    service, graph, repository = _recommendation_service(mode="suggest")

    event = service.record_branch_handoff_auto_run_decision(
        thread_id="target-thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message="  Carry this context\ninto the new branch.  ",
        handoff_run_id="run-1",
        handoff_run_status="started",
        request_id="req-handoff-1",
    )

    stored = repository.list_branch_decision_events(source_thread_id="target-thread-1")[0]
    signal = next(item for item in stored.signals if item.name == "branch_handoff_context")
    assert event.decision_id == stored.decision_id
    assert stored.source_thread_id == "target-thread-1"
    assert stored.action == BranchDecisionAction.CONTINUE_CURRENT
    assert stored.status == BranchDecisionStatus.SKIPPED
    assert stored.mode.value == "suggest"
    assert stored.can_promote is False
    assert stored.idempotency_key == "branch_handoff:target-thread-1:c37ce35aaf541163"
    assert stored.recommendation_target == "continue_current"
    assert stored.metadata["source"] == "branch_handoff"
    assert stored.metadata["branch_handoff_auto_run"] is True
    assert stored.metadata["handoff_run_id"] == "run-1"
    assert stored.metadata["handoff_run_status"] == "started"
    assert stored.metadata["handoff_message_preview"] == "Carry this context into the new branch."
    assert signal.value["handoff_run_id"] == "run-1"
    assert signal.value["handoff_run_status"] == "started"
    assert "branch_actions" not in graph.values


def test_branch_handoff_auto_run_record_is_idempotent_for_normalized_message() -> None:
    service, _graph, repository = _recommendation_service(mode="suggest")

    first = service.record_branch_handoff_auto_run_decision(
        thread_id="target-thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message="Carry this context into the new branch.",
        handoff_run_id="run-1",
        handoff_run_status="started",
    )
    second = service.record_branch_handoff_auto_run_decision(
        thread_id="target-thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message="  Carry this context\ninto the new branch.  ",
        handoff_run_id="run-2",
        handoff_run_status="retry",
    )

    events = repository.list_branch_decision_events(source_thread_id="target-thread-1")
    assert second.decision_id == first.decision_id
    assert len(events) == 1
    assert events[0].metadata["handoff_run_id"] == "run-1"
    assert events[0].metadata["handoff_run_status"] == "started"


def test_branch_handoff_auto_run_outcome_update_records_status() -> None:
    service, _graph, repository = _recommendation_service(mode="suggest")
    event = service.record_branch_handoff_auto_run_decision(
        thread_id="target-thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message="Initial handoff context.",
        handoff_run_id="run-1",
        handoff_run_status="started",
    )

    updated = service.update_branch_handoff_auto_run_outcome(
        decision_id=event.decision_id,
        handoff_run_id="run-1",
        handoff_run_status="completed",
        message="Final handoff answer.",
    )

    stored = repository.get_branch_decision_event(event.decision_id)
    assert stored is not None
    assert updated.decision_id == event.decision_id
    assert stored.status == BranchDecisionStatus.SKIPPED
    assert stored.action == BranchDecisionAction.CONTINUE_CURRENT
    assert stored.metadata["source"] == "branch_handoff"
    assert stored.metadata["handoff_run_id"] == "run-1"
    assert stored.metadata["handoff_run_status"] == "completed"
    assert stored.metadata["handoff_message_preview"] == "Final handoff answer."
    assert stored.executed_at is not None


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


def test_branch_recommendation_topic_drift_without_branch_words_forks_sibling_from_child() -> None:
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
        message="先看另一个问题：不相关领域的预算口径怎么定？",
        request_id="req-topic-drift-child",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    actions = normalize_branch_actions(graph.values.get("branch_actions"))
    topic_drift_signal = next(
        signal for signal in event.signals if signal.name == "recommendation_topic_drift"
    )
    assert event.action == BranchDecisionAction.FORK_SIBLING_BRANCH
    assert event.status == BranchDecisionStatus.PROMOTED
    assert event.recommendation_target == "fork_sibling_branch"
    assert topic_drift_signal.value["has_topic_drift"] is True
    assert topic_drift_signal.value["recommendation_target"] == "fork_sibling_branch"
    assert actions[0].kind == BranchActionKind.FORK_SIBLING_BRANCH
    assert actions[0].target_parent_thread_id == "parent-1"


def test_branch_recommendation_continues_when_user_says_in_this_branch() -> None:
    service, graph, repository = _recommendation_service(
        values={
            "messages": [HumanMessage(content="当前分支已经在研究济州岛旅行。")],
            "branch_meta": {
                "branch_id": "branch-1",
                "root_thread_id": "root-1",
                "parent_thread_id": "parent-1",
                "return_thread_id": "parent-1",
                "branch_name": "济州岛旅行",
            },
        }
    )

    payload = service.recommend_for_message(
        thread_id="thread-1",
        user_id="u-1",
        message="在这个分支里研究亲子旅行和雨天备选，给出可合并回主线的明确结论。",
        request_id="req-current-branch",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    assert payload is not None
    assert payload["action"] == "continue_current"
    assert event.action == BranchDecisionAction.CONTINUE_CURRENT
    assert event.status == BranchDecisionStatus.SKIPPED
    assert event.metadata["reason"] == "continue_current"
    assert "branch_actions" not in graph.values


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
    assert event.metadata["reason"] == "continue_current"
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
    assert event.metadata["reason"] == "pending_branch_action"
    assert [action.action_id for action in actions] == [pending.action_id]


def test_branch_recommendation_replaces_stale_pending_sibling_action() -> None:
    pending = build_branch_action_proposal(
        kind=BranchActionKind.FORK_SIBLING_BRANCH,
        root_thread_id="root-1",
        source_thread_id="thread-1",
        target_parent_thread_id="root-1",
        suggested_branch_name="Thailand",
        reason="Existing pending action.",
        handoff_message="我想去泰国旅游，你帮我做一个方案",
    )
    service, graph, repository = _recommendation_service(
        values={
            "messages": [
                HumanMessage(content="这个韩国旅游攻略：请补充一个5天预算表。"),
            ],
            "branch_meta": {
                "branch_id": "branch-1",
                "root_thread_id": "root-1",
                "parent_thread_id": "root-1",
                "return_thread_id": "root-1",
                "branch_name": "Korea Travel",
                "branch_depth": 1,
            },
            "branch_actions": [pending.model_dump(mode="json")],
        }
    )
    _attach_semantic_classifier(
        service,
        _FakeSemanticClassifier(
            result=_semantic_topic_shift_result(
                confidence=0.93,
                recommended_action=BranchDecisionAction.FORK_SIBLING_BRANCH,
            ),
        ),
    )

    service.recommend_for_message(
        thread_id="thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message="今天A股大盘的表现如何？",
        request_id="req-rec-replace-pending",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    actions = normalize_branch_actions(graph.values.get("branch_actions"))
    assert event.status == BranchDecisionStatus.PROMOTED
    assert event.promoted_action_id
    assert [action.status for action in actions] == [
        BranchActionStatus.DISMISSED,
        BranchActionStatus.PENDING,
    ]
    assert actions[0].action_id == pending.action_id
    assert actions[1].handoff_message == "今天A股大盘的表现如何？"
    assert event.metadata["replaced_pending_branch_action_id"] == pending.action_id


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
    assert event.metadata["reason"] == "child_depth_exceeded"
    assert "branch_actions" not in graph.values


def test_branch_recommendation_shadow_records_without_pending_action() -> None:
    service, graph, repository = _recommendation_service(mode="shadow")

    service.recommend_for_message(
        thread_id="thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message="换个主题，先看另一个问题：酒店取消政策怎么处理？",
        request_id="req-shadow",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    assert event.action == BranchDecisionAction.FORK_CHILD_BRANCH
    assert event.status == BranchDecisionStatus.SHADOWED
    assert event.metadata["reason"] == "shadow_mode"
    assert event.metadata["recommendation_user_visible"] is False
    assert "branch_actions" not in graph.values


def test_branch_recommendation_blocks_when_branch_is_closed() -> None:
    service, graph, repository = _recommendation_service(
        values={
            "messages": [HumanMessage(content="当前分支已经关闭。")],
            "branch_meta": {
                "branch_id": "branch-closed",
                "root_thread_id": "root-1",
                "parent_thread_id": "parent-1",
                "return_thread_id": "parent-1",
                "branch_name": "Closed",
                "branch_status": "closed",
            },
        }
    )

    service.recommend_for_message(
        thread_id="thread-1",
        user_id="u-1",
        message="先看另一个问题：不相关领域的预算口径怎么定？",
        request_id="req-closed",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    assert event.status == BranchDecisionStatus.BLOCKED
    assert event.metadata["reason"] == "closed_branch"
    assert "branch_actions" not in graph.values


def test_branch_recommendation_skips_when_below_threshold() -> None:
    service, graph, repository = _recommendation_service(
        values={"messages": [HumanMessage(content="继续分析主线。")]},
        recommendation_min_confidence=0.99,
    )

    service.recommend_for_message(
        thread_id="thread-1",
        root_thread_id="root-1",
        user_id="u-1",
        message="请新开一个子分支深入研究方案 B。",
        request_id="req-threshold",
    )

    event = repository.list_branch_decision_events(source_thread_id="thread-1")[0]
    assert event.action == BranchDecisionAction.FORK_CHILD_BRANCH
    assert event.status == BranchDecisionStatus.SKIPPED
    assert event.metadata["reason"] == "below_threshold"
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
    assert values["agent_branch_recommendation_semantic_enabled"] is True


def test_branch_recommendation_config_exposes_semantic_settings() -> None:
    service, _graph, _repository = _recommendation_service()
    service.settings.agent_branch_recommendation_semantic_enabled = True
    service.settings.agent_branch_recommendation_semantic_model = "moonshot:kimi-k2"

    config = service.config()

    assert config.recommendation_semantic_enabled is True
    assert config.recommendation_semantic_model == "moonshot:kimi-k2"
    assert config.recommendation_diagnostics["semantic_enabled"] is True
    assert config.recommendation_diagnostics["semantic_model"] == "moonshot:kimi-k2"
