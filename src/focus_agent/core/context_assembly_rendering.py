from __future__ import annotations

from typing import Any

from .context_policy_helpers import render_block_order as _render_block_order_helper
from .types import PromptMode


def _branch_scope_block(*, branch_meta: dict[str, Any], is_branch: bool) -> str:
    if not is_branch:
        return "## Branch scope\n- This is the main thread."

    policy_lines = [
        "- This is a child branch. Stay focused on this local exploration.",
        "- This branch may later be reviewed for upstream import into its return thread.",
        "- Do not assume local branch findings are upstream facts until they are explicitly approved.",
        "- Prepare import-worthy findings clearly, but treat them as local until approved.",
        "- Branch switches or new branches remain pending until a structured Branch Action is confirmed and executed.",
    ]

    lines = [
        "## Branch scope",
        f"- branch_id: {branch_meta.get('branch_id')}",
        f"- branch_name: {branch_meta.get('branch_name')}",
        f"- branch_role: {branch_meta.get('branch_role')}",
        *policy_lines,
    ]
    return "\n".join(lines)


def _mode_instructions(mode: PromptMode) -> str:
    instructions = {
        PromptMode.EXPLORE: (
            "## Prompt mode\n"
            "- explore\n"
            "- Explore hypotheses, surface uncertainties, and keep local conclusions clearly scoped."
        ),
        PromptMode.EXECUTE: (
            "## Prompt mode\n"
            "- execute\n"
            "- Prioritize concrete next steps, follow user constraints closely, and avoid speculative branches.\n"
            "- Do not claim branch changes are complete until a structured Branch Action or branch API result succeeds."
        ),
        PromptMode.SYNTHESIZE: (
            "## Prompt mode\n"
            "- synthesize\n"
            "- Consolidate approved information into a clean answer and avoid surfacing unreviewed branch-local findings."
        ),
        PromptMode.BRANCH_REVIEW: (
            "## Prompt mode\n"
            "- branch_review\n"
            "- Prepare the conversation for merge review by highlighting import-worthy findings, evidence, and artifacts."
        ),
    }
    return instructions[mode]


def _skill_system_block(*, has_available_skills: bool, has_active_skills: bool) -> str:
    if not has_available_skills and not has_active_skills:
        return ""

    lines = ["## Skill system"]
    if has_active_skills:
        lines.append("- Active skills are attached below and should shape the current turn.")
    if has_available_skills:
        lines.append(
            "- Available skill prefixes are listed below for future turns and explicit activation."
        )
    return "\n".join(lines)


def _render_lines(title: str, lines: list[str]) -> str:
    if not lines:
        return f"## {title}\n(none)"
    return "## " + title + "\n" + "\n".join(f"- {line}" for line in lines)


def _context_block_header(block: str) -> str:
    lowered = block.lower()
    if lowered.endswith("(none)"):
        return "empty"
    if lowered.startswith("## constraints and goals") or lowered.startswith("## 当前计划"):
        return "constraints"
    if lowered.startswith("## pinned facts"):
        return "pinned"
    if lowered.startswith("## findings"):
        return "findings"
    if lowered.startswith("## imported findings already approved into this thread"):
        return "imported_findings"
    if lowered.startswith("## local branch findings pending upstream review"):
        return "branch_findings"
    if lowered.startswith("## artifacts in scope"):
        return "artifacts"
    if lowered.startswith("## prompt mode"):
        return "prompt_mode"
    if lowered.startswith("## branch scope"):
        return "branch_scope"
    if lowered.startswith("## scene"):
        return "scene"
    if lowered.startswith("## skill system"):
        return "skill_system"
    if lowered.startswith("## active skills"):
        return "active_skills"
    if lowered.startswith("## rolling summary"):
        return "summary"
    if lowered.startswith("## retrieved long-term memories"):
        return "memory"
    if lowered.startswith("## available skills"):
        return "available_skills"
    return "preamble"


def _context_block_priority(block: str, *, index: int, prompt_mode: PromptMode) -> int:
    header = _context_block_header(block)
    if header == "empty":
        return 5
    ordering = _block_priority_map(prompt_mode)
    return ordering.get(header, 5)


def _block_priority_map(prompt_mode: PromptMode) -> dict[str, int]:
    base = {
        "constraints": 0,
        "imported_findings": 1,
        "findings": 1,
        "pinned": 2,
        "branch_findings": 2,
        "artifacts": 3,
        "preamble": 3,
        "scene": 4,
        "prompt_mode": 4,
        "branch_scope": 4,
        "skill_system": 4,
        "active_skills": 4,
        "memory": 5,
        "summary": 5,
        "available_skills": 5,
    }
    if prompt_mode == PromptMode.SYNTHESIZE:
        return {
            **base,
            "constraints": 0,
            "imported_findings": 0,
            "findings": 0,
            "pinned": 1,
            "memory": 2,
            "summary": 4,
        }
    if prompt_mode == PromptMode.BRANCH_REVIEW:
        return {**base, "branch_findings": 0, "findings": 0, "artifacts": 1, "constraints": 2}
    if prompt_mode == PromptMode.EXECUTE:
        return {
            **base,
            "constraints": 0,
            "pinned": 1,
            "imported_findings": 1,
            "findings": 1,
            "artifacts": 2,
        }
    return {**base, "constraints": 0, "findings": 1, "branch_findings": 1, "imported_findings": 1}


def _render_block_order(prompt_mode: PromptMode) -> tuple[str, ...]:
    return _render_block_order_helper(prompt_mode)


def _current_plan_step_goal(state: dict[str, Any]) -> str:
    plan = state.get("plan")
    current_step_id = str(state.get("current_step_id") or "").strip()
    if current_step_id and hasattr(plan, "steps"):
        for step in getattr(plan, "steps", []) or []:
            if str(getattr(step, "id", "")) == current_step_id:
                return str(getattr(step, "goal", "") or "").strip()
    if plan is None:
        return ""
    steps = getattr(plan, "steps", None)
    if steps is None and isinstance(plan, dict):
        steps = plan.get("steps")
    if not isinstance(steps, list):
        return ""
    for step in steps:
        done = getattr(step, "done", None)
        goal = getattr(step, "goal", None)
        if isinstance(step, dict):
            done = step.get("done", done)
            goal = step.get("goal", goal)
        if not done and goal:
            return str(goal).strip()
    return ""


__all__ = [
    "_block_priority_map",
    "_branch_scope_block",
    "_context_block_header",
    "_context_block_priority",
    "_current_plan_step_goal",
    "_mode_instructions",
    "_render_block_order",
    "_render_lines",
    "_skill_system_block",
]
