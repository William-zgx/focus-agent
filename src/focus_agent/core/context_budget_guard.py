from __future__ import annotations

from typing import Any

from langchain.messages import AIMessage, AnyMessage, ToolMessage

from . import context_prompt_budget as _prompt_budget
from . import context_token_counting as _token_counting
from . import context_tool_observation as _tool_observation
from .types import ContextBudget, PromptMode

_estimate_with_tokenizer = _token_counting._estimate_with_tokenizer
_message_budget_units = _token_counting._message_budget_units


def approximate_token_count(
    value: Any,
    *,
    chars_per_token: int = 4,
    tokenizer_id: str | None = None,
) -> int:
    _sync_token_counting_hooks()
    return _token_counting.approximate_token_count(
        value,
        chars_per_token=chars_per_token,
        tokenizer_id=tokenizer_id,
    )


def apply_prompt_budget_guard(
    prompt_messages: list[AnyMessage],
    *,
    budget: ContextBudget,
) -> list[AnyMessage]:
    _sync_prompt_budget_hooks()
    return _prompt_budget.apply_prompt_budget_guard(prompt_messages, budget=budget)


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
    _sync_token_counting_hooks()
    return _tool_observation.trim_tool_observation(
        observation,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        budget=budget,
        max_chars=max_chars,
        artifactize_for_prompt=artifactize_for_prompt,
        force_artifactize=force_artifactize,
    )


def _prompt_budget_count(messages: list[AnyMessage], *, budget: ContextBudget) -> int:
    _sync_prompt_budget_hooks()
    return _prompt_budget._prompt_budget_count(messages, budget=budget)


def _coerce_prompt_mode(mode: PromptMode | str | None) -> PromptMode:
    if isinstance(mode, PromptMode):
        return mode
    if isinstance(mode, str):
        try:
            return PromptMode(mode)
        except ValueError:
            return PromptMode.EXPLORE
    return PromptMode.EXPLORE


def _conversation_safe_messages(messages: list[AnyMessage], *, limit: int) -> list[AnyMessage]:
    safe_messages: list[AnyMessage] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            continue
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            continue
        safe_messages.append(message)
    return safe_messages[-limit:]


def _coerce_context_budget(value: Any) -> ContextBudget:
    if isinstance(value, ContextBudget):
        return value
    if isinstance(value, dict):
        return ContextBudget.model_validate(value)
    return ContextBudget()


def _sync_token_counting_hooks() -> None:
    _token_counting._estimate_with_tokenizer = _estimate_with_tokenizer


def _sync_prompt_budget_hooks() -> None:
    _sync_token_counting_hooks()
    _prompt_budget._message_budget_units = _message_budget_units
    _prompt_budget.trim_tool_observation = trim_tool_observation


__all__ = [
    "_coerce_context_budget",
    "_coerce_prompt_mode",
    "_conversation_safe_messages",
    "_estimate_with_tokenizer",
    "_message_budget_units",
    "_prompt_budget_count",
    "approximate_token_count",
    "apply_prompt_budget_guard",
    "trim_tool_observation",
]
