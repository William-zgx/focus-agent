from types import SimpleNamespace

import pytest

from focus_agent.engine.graph import policy


@pytest.mark.parametrize(
    "prompt",
    [
        "Use artifact_read(artifact_id='tool-observation://read_file/call-1', offset=20000, limit=300) to retrieve a page.",
        "Read the evidence.txt file in this workspace.",
        "找到仓库里 assemble_context 函数的定义位置。",
    ],
)
def test_workspace_lookup_exposes_observation_read_without_artifact_writes(prompt):
    tools = [
        SimpleNamespace(name=name, metadata={})
        for name in (
            "search_code",
            "read_file",
            "artifact_read",
            "artifact_list",
            "artifact_search",
            "write_text_artifact",
            "artifact_update",
            "apply_patch",
            "web_search",
        )
    ]
    plan = policy.build_tool_intent_plan(prompt)
    assert plan.policy == "workspace_lookup"
    selected = policy._tools_for_policy(
        plan.policy,
        tools,
        prompt,
        exposure=policy._turn_tool_exposure_from_intent_plan(plan),
    )

    names = {tool.name for tool in selected}
    assert "artifact_read" in names
    assert names <= {"search_code", "read_file", "artifact_read"}


def test_workspace_lookup_does_not_exempt_artifact_read_with_side_effects():
    tool = SimpleNamespace(name="artifact_read", metadata={"side_effect": True})
    plan = policy.build_tool_intent_plan("Read the evidence.txt file in this workspace.")

    assert (
        policy._tools_for_policy(
            plan.policy,
            [tool],
            plan.normalized_text,
            exposure=policy._turn_tool_exposure_from_intent_plan(plan),
        )
        == []
    )
