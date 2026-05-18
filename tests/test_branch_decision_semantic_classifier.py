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
