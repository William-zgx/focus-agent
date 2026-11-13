from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain.messages import AnyMessage

from ..branch_brief import resolve_fork_brief
from ..branch_conclusions import render_approved_conclusions
from ..context_assembly_coercion import (
    _coerce_artifact_lines,
    _coerce_constraints,
    _coerce_imported_lines,
    _coerce_legacy_imported_lines,
    _coerce_local_finding_lines,
    _coerce_pinned_facts,
)
from ..context_assembly_lines import (
    _dedupe_artifact_lines,
    _dedupe_finding_lines,
    _dedupe_memory_lines,
    _dedupe_preferring_reference,
    _dedupe_text_lines,
)
from ..context_assembly_rendering import (
    _branch_scope_block,
    _current_plan_step_goal,
    _mode_instructions,
    _render_block_order,
    _render_lines,
    _skill_system_block,
)
from ..context_compaction import select_recent_messages
from ..context_token_counting import approximate_token_count
from ..state import normalize_agent_state
from ..types import ContextBudget, PromptMode
from .budget import _coerce_prompt_mode, _conversation_safe_messages, apply_prompt_budget_guard
from .tool_observations import trim_tool_observation

# Budget helpers remain public here for legacy context_policy callers.
__all__ = [
    "ContextSlice",
    "apply_prompt_budget_guard",
    "approximate_token_count",
    "assemble_context",
    "trim_tool_observation",
]


@dataclass(slots=True)
class ContextSlice:
    prompt_mode: PromptMode
    system_instructions: str
    recent_messages: list[AnyMessage]
    active_skills_block: str
    available_skills_block: str
    memory_block: str
    summary_block: str
    pinned_block: str
    constraints_block: str
    findings_block: str
    artifact_block: str
    approved_conclusions_block: str = ""

    def render_prompt(self) -> str:
        section_map = {
            "system_instructions": self.system_instructions,
            "active_skills_block": self.active_skills_block,
            "available_skills_block": self.available_skills_block,
            "memory_block": self.memory_block,
            "summary_block": self.summary_block,
            "pinned_block": self.pinned_block,
            "constraints_block": self.constraints_block,
            "approved_conclusions_block": self.approved_conclusions_block,
            "findings_block": self.findings_block,
            "artifact_block": self.artifact_block,
        }
        ordered_keys = _render_block_order(self.prompt_mode)
        return "\n\n".join(section_map[key] for key in ordered_keys if section_map.get(key))


def assemble_context(state: dict[str, Any], mode: PromptMode | str) -> ContextSlice:
    normalized = normalize_agent_state(state)
    prompt_mode = _coerce_prompt_mode(mode or normalized.get("prompt_mode"))
    budget = ContextBudget.coerce(normalized.get("context_budget"))
    branch_meta = normalized.get("branch_meta") or {}
    is_branch = bool(branch_meta)
    fork_brief = resolve_fork_brief(normalized) if is_branch else None
    if fork_brief is not None:
        branch_meta = {**branch_meta, "fork_brief": fork_brief}

    messages = select_recent_messages({**normalized, "context_budget": budget})
    recent_messages = _conversation_safe_messages(messages, limit=max(1, len(messages)))

    memory_lines = _dedupe_memory_lines(
        [str(item) for item in state.get("_memory_lines", [])],
        limit=budget.citation_limit,
    )
    memory_block = str(normalized.get("memory_prompt_block") or "").strip()
    if not memory_block:
        memory_block = _render_lines("Retrieved long-term memories", memory_lines)
    active_skills_block = str(
        state.get("_active_skills_block") or normalized.get("active_skills_block") or ""
    ).strip()
    available_skills_block = str(
        state.get("_available_skills_block") or normalized.get("available_skills_block") or ""
    ).strip()
    scene = str(state.get("_scene") or "long_dialog_research")

    pinned_facts = _coerce_pinned_facts(normalized.get("pinned_facts", []))
    pinned_lines = [item.fact for item in pinned_facts]
    pinned_lines.extend(str(item) for item in normalized.get("pinned_items", []))
    pinned_lines = _dedupe_text_lines(pinned_lines, limit=10)

    constraints = _coerce_constraints(normalized.get("user_constraints", []))
    active_goal = str(normalized.get("active_goal") or "").strip()
    if not active_goal and fork_brief is not None:
        active_goal = str(fork_brief.get("goal") or "").strip()
    current_step_goal = _current_plan_step_goal(normalized)
    goal_lines = [
        *([f"Active goal: {active_goal}"] if active_goal else []),
        *([f"Current step: {current_step_goal}"] if current_step_goal else []),
    ]
    constraint_lines = goal_lines + _dedupe_text_lines(
        [item.constraint for item in constraints], limit=10 - len(goal_lines)
    )

    merge_queue = list(normalized.get("merge_queue", []) or [])
    approved_conclusions_block, rendered_entries = render_approved_conclusions(merge_queue)
    rendered_keys = {_merge_entry_key(entry) for entry in rendered_entries}
    rendered_branch_ids = {
        str(entry.get("branch_id")) for entry in rendered_entries if entry.get("branch_id")
    }
    # Conclusions rendered in their own block do not compete for findings slots.
    imported_lines = _coerce_imported_lines(
        item
        for item in normalized.get("imported_findings", [])
        if _finding_source_branch_id(item) not in rendered_branch_ids
    )
    legacy_imported_lines = _coerce_legacy_imported_lines(
        item
        for item in merge_queue
        if not (isinstance(item, dict) and _merge_entry_key(item) in rendered_keys)
    )

    local_finding_lines: list[str] = []
    if is_branch and prompt_mode in {
        PromptMode.EXPLORE,
        PromptMode.EXECUTE,
        PromptMode.BRANCH_REVIEW,
    }:
        local_finding_lines = _coerce_local_finding_lines(
            normalized.get("branch_local_findings", []),
            limit=budget.findings_limit,
        )

    artifact_lines = _coerce_artifact_lines(
        normalized.get("artifacts", []),
        limit=budget.artifact_limit,
        include_local=is_branch and prompt_mode != PromptMode.SYNTHESIZE,
    )

    imported_lines = _dedupe_finding_lines(
        imported_lines + legacy_imported_lines, limit=budget.findings_limit
    )
    local_finding_lines = _dedupe_preferring_reference(
        imported_lines, local_finding_lines, limit=budget.findings_limit
    )
    artifact_lines = _dedupe_artifact_lines(artifact_lines, limit=budget.artifact_limit)

    if normalized.get("retrieved_memories"):
        # Re-render structured sources instead of retaining a stale opaque block.
        from ...memory.assembler import render_scoped_context_memories

        memory_block = render_scoped_context_memories(
            normalized,
            prompt_mode=prompt_mode,
            represented_lines=[*imported_lines, *local_finding_lines],
            fallback=memory_block,
        )

    system_instructions = "\n\n".join(
        [
            "You are Focus Agent, a concise research-oriented assistant optimized for long dialogues.",
            (
                "Follow the user's explicit output-language instruction exactly. "
                "When the user writes in Chinese or explicitly requests Chinese, "
                "write the final answer in Chinese and translate source material "
                "instead of returning an English-only answer."
            ),
            _mode_instructions(prompt_mode),
            _skill_system_block(
                has_available_skills=bool(available_skills_block),
                has_active_skills=bool(active_skills_block),
            ),
            f"## Scene\n- {scene}",
            _branch_scope_block(branch_meta=branch_meta, is_branch=is_branch),
        ]
    )

    findings_sections: list[str] = []
    if imported_lines:
        findings_sections.append(
            _render_lines("Imported findings already approved into this thread", imported_lines)
        )
    if local_finding_lines:
        findings_sections.append(
            _render_lines("Local branch findings pending upstream review", local_finding_lines)
        )
    findings_block = (
        "## Findings\n" + "\n".join(findings_sections)
        if findings_sections
        else _render_lines("Findings", [])
    )
    compaction = normalized.get("context_compaction") or {}
    summary = normalized.get("rolling_summary") or ""
    if compaction.get("compaction_version") == 2 and "history_summary" in compaction:
        summary = compaction["history_summary"]

    return ContextSlice(
        prompt_mode=prompt_mode,
        system_instructions=system_instructions,
        recent_messages=recent_messages,
        active_skills_block=active_skills_block,
        available_skills_block=available_skills_block,
        memory_block=memory_block,
        summary_block=f"## Rolling summary\n{summary or '(empty)'}",
        pinned_block=_render_lines("Pinned facts", pinned_lines),
        constraints_block=_render_lines("Constraints and goals", constraint_lines),
        findings_block=findings_block,
        artifact_block=_render_lines("Artifacts in scope", artifact_lines),
        approved_conclusions_block=approved_conclusions_block,
    )


def _merge_entry_key(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(entry.get("branch_id") or ""),
        str(entry.get("branch_name") or ""),
        str(entry.get("summary") or ""),
    )


def _finding_source_branch_id(item: Any) -> str | None:
    if isinstance(item, dict):
        source = item.get("source_branch_id")
    else:
        source = getattr(item, "source_branch_id", None)
    return str(source) if source else None
