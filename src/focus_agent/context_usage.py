from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from langchain.messages import AnyMessage, HumanMessage, SystemMessage

from .core.context_policy import (
    _prompt_budget_count,
    apply_prompt_budget_guard,
    assemble_context,
)
from .core.types import ContextBudget, PromptMode


ContextUsageStatus = Literal["ok", "warm", "hot", "over", "compacting", "error"]


@dataclass(slots=True)
class ContextUsage:
    used_tokens: int
    token_limit: int
    remaining_tokens: int
    used_ratio: float
    status: ContextUsageStatus
    prompt_chars: int
    prompt_budget_chars: int
    tokenizer_mode: str
    last_compacted_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "used_tokens": self.used_tokens,
            "token_limit": self.token_limit,
            "remaining_tokens": self.remaining_tokens,
            "used_ratio": self.used_ratio,
            "status": self.status,
            "prompt_chars": self.prompt_chars,
            "prompt_budget_chars": self.prompt_budget_chars,
            "tokenizer_mode": self.tokenizer_mode,
            "last_compacted_at": self.last_compacted_at,
        }


def context_usage_status(used_ratio: float) -> ContextUsageStatus:
    if used_ratio >= 1:
        return "over"
    if used_ratio >= 0.85:
        return "hot"
    if used_ratio >= 0.70:
        return "warm"
    return "ok"


def build_context_usage(
    state: dict[str, Any],
    *,
    draft_message: str | None = None,
    selected_model: str | None = None,
) -> ContextUsage:
    budget = _context_budget_from_state(state, selected_model=selected_model)
    prompt_mode = _prompt_mode_from_state(state)
    context_slice = assemble_context(
        {
            **dict(state),
            "context_budget": budget,
        },
        prompt_mode,
    )
    assembled_context = context_slice.render_prompt()
    prompt_messages: list[AnyMessage] = [SystemMessage(content=assembled_context), *context_slice.recent_messages]
    if draft_message and str(draft_message).strip():
        prompt_messages.append(HumanMessage(content=str(draft_message).strip()))

    guarded = apply_prompt_budget_guard(prompt_messages, budget=budget)
    used_tokens = max(0, int(_prompt_budget_count(guarded, budget=budget)))
    token_limit = max(1, int(budget.prompt_token_limit))
    remaining_tokens = max(0, token_limit - used_tokens)
    used_ratio = min(1.0, used_tokens / token_limit) if token_limit else 0.0
    prompt_chars = sum(len(_message_text_for_chars(message)) for message in guarded)
    prompt_budget_chars = max(1, token_limit * max(1, int(budget.chars_per_token)))
    compaction = state.get("context_compaction") if isinstance(state.get("context_compaction"), dict) else {}
    return ContextUsage(
        used_tokens=used_tokens,
        token_limit=token_limit,
        remaining_tokens=remaining_tokens,
        used_ratio=used_ratio,
        status=context_usage_status(used_ratio),
        prompt_chars=prompt_chars,
        prompt_budget_chars=prompt_budget_chars,
        tokenizer_mode=str(budget.token_budget_mode),
        last_compacted_at=str(compaction.get("last_compacted_at") or "") or None,
    )


def _context_budget_from_state(state: dict[str, Any], *, selected_model: str | None = None) -> ContextBudget:
    value = state.get("context_budget")
    if isinstance(value, ContextBudget):
        budget = value
    elif isinstance(value, dict):
        try:
            budget = ContextBudget.model_validate(value)
        except Exception:  # noqa: BLE001
            budget = ContextBudget()
    else:
        budget = ContextBudget()
    model_id = str(selected_model or state.get("selected_model") or "").strip()
    if budget.tokenizer_id or not model_id:
        return budget
    return budget.model_copy(update={"tokenizer_id": model_id})


def _prompt_mode_from_state(state: dict[str, Any]) -> PromptMode:
    value = state.get("prompt_mode")
    if isinstance(value, PromptMode):
        return value
    if isinstance(value, str):
        try:
            return PromptMode(value)
        except ValueError:
            pass
    if state.get("merge_proposal") and not state.get("merge_decision"):
        return PromptMode.BRANCH_REVIEW
    return PromptMode.EXPLORE


def _message_text_for_chars(message: AnyMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return "".join(str(item) for item in content)
    return str(content)


__all__ = ["ContextUsage", "ContextUsageStatus", "build_context_usage", "context_usage_status"]
