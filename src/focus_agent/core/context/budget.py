from __future__ import annotations

from typing import Any

from langchain.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage

from .. import context_prompt_budget as _prompt_budget
from .. import context_token_counting as _token_counting
from .. import context_tool_observation as _tool_observation
from ..types import ContextBudget, PromptMode

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
    prioritized = _prioritize_tokenizer_first_system_messages(prompt_messages, budget=budget)
    return _prompt_budget.apply_prompt_budget_guard(prioritized, budget=budget)


def _prioritize_tokenizer_first_system_messages(
    prompt_messages: list[AnyMessage],
    *,
    budget: ContextBudget,
) -> list[AnyMessage]:
    if budget.token_budget_mode != "tokenizer_first":
        return prompt_messages

    guarded = [
        _prompt_budget._trim_message_tool_observation(message, budget=budget)
        for message in prompt_messages
    ]
    system_indices = [
        index for index, message in enumerate(guarded) if isinstance(message, SystemMessage)
    ]
    if len(system_indices) <= 1:
        return guarded

    counter = _prompt_budget._PromptBudgetCounter(budget)
    if _prompt_budget._within_prompt_budget(guarded, budget=budget, counter=counter):
        return guarded

    main_system_index = system_indices[0]
    mandatory_indices = _prompt_budget._mandatory_prompt_indices(guarded)
    protected_messages = [
        message
        for index, message in enumerate(guarded)
        if index != main_system_index
        and index in mandatory_indices
        and not isinstance(message, SystemMessage)
    ]
    guarded[main_system_index] = _trim_system_message_to_units(
        guarded[main_system_index],
        target_units=max(
            0,
            budget.prompt_token_limit - counter.count(protected_messages),
        ),
        other_messages=protected_messages,
        budget=budget,
    )

    for index in reversed(system_indices[1:]):
        if _prompt_budget._within_prompt_budget(guarded, budget=budget, counter=counter):
            break
        other_messages = [
            message for other_index, message in enumerate(guarded) if other_index != index
        ]
        guarded[index] = _trim_system_message_to_units(
            guarded[index],
            target_units=max(
                0,
                budget.prompt_token_limit - counter.count(other_messages),
            ),
            other_messages=other_messages,
            budget=budget,
        )

    return guarded


def _trim_system_message_to_units(
    message: AnyMessage,
    *,
    target_units: int,
    other_messages: list[AnyMessage],
    budget: ContextBudget,
) -> AnyMessage:
    target_chars = _prompt_budget._units_to_char_budget(target_units, budget=budget)
    if _prompt_budget._enforce_prompt_char_budget(budget):
        target_chars = min(
            target_chars,
            max(
                0,
                _prompt_budget._prompt_char_limit(budget)
                - _prompt_budget._prompt_char_count(other_messages),
            ),
        )
    content = _prompt_budget._trim_system_text_by_blocks(
        _token_counting._text_for_budget(message),
        max_chars=target_chars,
        target_units=target_units,
        budget=budget,
    )
    return _prompt_budget._copy_message_with_content(message, content)


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
