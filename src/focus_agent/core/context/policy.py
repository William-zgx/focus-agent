from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain.messages import AnyMessage

from . import budget as _budget_guard
from .assembly import (
    _branch_scope_block,
    _coerce_artifact_lines,
    _coerce_constraints,
    _coerce_imported_lines,
    _coerce_legacy_imported_lines,
    _coerce_local_finding_lines,
    _coerce_pinned_facts,
    _current_plan_step_goal,
    _dedupe_artifact_lines,
    _dedupe_finding_lines,
    _dedupe_memory_lines,
    _dedupe_preferring_reference,
    _dedupe_text_lines,
    _mode_instructions,
    _render_block_order,
    _render_lines,
    _skill_system_block,
)
from ..context_budget_guard import (
    _coerce_context_budget,
    _coerce_prompt_mode,
    _conversation_safe_messages,
)
from ..state import normalize_agent_state
from ..types import ContextBudget, PromptMode

_estimate_with_tokenizer = _budget_guard._estimate_with_tokenizer
_message_budget_units = _budget_guard._message_budget_units

__all__ = [
    "ContextSlice",
    "_estimate_with_tokenizer",
    "_message_budget_units",
    "_prompt_budget_count",
    "approximate_token_count",
    "apply_prompt_budget_guard",
    "assemble_context",
    "trim_tool_observation",
]


def _with_budget_guard_monkeypatches():
    return {
        "_estimate_with_tokenizer": _budget_guard._estimate_with_tokenizer,
        "_message_budget_units": _budget_guard._message_budget_units,
    }


def _restore_budget_guard_monkeypatches(previous: dict[str, Any]) -> None:
    _budget_guard._estimate_with_tokenizer = previous["_estimate_with_tokenizer"]
    _budget_guard._message_budget_units = previous["_message_budget_units"]


def approximate_token_count(
    value: Any,
    *,
    chars_per_token: int = 4,
    tokenizer_id: str | None = None,
) -> int:
    previous = _with_budget_guard_monkeypatches()
    _budget_guard._estimate_with_tokenizer = _estimate_with_tokenizer
    try:
        return _budget_guard.approximate_token_count(
            value,
            chars_per_token=chars_per_token,
            tokenizer_id=tokenizer_id,
        )
    finally:
        _restore_budget_guard_monkeypatches(previous)


def apply_prompt_budget_guard(
    prompt_messages: list[AnyMessage],
    *,
    budget: ContextBudget,
) -> list[AnyMessage]:
    previous = _with_budget_guard_monkeypatches()
    _budget_guard._estimate_with_tokenizer = _estimate_with_tokenizer
    _budget_guard._message_budget_units = _message_budget_units
    try:
        return _budget_guard.apply_prompt_budget_guard(prompt_messages, budget=budget)
    finally:
        _restore_budget_guard_monkeypatches(previous)


def trim_tool_observation(
    observation: Any,
    *,
    tool_name: str = "",
    tool_call_id: str = "",
    budget: ContextBudget | None = None,
    max_chars: int | None = None,
    artifactize_for_prompt: bool = False,
    force_artifactize: bool = False,
) -> str:
    return _budget_guard.trim_tool_observation(
        observation,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        budget=budget,
        max_chars=max_chars,
        artifactize_for_prompt=artifactize_for_prompt,
        force_artifactize=force_artifactize,
    )


def _prompt_budget_count(messages: list[AnyMessage], *, budget: ContextBudget) -> int:
    previous = _with_budget_guard_monkeypatches()
    _budget_guard._message_budget_units = _message_budget_units
    try:
        return _budget_guard._prompt_budget_count(messages, budget=budget)
    finally:
        _restore_budget_guard_monkeypatches(previous)


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

    def render_prompt(self) -> str:
        section_map = {
            "system_instructions": self.system_instructions,
            "active_skills_block": self.active_skills_block,
            "available_skills_block": self.available_skills_block,
            "memory_block": self.memory_block,
            "summary_block": self.summary_block,
            "pinned_block": self.pinned_block,
            "constraints_block": self.constraints_block,
            "findings_block": self.findings_block,
            "artifact_block": self.artifact_block,
        }
        ordered_keys = _render_block_order(self.prompt_mode)
        return "\n\n".join(section_map[key] for key in ordered_keys if section_map.get(key))


def assemble_context(state: dict[str, Any], mode: PromptMode | str) -> ContextSlice:
    normalized = normalize_agent_state(state)
    prompt_mode = _coerce_prompt_mode(mode or normalized.get("prompt_mode"))
    budget = _coerce_context_budget(normalized.get("context_budget"))
    branch_meta = normalized.get("branch_meta") or {}
    is_branch = bool(branch_meta)

    messages = list(normalized.get("messages", []) or normalized.get("recent_messages", []))
    recent_messages = _conversation_safe_messages(messages, limit=budget.recent_message_limit)

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
    constraint_lines = [item.constraint for item in constraints]
    if normalized.get("active_goal"):
        constraint_lines.insert(0, f"Active goal: {normalized['active_goal']}")
    current_step_goal = _current_plan_step_goal(normalized)
    if current_step_goal:
        constraint_lines.insert(1 if constraint_lines else 0, f"Current step: {current_step_goal}")
    constraint_lines = _dedupe_text_lines(constraint_lines, limit=10)

    imported_lines = _coerce_imported_lines(normalized.get("imported_findings", []))
    legacy_imported_lines = _coerce_legacy_imported_lines(normalized.get("merge_queue", []))

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

    system_instructions = "\n\n".join(
        [
            "You are Focus Agent, a concise research-oriented assistant optimized for long dialogues.",
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

    return ContextSlice(
        prompt_mode=prompt_mode,
        system_instructions=system_instructions,
        recent_messages=recent_messages,
        active_skills_block=active_skills_block,
        available_skills_block=available_skills_block,
        memory_block=memory_block,
        summary_block=f"## Rolling summary\n{normalized.get('rolling_summary') or '(empty)'}",
        pinned_block=_render_lines("Pinned facts", pinned_lines[-10:]),
        constraints_block=_render_lines("Constraints and goals", constraint_lines[-10:]),
        findings_block=findings_block,
        artifact_block=_render_lines("Artifacts in scope", artifact_lines),
    )
