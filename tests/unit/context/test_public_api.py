from __future__ import annotations


def test_context_package_and_leaf_exports_are_explicit():
    from focus_agent.core import context as context_package
    from focus_agent.core.context import budget, policy, tool_observations

    public_names = {
        "ContextSlice",
        "apply_prompt_budget_guard",
        "approximate_token_count",
        "assemble_context",
        "trim_tool_observation",
    }
    assert set(context_package.__all__) == public_names
    for module in (context_package, budget, policy, tool_observations):
        assert all(not name.startswith("_") for name in module.__all__)

    assert context_package.ContextSlice is policy.ContextSlice
    assert context_package.assemble_context is policy.assemble_context
    assert context_package.apply_prompt_budget_guard is budget.apply_prompt_budget_guard
    assert context_package.approximate_token_count is budget.approximate_token_count
    assert context_package.trim_tool_observation is tool_observations.trim_tool_observation
