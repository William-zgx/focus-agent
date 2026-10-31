from __future__ import annotations

from langchain.messages import HumanMessage

from focus_agent.core.context.policy import assemble_context
from focus_agent.core.types import FindingItem, PromptMode


def _main_state(branch_count: int = 3) -> dict:
    imported_findings = []
    merge_queue = []
    for index in range(branch_count):
        branch_id = f"b{index}"
        findings = [f"branch{index} finding {k} " + "x" * (10 * (3 - index)) for k in range(4)]
        imported_findings.extend(
            FindingItem(finding=item, source_branch_id=branch_id).model_dump(mode="json")
            for item in findings
        )
        merge_queue.append(
            {
                "branch_id": branch_id,
                "branch_name": f"branch{index}",
                "summary": f"branch{index} summary",
                "key_findings": findings,
                "open_questions": [f"branch{index} open question"],
                "evidence_refs": [f"doc-{index}"],
                "artifacts": [f"artifact-{index}.md"],
                "imported_at": f"2026-10-0{index + 1}T00:00:00+00:00",
            }
        )
    return {
        "messages": [HumanMessage(content="continue", id="m1")],
        "imported_findings": imported_findings,
        "merge_queue": merge_queue,
    }


def test_main_thread_renders_approved_conclusions_newest_first_with_labels():
    context = assemble_context(_main_state(), PromptMode.EXPLORE)

    block = context.approved_conclusions_block
    assert block.startswith("## Approved branch conclusions")
    assert block.index("[branch2 · 2026-10-03]") < block.index("[branch0 · 2026-10-01]")
    for index in range(3):
        assert f"branch{index} summary" in block
        assert f"branch{index} open question" in block
        assert f"artifact-{index}.md" in block
        for k in range(4):
            assert f"branch{index} finding {k}" in block
    assert "[evidence: doc-0]" in block
    # Findings represented in the block do not compete for the generic findings budget.
    assert "branch0 finding" not in context.findings_block
    assert context.render_prompt().index("## Approved branch conclusions") < (
        context.render_prompt().index("## Findings")
    )


def test_approved_conclusions_survive_parent_compaction():
    state = _main_state()
    state["rolling_summary"] = ""
    state["context_compaction"] = {"compaction_version": 2, "history_summary": "Older chat."}

    prompt = assemble_context(state, PromptMode.SYNTHESIZE).render_prompt()

    assert "branch0 summary" in prompt
    assert "branch2 open question" in prompt


def test_legacy_merge_queue_entries_still_render():
    state = {
        "messages": [HumanMessage(content="continue")],
        "merge_queue": [{"branch_name": "legacy", "summary": "legacy summary"}],
    }

    block = assemble_context(state, PromptMode.EXPLORE).approved_conclusions_block

    assert "[legacy] legacy summary" in block
