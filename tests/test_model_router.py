from __future__ import annotations

from focus_agent.config import Settings
from focus_agent.runtime.model_router import ModelChoice, ModelRouter, TaskKind


def test_model_router_from_settings_uses_role_specific_models_and_fallbacks():
    router = ModelRouter.from_settings(
        Settings(
            model="openai:gpt-4.1-mini",
            helper_model="openai:gpt-4.1",
            model_choices=("moonshot:kimi-k2.6",),
            agent_role_critic_model="openai:deepseek-chat",
            multi_agent_role_fallback_models={"critic": "ollama:qwen2.5:7b"},
        )
    )

    decision = router.decide(kind=TaskKind.CRITIC)

    assert decision.selected_model == "openai:deepseek-chat"
    assert decision.primary_model == "openai:deepseek-chat"
    assert decision.fallback_models == ("ollama:qwen2.5:7b", "moonshot:kimi-k2.6")


def test_model_router_canary_selection_is_deterministic():
    router = ModelRouter(
        None,
        {
            TaskKind.EXECUTION: ModelChoice(
                primary="openai:gpt-4.1-mini",
                canary_model="openai:gpt-4.1",
                canary_user_ratio=1.0,
            )
        },
    )

    decision = router.decide(kind="execution", user_id="user-1")

    assert decision.selected_model == "openai:gpt-4.1"
    assert decision.canary is True


def test_model_router_uses_first_available_fallback_when_primary_is_unavailable():
    router = ModelRouter(
        None,
        {
            TaskKind.PLANNING: ModelChoice(
                primary="openai:gpt-4.1",
                fallbacks=("moonshot:kimi-k2.6", "openai:gpt-4.1-mini"),
                max_tokens_per_min=120_000,
                cost_budget_usd_per_day=12.5,
            )
        },
    )

    decision = router.decide(
        kind=TaskKind.PLANNING,
        unavailable_models={"openai:gpt-4.1", "moonshot:kimi-k2.6"},
    )

    assert decision.selected_model == "openai:gpt-4.1-mini"
    assert decision.fallback_used is True
    assert decision.max_tokens_per_min == 120_000
    assert decision.cost_budget_usd_per_day == 12.5
