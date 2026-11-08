from __future__ import annotations

from copy import deepcopy
from typing import Any

from langchain_anthropic import ChatAnthropic

_DEFAULT_MAX_TOKENS = 16_384
_DEFAULT_THINKING_BUDGET_TOKENS = 4_096
_MAX_CACHE_BREAKPOINTS = 4
_NON_CACHEABLE_MESSAGE_BLOCKS = {"thinking", "redacted_thinking"}


def _has_cache_marker(value: object) -> bool:
    return isinstance(value, dict) and "cache_control" in value


def _existing_cache_breakpoints(value: object) -> int:
    if isinstance(value, dict):
        return int("cache_control" in value) + sum(
            _existing_cache_breakpoints(item) for item in value.values()
        )
    if isinstance(value, list):
        return sum(_existing_cache_breakpoints(item) for item in value)
    return 0


def apply_anthropic_prompt_cache(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy a formatted request and mark stable prefixes plus the moving tail."""
    cached = deepcopy(payload)
    remaining = max(0, _MAX_CACHE_BREAKPOINTS - _existing_cache_breakpoints(cached))

    def mark(block: object) -> None:
        nonlocal remaining
        if remaining <= 0 or not isinstance(block, dict) or _has_cache_marker(block):
            return
        block["cache_control"] = {"type": "ephemeral"}
        remaining -= 1

    tools = cached.get("tools")
    if isinstance(tools, list) and tools:
        mark(tools[-1])

    system = cached.get("system")
    if isinstance(system, str) and system and remaining > 0:
        system = [{"type": "text", "text": system}]
        cached["system"] = system
    if isinstance(system, list) and system:
        mark(system[-1])

    messages = cached.get("messages")
    if isinstance(messages, list) and messages and isinstance(messages[-1], dict):
        message = messages[-1]
        content = message.get("content")
        if isinstance(content, str) and content and remaining > 0:
            content = [{"type": "text", "text": content}]
            message["content"] = content
        if isinstance(content, list):
            for block in reversed(content):
                if (
                    isinstance(block, dict)
                    and block.get("type") not in _NON_CACHEABLE_MESSAGE_BLOCKS
                ):
                    mark(block)
                    break
    return cached


class PromptCachingChatAnthropic(ChatAnthropic):
    def _get_request_payload(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return apply_anthropic_prompt_cache(super()._get_request_payload(*args, **kwargs))


def create_anthropic_chat_model(
    *,
    model: str,
    thinking_enabled: bool = False,
    **kwargs: Any,
) -> ChatAnthropic:
    kwargs.setdefault("max_tokens", _DEFAULT_MAX_TOKENS)
    thinking = kwargs.get("thinking")
    if thinking_enabled and thinking is None:
        budget_tokens = min(_DEFAULT_THINKING_BUDGET_TOKENS, int(kwargs["max_tokens"]) - 1)
        if budget_tokens < 1024:
            raise ValueError("Anthropic thinking requires max_tokens greater than 1024.")
        thinking = {"type": "enabled", "budget_tokens": budget_tokens}
        kwargs["thinking"] = thinking
    if isinstance(thinking, dict) and thinking.get("type") not in {None, "disabled"}:
        kwargs.pop("temperature", None)
    return PromptCachingChatAnthropic(model=model, **kwargs)


__all__ = ["apply_anthropic_prompt_cache", "create_anthropic_chat_model"]
