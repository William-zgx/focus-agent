import json

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import focus_agent.core.context_policy as context_policy_module

from focus_agent.core.context_policy import (
    apply_prompt_budget_guard,
    approximate_token_count,
    assemble_context,
    trim_tool_observation,
)
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


def test_prompt_budget_guard_preserves_current_user_and_active_constraints():
    system_text = "\n\n".join(
        [
            "You are Focus Agent.",
            "## Retrieved long-term memories\n" + ("low priority memory " * 100),
            "## Constraints and goals\n- Active goal: draft the final answer\n- Preserve this exact constraint.",
            "## Rolling summary\n" + ("old summary " * 100),
        ]
    )
    current_turn = "Current user turn must stay exact."
    budget = ContextBudget(prompt_token_limit=150, chars_per_token=1)

    guarded = apply_prompt_budget_guard(
        [
            SystemMessage(content=system_text),
            HumanMessage(content="older history can be removed"),
            HumanMessage(content=current_turn),
        ],
        budget=budget,
    )

    rendered = "\n".join(str(message.content) for message in guarded)
    assert sum(len(str(message.content)) for message in guarded) <= 150
    assert current_turn in [message.content for message in guarded if isinstance(message, HumanMessage)]
    assert "Preserve this exact constraint." in rendered
    assert "low priority memory" not in rendered
    assert "older history can be removed" not in rendered


def test_prompt_budget_guard_prioritizes_imported_findings_over_summary_and_available_skills():
    state = {
        "messages": [HumanMessage(content="请继续基于已确认结论给出下一步建议。")],
        "rolling_summary": "old summary " * 80,
        "imported_findings": [
            FindingItem(finding="Approved finding: switch to the postgres migration path", evidence_refs=["pr-12"])
        ],
        "_available_skills_block": "## Available skills\n- low priority skill one\n- low priority skill two",
    }
    context_slice = assemble_context(state, PromptMode.SYNTHESIZE)
    budget = ContextBudget(prompt_token_limit=180, chars_per_token=1)

    guarded = apply_prompt_budget_guard(
        [
            SystemMessage(content=context_slice.render_prompt()),
            HumanMessage(content="请继续基于已确认结论给出下一步建议。"),
        ],
        budget=budget,
    )

    rendered = "\n".join(str(message.content) for message in guarded)

    assert "## Imported findings already approved into this thread" in rendered
    assert "Approved finding:" in rendered or "...[1 omitted]" in rendered
    assert "old summary old summary" not in rendered
    assert "low priority skill one" not in rendered


def test_prompt_budget_guard_truncates_bulleted_blocks_without_breaking_bullet_lines():
    budget = ContextBudget(prompt_token_limit=120, chars_per_token=1)
    system_text = "\n\n".join(
        [
            "You are Focus Agent.",
            "## Imported findings already approved into this thread\n"
            "- First approved finding with useful detail.\n"
            "- Second approved finding with more useful detail.\n"
            "- Third approved finding with extra useful detail.",
        ]
    )

    guarded = apply_prompt_budget_guard(
        [
            SystemMessage(content=system_text),
            HumanMessage(content="Use the approved findings."),
        ],
        budget=budget,
    )

    rendered = "\n".join(str(message.content) for message in guarded)

    assert "## Imported findings already approved into this thread" in rendered
    assert "...[" in rendered or "- Second approved finding" in rendered
    assert "...[trimmed]..." not in rendered


def test_prompt_budget_guard_hard_limits_oversized_current_turn():
    current_turn = "Current user turn " * 20
    budget = ContextBudget(prompt_token_limit=80, chars_per_token=1)

    guarded = apply_prompt_budget_guard(
        [
            SystemMessage(content="system " * 20),
            HumanMessage(content=current_turn),
        ],
        budget=budget,
    )

    rendered = "\n".join(str(message.content) for message in guarded)
    assert sum(len(str(message.content)) for message in guarded) <= 80
    assert "Current user" in rendered
    assert "[trimmed]" in rendered


def test_approximate_token_count_uses_deterministic_char_budget():
    assert approximate_token_count("abcd", chars_per_token=4) == 1
    assert approximate_token_count("abcde", chars_per_token=4) == 2


def test_approximate_token_count_prefers_tokenizer_when_available(monkeypatch):
    monkeypatch.setattr(
        context_policy_module,
        "_estimate_with_tokenizer",
        lambda text, tokenizer_id=None: 3 if tokenizer_id == "fake-model" and text else None,
    )

    assert approximate_token_count("abcdef", chars_per_token=10, tokenizer_id="fake-model") == 3


def test_trim_tool_observation_preserves_search_snippets_without_noise():
    payload = {
        "query": "assemble_context",
        "results": [
            {
                "path": "src/focus_agent/core/context_policy.py",
                "line_number": 42,
                "line": "def assemble_context(state, mode):",
            }
        ],
        "noise": "POLLUTION" * 1000,
    }

    trimmed = trim_tool_observation(
        json.dumps(payload, ensure_ascii=False),
        tool_name="search_code",
        max_chars=260,
    )

    assert len(trimmed) <= 260
    assert "context_policy.py" in trimmed
    assert "line_number" in trimmed
    assert "POLLUTION" not in trimmed
    assert "summary" in trimmed


def test_trim_tool_observation_preserves_read_file_line_numbers():
    payload = {
        "path": "src/focus_agent/engine/graph_builder.py",
        "start_line": 10,
        "end_line": 200,
        "total_lines": 500,
        "content": "\n".join(f"{line:03d} | important line {line}" for line in range(10, 120)),
    }

    trimmed = trim_tool_observation(
        json.dumps(payload, ensure_ascii=False),
        tool_name="read_file",
        max_chars=420,
    )

    assert len(trimmed) <= 420
    assert "graph_builder.py" in trimmed
    assert "010 | important line 10" in trimmed
    assert "truncated_by_context_policy" in trimmed


def test_trim_tool_observation_artifactizes_prompt_view_with_refs():
    payload = {
        "query": "assemble_context",
        "results": [
            {
                "path": "src/focus_agent/core/context_policy.py",
                "line_number": 42,
                "line": "def assemble_context(state, mode):",
            }
        ],
        "noise": "POLLUTION" * 1000,
    }

    trimmed = trim_tool_observation(
        json.dumps(payload, ensure_ascii=False),
        tool_name="search_code",
        tool_call_id="call-1",
        max_chars=320,
        artifactize_for_prompt=True,
    )

    parsed = json.loads(trimmed)

    assert len(trimmed) <= 320
    assert parsed["artifact_ref"] == "tool-observation://search_code/call-1"
    assert parsed["refs"] == ["src/focus_agent/core/context_policy.py:42"]
    assert parsed.get("results", []) == [] or parsed["results"][0]["ref"] == "src/focus_agent/core/context_policy.py:42"
    assert "POLLUTION" not in trimmed


def test_prompt_budget_guard_artifactizes_tool_messages_without_mutating_stored_message():
    payload = {
        "query": "assemble_context",
        "results": [
            {
                "path": "src/focus_agent/core/context_policy.py",
                "line_number": 42,
                "line": "def assemble_context(state, mode):",
            }
        ],
        "noise": "POLLUTION" * 1000,
    }
    original_tool = ToolMessage(
        content=json.dumps(payload, ensure_ascii=False),
        tool_call_id="call-1",
        artifact={"tool_name": "search_code"},
    )

    guarded = apply_prompt_budget_guard(
        [
            SystemMessage(content="You are Focus Agent."),
            HumanMessage(content="Where is assemble_context defined?"),
            original_tool,
        ],
        budget=ContextBudget(prompt_token_limit=600, chars_per_token=1, tool_observation_token_limit=180),
    )

    guarded_tool = next(message for message in guarded if isinstance(message, ToolMessage))
    parsed = json.loads(str(guarded_tool.content))

    assert parsed["artifact_ref"] == "tool-observation://search_code/call-1"
    assert parsed["refs"] == ["src/focus_agent/core/context_policy.py:42"]
    assert "POLLUTION" not in str(guarded_tool.content)
    assert "artifact_ref" not in str(original_tool.content)
    assert "POLLUTION" in str(original_tool.content)


def test_render_prompt_reorders_blocks_by_prompt_mode():
    state = {
        "messages": [HumanMessage(content="请汇总结论")],
        "rolling_summary": "summary",
        "memory_prompt_block": "## Retrieved long-term memories\n- memory",
        "imported_findings": [FindingItem(finding="Approved finding")],
        "branch_meta": {
            "branch_id": "branch-1",
            "branch_name": "review-branch",
            "branch_role": "verify",
        },
        "branch_local_findings": [FindingItem(finding="Branch finding")],
        "artifacts": [ArtifactRef(title="Artifact one", kind="note")],
        "user_constraints": [{"constraint": "Keep the answer concise."}],
    }

    review = assemble_context(state, PromptMode.BRANCH_REVIEW).render_prompt()
    synthesize = assemble_context(state, PromptMode.SYNTHESIZE).render_prompt()

    assert review.index("## Findings") < review.index("## Constraints and goals")
    assert synthesize.index("## Constraints and goals") < synthesize.index("## Retrieved long-term memories")


def test_trim_tool_observation_wraps_long_text_with_reference_summary():
    text = "very important observation " * 80

    trimmed = trim_tool_observation(
        text,
        tool_name="web_fetch",
        budget=ContextBudget(tool_observation_token_limit=120, chars_per_token=1, tool_reference_token_limit=60),
        artifactize_for_prompt=True,
    )

    assert len(trimmed) <= 120
    assert '"summary"' in trimmed
    assert '"truncated_by_context_policy"' in trimmed


def test_prompt_budget_guard_tokenizer_first_uses_token_estimates(monkeypatch):
    def fake_estimate(message, *, budget):  # noqa: ARG001
        text = str(getattr(message, "content", ""))
        if "Current user turn must stay exact." in text:
            return 20
        if "Preserve this exact constraint." in text:
            return 18
        if "low priority memory" in text:
            return 40
        return max(1, len(text) // 10)

    monkeypatch.setattr(context_policy_module, "_message_budget_units", fake_estimate)

    system_text = "\n\n".join(
        [
            "You are Focus Agent.",
            "## Retrieved long-term memories\n" + ("low priority memory " * 20),
            "## Constraints and goals\n- Preserve this exact constraint.",
        ]
    )
    guarded = apply_prompt_budget_guard(
        [
            SystemMessage(content=system_text),
            HumanMessage(content="Current user turn must stay exact."),
        ],
        budget=ContextBudget(
            prompt_token_limit=45,
            chars_per_token=4,
            token_budget_mode="tokenizer_first",
            tokenizer_id="fake-model",
        ),
    )

    rendered = "\n".join(str(message.content) for message in guarded)
    assert "Preserve this exact constraint." in rendered
    assert "low priority memory" not in rendered


def test_assemble_context_dedupes_imported_and_local_findings_in_prompt():
    state = {
        "branch_meta": {
            "branch_id": "branch-4",
            "branch_name": "owner-fix",
            "branch_role": "verify",
        },
        "imported_findings": [
            FindingItem(
                finding="Owner drops on first load",
                confidence=0.82,
                evidence_refs=["main-doc", "trace-7"],
            )
        ],
        "branch_local_findings": [
            FindingItem(
                finding="Owner drops on first load",
                confidence=0.94,
                evidence_refs=["tmp-note"],
                source_branch_id="branch-4",
            )
        ],
    }

    slice_ = assemble_context(state, PromptMode.EXPLORE)

    assert slice_.findings_block.count("Owner drops on first load") == 1
    assert "## Imported findings already approved into this thread" in slice_.findings_block
    assert "## Local branch findings pending upstream review" not in slice_.findings_block
    assert "main-doc" in slice_.findings_block
    assert "tmp-note" not in slice_.findings_block


def test_assemble_context_dedupes_memory_lines_and_artifacts_with_prompt_preferences():
    state = {
        "_memory_lines": [
            "[branch:branch-1] Owner issue confirmed [score 0.61]",
            "[root_thread/imported_conclusion] Owner issue confirmed [score 0.93]",
        ],
        "branch_meta": {
            "branch_id": "branch-5",
            "branch_name": "artifacts",
            "branch_role": "execute",
        },
        "artifacts": [
            ArtifactRef(title="Owner notes", kind="markdown", uri="file:///tmp/owner-notes.md"),
            ArtifactRef(title="Owner notes", kind="markdown", uri="file:///tmp/owner-notes.md"),
            ArtifactRef(title="Owner notes", kind="markdown"),
        ],
        "context_budget": ContextBudget(citation_limit=4, artifact_limit=4),
    }

    slice_ = assemble_context(state, PromptMode.EXECUTE)

    assert slice_.memory_block.count("Owner issue confirmed") == 1
    assert "root_thread/imported_conclusion" in slice_.memory_block
    assert "branch:branch-1" not in slice_.memory_block
    assert slice_.artifact_block.count("Owner notes [markdown]") == 1
    assert "file:///tmp/owner-notes.md" in slice_.artifact_block
