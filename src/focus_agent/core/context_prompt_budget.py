from __future__ import annotations

from langchain.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage

from .context_assembly import _context_block_priority
from .context_policy_helpers import units_to_char_budget as _units_to_char_budget_helper
from .context_token_counting import _message_budget_units, _text_for_budget
from .context_tool_observation import (
    _prompt_observation_for_tool_message,
    _tool_message_was_runtime_compacted,
    _tool_name_for_tool_message,
    _tool_observation_char_limit,
    _tool_observation_within_budget,
    trim_tool_observation,
)
from .types import ContextBudget, PromptMode


def apply_prompt_budget_guard(
    prompt_messages: list[AnyMessage],
    *,
    budget: ContextBudget,
) -> list[AnyMessage]:
    """Deterministically trim a prompt before model invocation."""
    counter = _PromptBudgetCounter(budget)
    guarded = [
        _trim_message_tool_observation(message, budget=budget) for message in prompt_messages
    ]
    if _within_prompt_budget(guarded, budget=budget, counter=counter):
        return guarded

    main_system_index = _first_main_system_index(guarded)
    if main_system_index is not None:
        mandatory_indices = _mandatory_prompt_indices(guarded)
        other_messages = [
            message
            for index, message in enumerate(guarded)
            if index != main_system_index
            and (index in mandatory_indices or isinstance(message, SystemMessage))
        ]
        other_units = counter.count(other_messages)
        target_units = max(0, budget.prompt_token_limit - other_units)
        target_chars = _units_to_char_budget(target_units, budget=budget)
        if _enforce_prompt_char_budget(budget):
            target_chars = min(
                target_chars,
                max(0, _prompt_char_limit(budget) - _prompt_char_count(other_messages)),
            )
        trimmed_system = _trim_system_text_by_blocks(
            _text_for_budget(guarded[main_system_index]),
            max_chars=target_chars,
            target_units=target_units,
            budget=budget,
        )
        guarded[main_system_index] = _copy_message_with_content(
            guarded[main_system_index],
            trimmed_system,
        )

    if _within_prompt_budget(guarded, budget=budget, counter=counter):
        return guarded

    mandatory_indices = _mandatory_prompt_indices(guarded)
    removable = [
        index
        for index, message in enumerate(guarded)
        if index not in mandatory_indices and not isinstance(message, SystemMessage)
    ]
    for index in reversed(removable):
        if _within_prompt_budget(guarded, budget=budget, counter=counter):
            break
        del guarded[index]
        mandatory_indices = _mandatory_prompt_indices(guarded)

    if _within_prompt_budget(guarded, budget=budget, counter=counter):
        return guarded

    guarded = _shrink_tool_messages_to_fit(guarded, budget=budget, counter=counter)
    if _within_prompt_budget(guarded, budget=budget, counter=counter):
        return guarded

    return _hard_limit_prompt_messages(guarded, budget=budget, counter=counter)


def _prompt_char_limit(budget: ContextBudget) -> int:
    return max(1, int(budget.prompt_token_limit) * max(1, int(budget.chars_per_token)))


def _prompt_char_count(messages: list[AnyMessage]) -> int:
    return sum(len(_text_for_budget(message)) for message in messages)


def _within_prompt_budget(
    messages: list[AnyMessage],
    *,
    budget: ContextBudget,
    counter: _PromptBudgetCounter,
) -> bool:
    if counter.count(messages) > budget.prompt_token_limit:
        return False
    if not _enforce_prompt_char_budget(budget):
        return True
    return _prompt_char_count(messages) <= _prompt_char_limit(budget)


def _enforce_prompt_char_budget(budget: ContextBudget) -> bool:
    return (
        budget.token_budget_mode != "tokenizer_first"
        or not budget.tokenizer_id
        or budget.chars_per_token <= 1
    )


def _copy_message_with_content(message: AnyMessage, content: str) -> AnyMessage:
    if hasattr(message, "model_copy"):
        return message.model_copy(update={"content": content})
    return type(message)(content=content)


def _first_main_system_index(messages: list[AnyMessage]) -> int | None:
    for index, message in enumerate(messages):
        if isinstance(message, SystemMessage):
            return index
    return None


def _mandatory_prompt_indices(messages: list[AnyMessage]) -> set[int]:
    indices = {
        index for index, message in enumerate(messages) if isinstance(message, SystemMessage)
    }
    latest_human = _latest_human_index(messages)
    if latest_human is not None:
        indices.add(latest_human)

    trailing_tool_start = _trailing_tool_span_start(messages)
    if trailing_tool_start is not None:
        indices.update(range(trailing_tool_start, len(messages)))
    return indices


def _latest_human_index(messages: list[AnyMessage]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return index
    return None


def _trailing_tool_span_start(messages: list[AnyMessage]) -> int | None:
    index = len(messages) - 1
    while index >= 0 and isinstance(messages[index], ToolMessage):
        index -= 1
    if index < 0:
        return None
    message = messages[index]
    if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
        return index
    return None


def _trim_system_text_by_blocks(
    text: str,
    *,
    max_chars: int,
    target_units: int | None = None,
    budget: ContextBudget | None = None,
) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text

    blocks = _split_context_blocks(text)
    prompt_mode = _prompt_mode_from_blocks(blocks)
    selected: set[int] = set()
    omitted = False
    used = 0
    unit_budget = (
        max(0, int(target_units)) if target_units is not None and budget is not None else None
    )
    used_units = 0

    for priority in range(0, 6):
        for index, block in enumerate(blocks):
            if (
                index in selected
                or _context_block_priority(block, index=index, prompt_mode=prompt_mode) != priority
            ):
                continue
            extra = len(block) + (2 if selected else 0)
            extra_units = (
                _message_budget_units(SystemMessage(content=block), budget=budget)
                if unit_budget is not None and budget is not None
                else 0
            )
            fits_unit_budget = unit_budget is None or used_units + extra_units <= unit_budget
            if used + extra <= max_chars and fits_unit_budget:
                selected.add(index)
                used += extra
                if unit_budget is not None:
                    used_units += extra_units
                continue
            remaining = max_chars - used - (2 if selected else 0)
            if priority <= 1 and remaining >= _minimum_truncation_budget(block):
                blocks[index] = _truncate_context_block(block, max_chars=remaining)
                selected.add(index)
                used = max_chars
                if unit_budget is not None:
                    used_units = unit_budget
            elif priority <= 3 and remaining >= _minimum_truncation_budget(block):
                blocks[index] = _truncate_context_block(block, max_chars=remaining)
                selected.add(index)
                used = max_chars
                if unit_budget is not None:
                    used_units = unit_budget
            else:
                omitted = True

    if not selected:
        return _truncate_block(text, max_chars=max_chars)

    rendered = "\n\n".join(blocks[index] for index in sorted(selected) if blocks[index])
    if omitted:
        note = "\n\n## Context trimming\n- Lower-priority context omitted to fit the prompt budget."
        if len(rendered) + len(note) <= max_chars:
            rendered += note
    if len(rendered) <= max_chars:
        return rendered
    return _truncate_block(rendered, max_chars=max_chars)


def _split_context_blocks(text: str) -> list[str]:
    return [block.strip() for block in text.split("\n\n") if block.strip()]


def _prompt_mode_from_blocks(blocks: list[str]) -> PromptMode:
    for block in blocks:
        lowered = block.lower()
        if not lowered.startswith("## prompt mode"):
            continue
        if "- execute" in lowered:
            return PromptMode.EXECUTE
        if "- synthesize" in lowered:
            return PromptMode.SYNTHESIZE
        if "- branch_review" in lowered:
            return PromptMode.BRANCH_REVIEW
    return PromptMode.EXPLORE


def _truncate_context_block(text: str, *, max_chars: int) -> str:
    structured = _truncate_bulleted_block(text, max_chars=max_chars)
    if structured:
        return structured
    return _truncate_block(text, max_chars=max_chars)


def _minimum_truncation_budget(text: str) -> int:
    first_line = text.splitlines()[0].strip() if text.splitlines() else ""
    return max(36, min(96, len(first_line) + 8))


def _truncate_block(text: str, *, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 24:
        return text[:max_chars]
    marker = "\n...[trimmed]...\n"
    keep = max_chars - len(marker)
    if keep <= 0:
        return text[:max_chars]
    head = max(1, keep // 2)
    tail = max(1, keep - head)
    return text[:head].rstrip() + marker + text[-tail:].lstrip()


def _shrink_tool_messages_to_fit(
    messages: list[AnyMessage],
    *,
    budget: ContextBudget,
    counter: _PromptBudgetCounter | None = None,
) -> list[AnyMessage]:
    guarded = list(messages)
    budget_counter = counter or _PromptBudgetCounter(budget)
    for index in range(len(guarded) - 1, -1, -1):
        current_count = budget_counter.count(guarded)
        if _within_prompt_budget(guarded, budget=budget, counter=budget_counter):
            break
        message = guarded[index]
        if not isinstance(message, ToolMessage):
            continue
        overflow_units = max(0, current_count - budget.prompt_token_limit)
        overflow_chars = (
            max(0, _prompt_char_count(guarded) - _prompt_char_limit(budget))
            if _enforce_prompt_char_budget(budget)
            else 0
        )
        current = _text_for_budget(message)
        target = max(
            200,
            len(current)
            - max(_units_to_char_budget(overflow_units, budget=budget), overflow_chars)
            - 16,
        )
        guarded[index] = _copy_message_with_content(
            message,
            trim_tool_observation(
                current,
                tool_name=_tool_name_for_tool_message(message),
                tool_call_id=str(getattr(message, "tool_call_id", "") or ""),
                max_chars=target,
                budget=budget,
                artifactize_for_prompt=True,
                force_artifactize=_tool_message_was_runtime_compacted(message, max_chars=target),
            ),
        )
    return guarded


def _hard_limit_prompt_messages(
    messages: list[AnyMessage],
    *,
    budget: ContextBudget,
    counter: _PromptBudgetCounter | None = None,
) -> list[AnyMessage]:
    guarded = list(messages)
    budget_counter = counter or _PromptBudgetCounter(budget)
    latest_human = _latest_human_index(guarded)
    ordered_indices = [
        *[
            index
            for index in range(len(guarded) - 1, -1, -1)
            if isinstance(guarded[index], ToolMessage)
        ],
        *[
            index
            for index in range(len(guarded) - 1, -1, -1)
            if isinstance(guarded[index], SystemMessage)
        ],
        *[
            index
            for index in range(len(guarded) - 1, -1, -1)
            if index != latest_human
            and not isinstance(guarded[index], (SystemMessage, ToolMessage))
        ],
    ]
    if latest_human is not None:
        ordered_indices.append(latest_human)

    seen: set[int] = set()
    for index in ordered_indices:
        if index in seen or index >= len(guarded):
            continue
        seen.add(index)
        current_count = budget_counter.count(guarded)
        if _within_prompt_budget(guarded, budget=budget, counter=budget_counter):
            break
        message = guarded[index]
        current = _text_for_budget(message)
        overflow_units = max(0, current_count - budget.prompt_token_limit)
        overflow_chars = (
            max(0, _prompt_char_count(guarded) - _prompt_char_limit(budget))
            if _enforce_prompt_char_budget(budget)
            else 0
        )
        target = max(
            0,
            len(current)
            - max(_units_to_char_budget(overflow_units, budget=budget), overflow_chars)
            - 16,
        )
        if isinstance(message, ToolMessage):
            content = trim_tool_observation(
                current,
                tool_name=_tool_name_for_tool_message(message),
                tool_call_id=str(getattr(message, "tool_call_id", "") or ""),
                max_chars=target,
                budget=budget,
                artifactize_for_prompt=True,
                force_artifactize=_tool_message_was_runtime_compacted(message, max_chars=target),
            )
        elif isinstance(message, SystemMessage):
            content = _truncate_context_block(current, max_chars=target)
        else:
            content = _truncate_block(current, max_chars=target)
        guarded[index] = _copy_message_with_content(message, content)

    return guarded


class _PromptBudgetCounter:
    def __init__(self, budget: ContextBudget) -> None:
        self.budget = budget
        self._message_cache: dict[tuple[int, str], int] = {}
        self._system_block_cache: dict[str, int] = {}

    def count(self, messages: list[AnyMessage]) -> int:
        return sum(self.message_units(message) for message in messages)

    def message_units(self, message: AnyMessage) -> int:
        if isinstance(message, SystemMessage):
            return self.system_units(str(message.content))
        text = _text_for_budget(message)
        key = (id(message), text)
        cached = self._message_cache.get(key)
        if cached is not None:
            return cached
        value = _message_budget_units(message, budget=self.budget)
        self._message_cache[key] = value
        return value

    def system_units(self, text: str) -> int:
        cached = self._system_block_cache.get(text)
        if cached is not None:
            return cached
        value = _system_message_budget_units(text, budget=self.budget)
        self._system_block_cache[text] = value
        return value


def _prompt_budget_count(messages: list[AnyMessage], *, budget: ContextBudget) -> int:
    return _PromptBudgetCounter(budget).count(messages)


def _system_message_budget_units(text: str, *, budget: ContextBudget) -> int:
    blocks = _split_context_blocks(text)
    if not blocks:
        return _message_budget_units(SystemMessage(content=text), budget=budget)
    return sum(
        _message_budget_units(SystemMessage(content=block), budget=budget) for block in blocks
    )


def _trim_message_tool_observation(message: AnyMessage, *, budget: ContextBudget) -> AnyMessage:
    if not isinstance(message, ToolMessage):
        return message
    prompt_observation = _prompt_observation_for_tool_message(message)
    if prompt_observation:
        if _tool_observation_within_budget(
            prompt_observation,
            budget=budget,
            max_chars=_tool_observation_char_limit(budget),
            enforce_token_budget=True,
        ):
            trimmed = prompt_observation
        else:
            trimmed = trim_tool_observation(
                prompt_observation,
                tool_name=_tool_name_for_tool_message(message),
                tool_call_id=str(getattr(message, "tool_call_id", "") or ""),
                budget=budget,
                artifactize_for_prompt=True,
            )
    else:
        trimmed = trim_tool_observation(
            str(message.content),
            tool_name=_tool_name_for_tool_message(message),
            tool_call_id=str(getattr(message, "tool_call_id", "") or ""),
            budget=budget,
            artifactize_for_prompt=True,
            force_artifactize=_tool_message_was_runtime_compacted(
                message,
                max_chars=_tool_observation_char_limit(budget),
            ),
        )
    if trimmed == message.content and not prompt_observation:
        return message
    return _copy_message_with_content(message, trimmed)


def _units_to_char_budget(units: int, *, budget: ContextBudget) -> int:
    return _units_to_char_budget_helper(units, budget=budget)


def _truncate_bulleted_block(text: str, *, max_chars: int) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    if len(lines) < 2 or not lines[0].startswith("## "):
        return ""

    header = lines[0].strip()
    body_lines = [line.strip() for line in lines[1:] if line.strip()]
    if not body_lines:
        return ""

    kept_lines = [header]
    used = len(header)
    omitted_lines: list[str] = []
    prioritized_lines = list(body_lines)
    if header.casefold().startswith("## constraints and goals"):
        bullets = [line for line in body_lines if line.startswith("- ")]
        if bullets:
            last_bullet = bullets[-1]
            prioritized_lines = [last_bullet, *[line for line in body_lines if line != last_bullet]]

    for body_line in prioritized_lines:
        extra = len(body_line) + 1
        if used + extra > max_chars:
            omitted_lines.append(body_line)
            continue
        kept_lines.append(body_line)
        used += extra

    if len(kept_lines) == 1:
        omitted_note = f"- ...[{len(body_lines)} omitted]"
        if len(header) + 1 + len(omitted_note) <= max_chars:
            return "\n".join([header, omitted_note])
        return header if len(header) <= max_chars else _truncate_block(header, max_chars=max_chars)

    rendered = "\n".join(kept_lines)
    if omitted_lines:
        note = f"\n- ...[{len(omitted_lines)} more omitted]"
        if len(rendered) + len(note) <= max_chars:
            rendered += note
    return rendered
