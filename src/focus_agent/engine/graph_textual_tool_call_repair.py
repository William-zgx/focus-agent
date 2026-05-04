from __future__ import annotations

from typing import Any

from langchain.messages import AIMessage, SystemMessage

from ..core.context_policy import apply_prompt_budget_guard
from ..core.tool_protocol import looks_like_textual_tool_call_artifact
from ..core.types import ContextBudget
from .graph_tool_call_repair import _known_tool_names
from .graph_tool_history_repair import _message_text
from .graph_tool_result_fallback import _invoke_with_tool_result_fallback


_TOOL_EXHAUSTION_NOTE = (
    "You have enough tool results for this turn. Do not call more tools. "
    "Answer the user directly using the information already gathered, and state any uncertainty plainly."
)


_TOOL_CALL_PROTOCOL_REPAIR_NOTE = (
    "If you need a tool, emit a real tool call through the tool-calling interface. "
    "Do not write DSML tags, XML, or function-call payloads into the assistant text. "
    "Do not narrate search, fetch, browse, retry, or calculation attempts as assistant text. "
    "If no tool is needed, answer directly in natural language."
)


_TOOL_CALL_MARKUP_REPAIR_NOTE = (
    "Do not emit tool-call markup, XML, JSON function-call payloads, or DSML tags. "
    "Do not include internal process narration about searching, fetching, browsing, retrying, or calculating. "
    "Write only the final user-facing answer in natural language."
)


_TOOL_CALL_LAST_RESORT_NOTE = (
    "The previous draft still contained internal tool-call markup. "
    "Do not call more tools. Using only the information already gathered in this conversation, "
    "write a concise final answer for the user in natural language."
)


def _looks_like_textual_tool_call_artifact(
    message: Any,
    *,
    known_tool_names: list[str] | set[str] | tuple[str, ...] | None = None,
) -> bool:
    return looks_like_textual_tool_call_artifact(
        _message_text(message),
        known_tool_names=known_tool_names,
    )


def _repair_textual_tool_call_response(
    *,
    response: Any,
    prompt_messages: list[Any],
    fallback_messages: list[Any] | None = None,
    context_budget: ContextBudget,
    selected_model: str,
    selected_thinking_mode: str,
    available_tools: list[Any],
    model_for,
    model_with_tools_for,
) -> Any:
    known_names = _known_tool_names(available_tools)
    if not _looks_like_textual_tool_call_artifact(response, known_tool_names=known_names):
        return response

    repaired_prompt = apply_prompt_budget_guard(
        [
            prompt_messages[0],
            SystemMessage(content=_TOOL_CALL_PROTOCOL_REPAIR_NOTE),
            *prompt_messages[1:],
            AIMessage(content=_message_text(response)),
        ],
        budget=context_budget,
    )
    repaired = _invoke_with_tool_result_fallback(
        model_with_tools_for(selected_model, selected_thinking_mode, available_tools),
        repaired_prompt,
        fallback_messages=fallback_messages or prompt_messages,
        known_tool_names=known_names,
    )
    if not _looks_like_textual_tool_call_artifact(repaired, known_tool_names=known_names):
        return repaired

    fallback_prompt = apply_prompt_budget_guard(
        [
            prompt_messages[0],
            SystemMessage(content=_TOOL_CALL_MARKUP_REPAIR_NOTE),
            *prompt_messages[1:],
            AIMessage(content=_message_text(repaired)),
        ],
        budget=context_budget,
    )
    return _invoke_with_tool_result_fallback(
        model_for(selected_model, selected_thinking_mode),
        fallback_prompt,
        fallback_messages=fallback_messages or prompt_messages,
        known_tool_names=known_names,
    )


def _repair_tool_free_answer_response(
    *,
    response: Any,
    prompt_messages: list[Any],
    fallback_messages: list[Any] | None = None,
    context_budget: ContextBudget,
    selected_model: str,
    selected_thinking_mode: str,
    model_for,
) -> Any:
    from .graph_tool_result_fallback import (
        _has_tool_result_messages,
        _invoke_tool_result_synthesis,
        _tool_result_fallback_message,
    )

    fallback_source_messages = fallback_messages or prompt_messages
    if not _message_text(response).strip() and _has_tool_result_messages(fallback_source_messages):
        synthesized = _invoke_tool_result_synthesis(
            model_for(selected_model, selected_thinking_mode),
            fallback_source_messages,
        )
        if synthesized is not None:
            return synthesized
        return _tool_result_fallback_message(fallback_source_messages)

    if not _looks_like_textual_tool_call_artifact(response):
        return response

    repaired_prompt = apply_prompt_budget_guard(
        [
            prompt_messages[0],
            SystemMessage(content=_TOOL_EXHAUSTION_NOTE),
            SystemMessage(content=_TOOL_CALL_MARKUP_REPAIR_NOTE),
            *prompt_messages[1:],
            AIMessage(content=_message_text(response)),
        ],
        budget=context_budget,
    )
    repaired = _invoke_with_tool_result_fallback(
        model_for(selected_model, selected_thinking_mode),
        repaired_prompt,
        fallback_messages=fallback_source_messages,
    )
    if not _looks_like_textual_tool_call_artifact(repaired):
        return repaired

    final_prompt = apply_prompt_budget_guard(
        [
            prompt_messages[0],
            SystemMessage(content=_TOOL_EXHAUSTION_NOTE),
            SystemMessage(content=_TOOL_CALL_MARKUP_REPAIR_NOTE),
            SystemMessage(content=_TOOL_CALL_LAST_RESORT_NOTE),
            *prompt_messages[1:],
            AIMessage(content=_message_text(repaired)),
        ],
        budget=context_budget,
    )
    final_attempt = _invoke_with_tool_result_fallback(
        model_for(selected_model, selected_thinking_mode),
        final_prompt,
        fallback_messages=fallback_source_messages,
    )
    if not _looks_like_textual_tool_call_artifact(final_attempt):
        return final_attempt

    synthesized = _invoke_tool_result_synthesis(
        model_for(selected_model, selected_thinking_mode),
        fallback_source_messages,
    )
    if synthesized is not None:
        return synthesized

    return _tool_result_fallback_message(fallback_source_messages)


__all__ = [
    "_TOOL_EXHAUSTION_NOTE",
    "_TOOL_CALL_PROTOCOL_REPAIR_NOTE",
    "_TOOL_CALL_MARKUP_REPAIR_NOTE",
    "_TOOL_CALL_LAST_RESORT_NOTE",
    "_looks_like_textual_tool_call_artifact",
    "_repair_textual_tool_call_response",
    "_repair_tool_free_answer_response",
]
