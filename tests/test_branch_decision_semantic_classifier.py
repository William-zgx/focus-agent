from __future__ import annotations

from langchain.messages import AIMessage, HumanMessage

from focus_agent.branch_decision.classifier import (
    SemanticTopicRelationClassifier,
    classify_topic_relation,
)
from focus_agent.config import Settings
from focus_agent.config_parts.agent import load_agent_config


class FakeModel:
    def __init__(self, content: str | Exception) -> None:
        self.content = content
        self.invocations: list[object] = []

    def invoke(self, messages):
        self.invocations.append(messages)
        if isinstance(self.content, Exception):
            raise self.content
        return AIMessage(content=self.content)


def _settings(**overrides) -> Settings:
    return Settings(
        auth_enabled=False,
        agent_branch_recommendation_enabled=True,
        agent_branch_recommendation_semantic_enabled=True,
        **overrides,
    )


def test_semantic_classifier_parses_structured_result() -> None:
    fake_model = FakeModel(
        """
        {
          "relatedness": 0.18,
          "topic_shift": true,
          "relationship": "unrelated_new_topic",
          "recommended_action": "fork_sibling_branch",
          "confidence": 0.86,
          "reason": "The incoming message starts a separate topic."
        }
        """
    )
    seen_model_ids: list[str] = []

    result = classify_topic_relation(
        settings=_settings(model="openai:gpt-4.1-mini"),
        message="换个问题，看一下酒店取消政策。",
        branch_history=[HumanMessage(content="当前分支在讨论计费 API 重构。")],
        selected_model="openai:gpt-5-mini",
        on_branch=True,
        model_factory=lambda model_id: seen_model_ids.append(model_id) or fake_model,
    )

    assert seen_model_ids == ["openai:gpt-5-mini"]
    assert result.relatedness == 0.18
    assert result.topic_shift is True
    assert result.recommended_action == "fork_sibling_branch"
    assert result.confidence == 0.86
    assert result.model == "openai:gpt-5-mini"
    assert result.status == "ok"
    prompt_text = fake_model.invocations[0][1].content
    assert "Do not answer the user request" in prompt_text


def test_semantic_classifier_model_override_wins_over_selected_model() -> None:
    fake_model = FakeModel(
        """
        {
          "relatedness": 0.91,
          "topic_shift": false,
          "relationship": "same_topic_followup",
          "recommended_action": "continue_current",
          "confidence": 0.81,
          "reason": "The user asks a follow-up."
        }
        """
    )
    seen_model_ids: list[str] = []
    classifier = SemanticTopicRelationClassifier(
        settings=_settings(agent_branch_recommendation_semantic_model="moonshot:kimi-k2"),
        model_factory=lambda model_id: seen_model_ids.append(model_id) or fake_model,
    )

    result = classifier.classify(
        message="继续看刚才的接口错误。",
        branch_history="user: 修复计费 API\nassistant: 已定位接口错误",
        selected_model="openai:gpt-5-mini",
    )

    assert seen_model_ids == ["moonshot:kimi-k2"]
    assert result.recommended_action == "continue_current"
    assert result.model == "moonshot:kimi-k2"
    assert result.status == "ok"


def test_semantic_classifier_uses_selected_model_from_values() -> None:
    fake_model = FakeModel(
        """
        {
          "relatedness": 0.3,
          "topic_shift": true,
          "relationship": "parallel_topic",
          "recommended_action": "fork_child_branch",
          "confidence": 0.88,
          "reason": "The user opened a different planning topic."
        }
        """
    )
    seen_model_ids: list[str] = []

    result = classify_topic_relation(
        settings=_settings(model="openai:gpt-4.1-mini"),
        message="再看一个完全不同的预算问题。",
        values={
            "selected_model": "openai:gpt-5-mini",
            "messages": [HumanMessage(content="当前在讨论济州岛行程。")],
        },
        model_factory=lambda model_id: seen_model_ids.append(model_id) or fake_model,
    )

    assert seen_model_ids == ["openai:gpt-5-mini"]
    assert result.recommended_action == "fork_child_branch"
    assert result.status == "ok"


def test_semantic_classifier_accepts_labeled_relatedness() -> None:
    fake_model = FakeModel(
        """
        {
          "relatedness": "unrelated",
          "topic_shift": true,
          "relationship": "unrelated_new_topic",
          "recommended_action": "fork_sibling_branch",
          "confidence": 0.9,
          "reason": "The incoming message changes destination and task."
        }
        """
    )

    result = classify_topic_relation(
        settings=_settings(model="openai:gpt-5-mini"),
        message="大阪环球影城十月亲子预算怎么安排？",
        branch_history=[HumanMessage(content="当前分支在讨论济州岛东门市场夜宵路线。")],
        on_branch=True,
        model_factory=lambda _model_id: fake_model,
    )

    assert result.relatedness == 0.0
    assert result.topic_shift is True
    assert result.recommended_action == "fork_sibling_branch"
    assert result.status == "ok"


def test_semantic_classifier_accepts_labeled_topic_shift() -> None:
    fake_model = FakeModel(
        """
        {
          "relatedness": "unrelated",
          "topic_shift": "major",
          "relationship": "unrelated_new_topic",
          "recommended_action": "fork_sibling_branch",
          "confidence": 0.87,
          "reason": "The user moved from travel planning to market analysis."
        }
        """
    )

    result = classify_topic_relation(
        settings=_settings(model="moonshot:kimi-k2.6"),
        message="软通动力今天盘面怎么看？",
        branch_history=[HumanMessage(content="当前分支在讨论韩国济州岛旅行。")],
        on_branch=True,
        model_factory=lambda _model_id: fake_model,
    )

    assert result.topic_shift is True
    assert result.recommended_action == "fork_sibling_branch"
    assert result.status == "ok"


def test_semantic_classifier_fails_closed_on_non_json() -> None:
    result = classify_topic_relation(
        settings=_settings(),
        message="换个主题聊部署。",
        branch_history="user: 当前讨论前端测试",
        model_factory=lambda _model_id: FakeModel("this is not json"),
    )

    assert result.relatedness == 1.0
    assert result.topic_shift is False
    assert result.recommended_action == "continue_current"
    assert result.confidence == 0.0
    assert result.status == "semantic_classifier_failed"
    assert result.reason.startswith("Semantic classifier returned invalid output")


def test_semantic_classifier_fails_closed_on_model_error() -> None:
    result = classify_topic_relation(
        settings=_settings(),
        message="换个主题聊部署。",
        branch_history="user: 当前讨论前端测试",
        model_factory=lambda _model_id: FakeModel(RuntimeError("provider unavailable")),
    )

    assert result.recommended_action == "continue_current"
    assert result.status == "error"
    assert "provider unavailable" in result.reason


def test_semantic_recommendation_config_follows_recommendation_enabled() -> None:
    enabled_values = load_agent_config(
        {"AGENT_BRANCH_RECOMMENDATION_ENABLED": "true"},
        Settings(),
    )
    disabled_values = load_agent_config(
        {"AGENT_BRANCH_RECOMMENDATION_ENABLED": "false"},
        Settings(),
    )
    override_values = load_agent_config(
        {
            "AGENT_BRANCH_RECOMMENDATION_ENABLED": "true",
            "AGENT_BRANCH_RECOMMENDATION_SEMANTIC_ENABLED": "false",
            "AGENT_BRANCH_RECOMMENDATION_SEMANTIC_MODEL": "moonshot:kimi-k2",
        },
        Settings(),
    )

    assert enabled_values["agent_branch_recommendation_semantic_enabled"] is True
    assert disabled_values["agent_branch_recommendation_semantic_enabled"] is False
    assert override_values["agent_branch_recommendation_semantic_enabled"] is False
    assert override_values["agent_branch_recommendation_semantic_model"] == "moonshot:kimi-k2"


def _decision_settings(**overrides):
    from focus_agent.config import ConfiguredModel, ModelCatalogConfig, ProviderConfig

    return _settings(
        model_catalog=ModelCatalogConfig(
            providers=(ProviderConfig(id="decider", base_url_default="https://example.test/v1"),),
            models=(ConfiguredModel(id="decider:route-v2", protocol="system_one"),),
        ),
        **overrides,
    )


def _decision_response(choice="fork_child_branch", confidence=0.95):
    from focus_agent.decision_models import DecisionModelAnswer, DecisionModelResult

    return DecisionModelResult(
        model="route-v2",
        answers={
            "action": DecisionModelAnswer(
                question_id="action",
                type="choice",
                choice=choice,
                confidence=confidence,
                probabilities={
                    "continue_current": 0.01,
                    "fork_child_branch": 0.98,
                    "fork_sibling_branch": 0.01,
                },
            )
        },
    )


def test_system_one_routing_preserves_raw_diagnostics(monkeypatch):
    import focus_agent.decision_models as decisions

    calls = []
    monkeypatch.setattr(
        decisions, "evaluate_decision_model", lambda **kw: calls.append(kw) or _decision_response()
    )
    result = classify_topic_relation(
        settings=_decision_settings(agent_branch_recommendation_semantic_model="decider:route-v2"),
        message="研究新的部署选项",
        branch_history="当前在讨论部署。",
        model_factory=lambda _: (_ for _ in ()).throw(AssertionError("chat invoked")),
    )
    assert calls[0]["state"]["incoming_message"] == "研究新的部署选项"
    assert result.relatedness is None
    assert result.recommended_action == "fork_child_branch"
    assert result.decision_min_confidence == 0.9
    assert result.diagnostics["response_model"] == "route-v2"
    assert result.diagnostics["probabilities"]["fork_child_branch"] == 0.98
    assert result.diagnostics["fallback_used"] is False


def test_failed_system_one_uses_chat_fallback_once(monkeypatch):
    import focus_agent.decision_models as decisions
    from focus_agent.decision_models import DecisionModelHTTPError

    monkeypatch.setattr(
        decisions,
        "evaluate_decision_model",
        lambda **kw: (_ for _ in ()).throw(DecisionModelHTTPError(429)),
    )
    models = []
    result = classify_topic_relation(
        settings=_decision_settings(
            agent_branch_recommendation_semantic_model="decider:route-v2",
            agent_branch_recommendation_semantic_fallback_model="openai:backup",
        ),
        message="继续分析",
        branch_history="当前讨论部署。",
        model_factory=lambda model: (
            models.append(model) or FakeModel('{"recommended_action":"continue_current"}')
        ),
    )
    assert models == ["openai:backup"]
    assert result.status == "ok"
    assert result.model == "openai:backup"
    assert result.decision_min_confidence is None
    assert result.diagnostics["fallback_used"] is True
    assert [a["status"] for a in result.diagnostics["attempts"]] == ["error", "ok"]


def test_invalid_chat_uses_system_one_fallback(monkeypatch):
    import focus_agent.decision_models as decisions

    monkeypatch.setattr(decisions, "evaluate_decision_model", lambda **kw: _decision_response())
    result = classify_topic_relation(
        settings=_decision_settings(
            agent_branch_recommendation_semantic_model="openai:primary",
            agent_branch_recommendation_semantic_fallback_model="decider:route-v2",
        ),
        message="研究部署",
        branch_history="当前讨论测试。",
        model_factory=lambda _: FakeModel("invalid JSON"),
    )
    assert result.model == "decider:route-v2"
    assert result.status == "ok"
    assert result.diagnostics["attempts"][0]["status"] == "semantic_classifier_failed"


def test_low_confidence_or_continue_does_not_use_fallback(monkeypatch):
    import focus_agent.decision_models as decisions

    for choice, confidence in [("continue_current", 0.99), ("fork_child_branch", 0.2)]:
        monkeypatch.setattr(
            decisions,
            "evaluate_decision_model",
            lambda choice=choice, confidence=confidence, **kw: _decision_response(
                choice, confidence
            ),
        )
        result = classify_topic_relation(
            settings=_decision_settings(
                agent_branch_recommendation_semantic_model="decider:route-v2",
                agent_branch_recommendation_semantic_fallback_model="openai:backup",
            ),
            message="免费托管怎么样？",
            branch_history="正在研究部署。",
            model_factory=lambda _: (_ for _ in ()).throw(AssertionError("fallback invoked")),
        )
        assert result.status == "ok"
        assert len(result.diagnostics["attempts"]) == 1


def test_attempts_share_deadline_and_discard_late_result(monkeypatch):
    import focus_agent.branch_decision.classifier as module
    import focus_agent.decision_models as decisions

    clock = [10.0]
    budgets = []
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])

    class SlowFailure:
        def invoke(self, messages):
            clock[0] += 3
            raise RuntimeError("private provider message")

    def decide(**kwargs):
        budgets.append(kwargs["timeout_seconds"])
        clock[0] += 3
        return _decision_response()

    monkeypatch.setattr(decisions, "evaluate_decision_model", decide)
    result = classify_topic_relation(
        settings=_decision_settings(
            agent_branch_recommendation_semantic_model="openai:primary",
            agent_branch_recommendation_semantic_fallback_model="decider:route-v2",
        ),
        message="研究部署",
        branch_history="当前讨论测试。",
        deadline=15.0,
        model_factory=lambda _: SlowFailure(),
    )
    assert budgets == [2.0]
    assert result.recommended_action == "continue_current"
    assert result.status == "semantic_classifier_failed"
    assert "deadline exceeded" in result.reason


def test_no_budget_does_not_invoke_provider():
    result = classify_topic_relation(
        settings=_settings(agent_branch_recommendation_semantic_fallback_model="openai:backup"),
        message="研究部署",
        branch_history="当前讨论测试。",
        deadline=0,
        model_factory=lambda _: (_ for _ in ()).throw(AssertionError("provider invoked")),
    )
    assert result.diagnostics["attempts"] == []
    assert result.recommended_action == "continue_current"


def test_decision_configuration_environment():
    config = load_agent_config(
        {
            "AGENT_BRANCH_RECOMMENDATION_SEMANTIC_FALLBACK_MODEL": "acme:route",
            "AGENT_BRANCH_RECOMMENDATION_SEMANTIC_DECISION_MIN_CONFIDENCE": "0.94",
            "AGENT_BRANCH_RECOMMENDATION_TIMEOUT_SECONDS": "8",
        },
        Settings(),
    )
    assert config["agent_branch_recommendation_semantic_fallback_model"] == "acme:route"
    assert config["agent_branch_recommendation_semantic_decision_min_confidence"] == 0.94
    assert config["agent_branch_recommendation_timeout_seconds"] == 8


def test_disabled_result_does_not_fork_or_fallback():
    models = []
    result = classify_topic_relation(
        settings=_settings(agent_branch_recommendation_semantic_fallback_model="openai:backup"),
        message="研究部署",
        branch_history="当前讨论测试。",
        model_factory=lambda model: (
            models.append(model)
            or FakeModel(
                '{"status":"disabled","topic_shift":true,"recommended_action":"fork_child_branch","confidence":0.99}'
            )
        ),
    )
    assert len(models) == 1
    assert result.status == "disabled"
    assert result.recommended_action == "continue_current"
    assert result.diagnostics["fallback_used"] is False


def test_invalid_primary_model_id_can_use_fallback():
    models = []
    result = classify_topic_relation(
        settings=_settings(
            agent_branch_recommendation_semantic_model="openai:",
            agent_branch_recommendation_semantic_fallback_model="openai:backup",
        ),
        message="研究部署",
        branch_history="当前讨论测试。",
        model_factory=lambda model: (
            models.append(model) or FakeModel('{"recommended_action":"continue_current"}')
        ),
    )
    assert models == ["openai:backup"]
    assert result.status == "ok"
    assert result.diagnostics["fallback_used"] is True
