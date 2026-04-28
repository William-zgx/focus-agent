from __future__ import annotations

from .types import ContextBudget, PromptMode


def render_block_order(prompt_mode: PromptMode) -> tuple[str, ...]:
    if prompt_mode == PromptMode.SYNTHESIZE:
        return (
            "system_instructions",
            "constraints_block",
            "findings_block",
            "memory_block",
            "pinned_block",
            "summary_block",
            "active_skills_block",
            "available_skills_block",
            "artifact_block",
        )
    if prompt_mode == PromptMode.BRANCH_REVIEW:
        return (
            "system_instructions",
            "findings_block",
            "artifact_block",
            "constraints_block",
            "pinned_block",
            "memory_block",
            "summary_block",
            "active_skills_block",
            "available_skills_block",
        )
    if prompt_mode == PromptMode.EXECUTE:
        return (
            "system_instructions",
            "constraints_block",
            "pinned_block",
            "findings_block",
            "artifact_block",
            "memory_block",
            "summary_block",
            "active_skills_block",
            "available_skills_block",
        )
    return (
        "system_instructions",
        "constraints_block",
        "findings_block",
        "artifact_block",
        "memory_block",
        "summary_block",
        "pinned_block",
        "active_skills_block",
        "available_skills_block",
    )


def units_to_char_budget(units: int, *, budget: ContextBudget) -> int:
    multiplier = max(1, int(budget.chars_per_token))
    char_budget = max(0, int(units) * multiplier)
    if units > 0 and budget.token_budget_mode == "tokenizer_first":
        char_budget += max(16, multiplier * 2)
    return char_budget
