from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from langchain.messages import AnyMessage, HumanMessage, ToolMessage

from ..harness.tools import canonical_tool_schema
from .context.budget import _prompt_budget_count, apply_prompt_budget_guard
from .context_token_counting import (
    TokenCountEstimate,
    estimate_messages_token_count,
    estimate_text_token_count,
)
from .types import ContextBudget


@dataclass(slots=True)
class ContextRequest:
    """The one budgeted message list sent to a model invocation."""

    messages: list[AnyMessage]
    budget: ContextBudget
    configured_token_limit: int
    input_token_limit: int
    pretrim_tokens: int
    posttrim_tokens: int
    tool_schema_tokens: int
    output_reserve_tokens: int
    remaining_tokens: int
    prompt_chars: int
    trimmed: bool
    required_overflow: bool
    estimated: bool
    counting_backend: str
    tokenizer_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "configured_token_limit": self.configured_token_limit,
            "input_token_limit": self.input_token_limit,
            "pretrim_tokens": self.pretrim_tokens,
            "posttrim_tokens": self.posttrim_tokens,
            "tool_schema_tokens": self.tool_schema_tokens,
            "output_reserve_tokens": self.output_reserve_tokens,
            "remaining_tokens": self.remaining_tokens,
            "prompt_chars": self.prompt_chars,
            "trimmed": self.trimmed,
            "required_overflow": self.required_overflow,
            "estimated": self.estimated,
            "counting_backend": self.counting_backend,
            "tokenizer_id": self.tokenizer_id,
        }


def build_context_request(
    messages: Iterable[AnyMessage],
    *,
    budget: ContextBudget,
    available_tools: Iterable[Any] = (),
    output_reserve_tokens: int | None = None,
    preserve_required_messages: bool = True,
) -> ContextRequest:
    """Assemble the final, budgeted model request.

    ``prompt_token_limit`` is the configured request allowance. Tool schemas
    and an explicit completion reserve consume that allowance before message
    trimming. The helper never mutates the caller's message list.
    """

    source_messages = list(messages)
    tools = list(available_tools or ())
    configured_limit = max(1, int(budget.prompt_token_limit))
    reserve = _output_reserve_tokens(budget, output_reserve_tokens)
    schema_estimate = _estimate_tool_schema_tokens(tools, budget=budget)
    input_capacity = configured_limit - reserve - schema_estimate.tokens
    # Keep the diagnostic honest when overhead alone exhausts the configured
    # allowance.  The lower bound for the existing guard is only an internal
    # implementation detail; ``input_limit`` remains zero in the payload.
    input_limit = max(0, input_capacity)
    effective_budget = budget.model_copy(update={"prompt_token_limit": max(1, input_limit)})

    pretrim_estimate = estimate_messages_token_count(source_messages, budget=budget)
    guarded = apply_prompt_budget_guard(
        source_messages,
        budget=effective_budget,
        preserve_required_messages=preserve_required_messages,
    )
    posttrim_estimate = estimate_messages_token_count(guarded, budget=budget)
    posttrim_tokens = max(0, int(_prompt_budget_count(guarded, budget=budget)))
    pretrim_tokens = max(0, int(_prompt_budget_count(source_messages, budget=budget)))
    required_overflow = _required_message_overflow(source_messages, guarded)
    trimmed = _message_payloads(guarded) != _message_payloads(source_messages)
    return ContextRequest(
        messages=guarded,
        budget=effective_budget,
        configured_token_limit=configured_limit,
        input_token_limit=input_limit,
        pretrim_tokens=pretrim_tokens,
        posttrim_tokens=posttrim_tokens,
        tool_schema_tokens=schema_estimate.tokens,
        output_reserve_tokens=reserve,
        remaining_tokens=max(0, input_limit - posttrim_tokens),
        prompt_chars=sum(_message_chars(message) for message in guarded),
        trimmed=trimmed,
        required_overflow=(input_capacity <= 0)
        or required_overflow
        or posttrim_tokens > input_limit,
        # The tokenizer counts rendered payloads, not provider framing. Even
        # requests without tools remain estimates of the final wire request.
        estimated=True,
        counting_backend=_counting_backend(pretrim_estimate, posttrim_estimate, schema_estimate),
        tokenizer_id=(
            schema_estimate.tokenizer_id
            or posttrim_estimate.tokenizer_id
            or pretrim_estimate.tokenizer_id
            or budget.tokenizer_id
        ),
    )


def _output_reserve_tokens(budget: ContextBudget, explicit: int | None) -> int:
    value = explicit
    if value is None:
        value = getattr(budget, "output_token_reserve", 0)
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _estimate_tool_schema_tokens(tools: list[Any], *, budget: ContextBudget) -> TokenCountEstimate:
    if not tools:
        return TokenCountEstimate(
            tokens=0,
            counting_backend="chars_fallback",
            tokenizer_id=budget.tokenizer_id,
            estimated=False,
        )
    payload = []
    for tool in tools:
        schema = canonical_tool_schema(tool)
        # ``canonical_tool_schema`` already carries descriptions for BaseTool
        # instances.  Keep mapping-style tool definitions honest too: some
        # registries pass ``{"name", "description", "input_schema"}``.
        if isinstance(tool, Mapping) and isinstance(schema, dict):
            description = str(tool.get("description") or "")
            if description and not schema.get("description"):
                schema = {**schema, "description": description}
            name = str(tool.get("name") or "")
        else:
            name = str(getattr(tool, "name", "") or "")
        payload.append({"name": name, "schema": schema})
    payload.sort(key=lambda item: (item["name"], json.dumps(item["schema"], sort_keys=True)))
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    return estimate_text_token_count(
        text,
        chars_per_token=budget.chars_per_token,
        tokenizer_id=budget.tokenizer_id,
        tokenizer_first=budget.token_budget_mode == "tokenizer_first",
    )


def _required_message_overflow(source: list[AnyMessage], guarded: list[AnyMessage]) -> bool:
    source_humans = [message for message in source if isinstance(message, HumanMessage)]
    if source_humans:
        latest = str(source_humans[-1].content or "")
        guarded_humans = [message for message in guarded if isinstance(message, HumanMessage)]
        if not guarded_humans or str(guarded_humans[-1].content or "") != latest:
            return True

    source_tool_ids, source_result_ids = _trailing_tool_exchange_ids(source)
    if source_tool_ids:
        guarded_tool_ids, guarded_result_ids = _trailing_tool_exchange_ids(guarded)
        if not source_tool_ids.issubset(guarded_tool_ids):
            return True
        if not source_result_ids.issubset(guarded_result_ids):
            return True
    return False


def _trailing_tool_exchange_ids(messages: list[AnyMessage]) -> tuple[set[str], set[str]]:
    """Return IDs from only the latest tool exchange, not old observations."""

    end = len(messages)
    index = end - 1
    while index >= 0 and isinstance(messages[index], ToolMessage):
        index -= 1
    if index < 0:
        return set(), set()
    calls = getattr(messages[index], "tool_calls", None)
    if not calls:
        return set(), set()
    call_ids = {
        str(call.get("id") or "") for call in calls if isinstance(call, dict) and call.get("id")
    }
    result_ids = {
        str(message.tool_call_id or "")
        for message in messages[index + 1 : end]
        if isinstance(message, ToolMessage) and str(message.tool_call_id or "")
    }
    return call_ids, result_ids


def _message_payloads(messages: list[AnyMessage]) -> list[tuple[str, str]]:
    return [(message.__class__.__name__, _message_text(message)) for message in messages]


def _message_text(message: AnyMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return json.dumps(content, ensure_ascii=False, default=str)
    return str(content or "")


def _message_chars(message: AnyMessage) -> int:
    return len(_message_text(message))


def _counting_backend(*estimates: TokenCountEstimate) -> str:
    if any(estimate.estimated for estimate in estimates):
        return "chars_fallback"
    return next(
        (estimate.counting_backend for estimate in estimates if estimate.tokens),
        "chars_fallback",
    )


__all__ = ["ContextRequest", "build_context_request"]
