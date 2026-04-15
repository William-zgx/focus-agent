from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.core.context_policy import assemble_context
from focus_agent.core.types import ArtifactRef, ContextBudget, FindingItem, PromptMode


def test_assemble_context_changes_output_by_mode():
    state = {
        "messages": [HumanMessage(content="Need a recommendation"), AIMessage(content="Working on it")],
        "rolling_summary": "We are comparing rollout options.",
        "memory_prompt_block": "## Retrieved long-term memories\n- 历史结论 A",
        "branch_meta": {
            "branch_id": "branch-1",
            "branch_name": "deep-dive",
            "branch_role": "deep_dive",
        },
        "branch_local_findings": [
            FindingItem(finding="Option A has the lowest migration cost", evidence_refs=["calc-1"])
        ],
        "artifacts": [
            ArtifactRef(title="Migration notes", kind="markdown", uri="file:///tmp/notes.md")
        ],
    }

    explore = assemble_context(state, PromptMode.EXPLORE)
    execute = assemble_context(state, PromptMode.EXECUTE)
    synthesize = assemble_context(state, PromptMode.SYNTHESIZE)
    review = assemble_context(state, PromptMode.BRANCH_REVIEW)

    assert "- explore" in explore.system_instructions
    assert "- execute" in execute.system_instructions
    assert "- synthesize" in synthesize.system_instructions
    assert "- branch_review" in review.system_instructions
    assert "历史结论 A" in explore.render_prompt()
    assert "Option A has the lowest migration cost" in explore.findings_block
    assert "Option A has the lowest migration cost" in review.findings_block
    assert "Option A has the lowest migration cost" not in synthesize.findings_block
    assert "Migration notes" in execute.artifact_block
    assert "Migration notes" not in synthesize.artifact_block


def test_branch_context_does_not_auto_include_non_imported_parent_findings():
    state = {
        "messages": [HumanMessage(content="Keep exploring the branch")],
        "branch_meta": {
            "branch_id": "branch-2",
            "branch_name": "verification",
            "branch_role": "verify",
        },
        "branch_local_findings": [FindingItem(finding="Local verification is incomplete")],
        "main_thread_findings": ["Parent-only finding that should not leak"],
    }

    slice_ = assemble_context(state, PromptMode.EXPLORE)

    assert "Local verification is incomplete" in slice_.findings_block
    assert "Parent-only finding that should not leak" not in slice_.render_prompt()


def test_assemble_context_applies_budget_limits():
    state = {
        "messages": [
            HumanMessage(content="m1"),
            AIMessage(content="m2"),
            HumanMessage(content="m3"),
            AIMessage(content="m4"),
        ],
        "branch_meta": {
            "branch_id": "branch-3",
            "branch_name": "budget-check",
            "branch_role": "explore_alternatives",
        },
        "branch_local_findings": [
            FindingItem(finding="Finding one"),
            FindingItem(finding="Finding two"),
        ],
        "artifacts": [
            ArtifactRef(title="Artifact one", kind="note"),
            ArtifactRef(title="Artifact two", kind="note"),
        ],
        "context_budget": ContextBudget(
            recent_message_limit=2,
            findings_limit=1,
            artifact_limit=1,
        ),
    }

    slice_ = assemble_context(state, PromptMode.BRANCH_REVIEW)

    assert [message.content for message in slice_.recent_messages] == ["m3", "m4"]
    assert "Finding two" in slice_.findings_block
    assert "Finding one" not in slice_.findings_block
    assert "Artifact two" in slice_.artifact_block
    assert "Artifact one" not in slice_.artifact_block


def test_assemble_context_skips_historical_tool_messages():
    state = {
        "messages": [
            HumanMessage(content="北京天气"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "tool-call-1",
                        "name": "web_search",
                        "args": {"query": "beijing weather"},
                    }
                ],
            ),
            ToolMessage(content='{"forecast":"sunny"}', tool_call_id="tool-call-1"),
            AIMessage(content="今天北京晴。"),
            HumanMessage(content="那明天呢"),
        ],
        "context_budget": ContextBudget(recent_message_limit=5),
    }

    slice_ = assemble_context(state, PromptMode.EXPLORE)

    assert [message.content for message in slice_.recent_messages] == [
        "北京天气",
        "今天北京晴。",
        "那明天呢",
    ]


def test_branch_scope_mentions_upstream_review_behavior():
    context_slice = assemble_context(
        {
            "branch_meta": {
                "branch_id": "branch-review",
                "branch_name": "verify",
                "branch_role": "verify",
            }
        },
        PromptMode.BRANCH_REVIEW,
    )

    assert "branch_role: verify" in context_slice.system_instructions
    assert "may later be reviewed for upstream import" in context_slice.system_instructions
    assert "conclusion_policy" not in context_slice.system_instructions


def test_assemble_context_renders_skill_blocks():
    context_slice = assemble_context(
        {
            "_active_skills_block": "## Active skills\n- plan",
            "_available_skills_block": "## Available skills\n- plan: Planning mode",
        },
        PromptMode.EXPLORE,
    )

    rendered = context_slice.render_prompt()

    assert "## Active skills" in rendered
    assert "## Available skills" in rendered
    assert "## Skill system" in context_slice.system_instructions
