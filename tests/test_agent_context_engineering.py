from langchain.messages import ToolMessage

from focus_agent.agent_context_engineering import (
    build_context_engineering_decision,
    build_context_policy,
)
from focus_agent.config import Settings
from focus_agent.core.types import ContextBudget


def test_context_engineering_policy_defaults_are_legacy_safe():
    policy = build_context_policy(Settings())

    assert policy["enabled"] is False
    assert policy["artifactize_long_observations"] is False
    assert policy["tokenizer_mode"] == "chars_fallback"
    assert policy["default_off_legacy_safe"] is True


def test_context_engineering_artifactizes_long_tool_observation(tmp_path):
    settings = Settings(
        agent_context_engineering_v2_enabled=True,
        agent_context_artifactize_long_observations=True,
        agent_context_role_views_enabled=True,
        agent_context_artifact_min_chars=100,
        artifact_dir=str(tmp_path),
    )
    long_observation = "tool result " * 80

    decision = build_context_engineering_decision(
        settings=settings,
        state={
            "messages": [ToolMessage(content=long_observation, tool_call_id="tool-1")],
            "context_budget": ContextBudget(prompt_token_limit=120, chars_per_token=1),
            "rolling_summary": "summary " * 700,
        },
        prompt_mode="execute",
        assembled_context="assembled context " * 40,
        role="critic",
        artifact_dir=tmp_path,
    )

    assert decision.enabled is True
    assert decision.budget.prompt_chars > 0
    assert decision.compression_plan.enabled is True
    assert decision.artifact_refs
    assert decision.artifact_refs[0].materialized is True
    assert (tmp_path / decision.artifact_refs[0].artifact_id).exists()
    assert any(view.role == "critic" for view in decision.role_context_views)


def test_context_engineering_compresses_over_budget_prompt():
    settings = Settings(agent_context_engineering_v2_enabled=True)

    decision = build_context_engineering_decision(
        settings=settings,
        state={"context_budget": {"prompt_token_limit": 80, "chars_per_token": 1}},
        prompt_mode="explore",
        assembled_context="A" * 500,
    )

    assert decision.budget.over_budget_chars == 420
    assert decision.compressed_prompt is not None
    assert "Context Engineering v2" in decision.compressed_prompt
