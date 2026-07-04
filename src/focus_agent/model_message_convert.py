"""Cross-provider message conversion utilities.

Inspired by pi/opencode's message-adapter layer, this module converts
chat messages and tool calls between provider wire formats so that a
shared conversation history can be replayed across OpenAI-compatible,
Anthropic, Google Gemini, and OpenAI Responses endpoints.

The converters operate on plain ``dict`` / ``list`` message structures
(as returned by providers or stored in AgentState) rather than on
langchain message objects, so they can be used in streaming middleware,
persistence layers, and test fixtures without pulling in the full SDK.

Supported conversions
---------------------
* Anthropic Messages API  <->  OpenAI Chat Completions
* (Google Gemini and OpenAI Responses are placeholders / pass-through
  for now and will be filled in as those routes are wired up.)

Anthropic thinking blocks
-------------------------
Anthropic's extended thinking feature emits ``{"type": "thinking", ...}``
content blocks. When relaying those messages to OpenAI-compatible
providers we render them as ``<thinking>...</thinking>`` XML tags inside a
text block so reasoning is preserved without confusing the downstream
model. The reverse converter extracts those tags back into structured
thinking blocks when possible.
"""

from __future__ import annotations

import copy
import re
from typing import Any

ProtocolName = str

_THINKING_OPEN_RE = re.compile(r"<thinking>\s*", re.IGNORECASE)
_THINKING_CLOSE_RE = re.compile(r"\s*</thinking>", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def convert_messages_for_provider(
    messages: list[dict[str, Any]],
    source_protocol: ProtocolName,
    target_protocol: ProtocolName,
) -> list[dict[str, Any]]:
    """Convert a list of messages from ``source_protocol`` to ``target_protocol``.

    Parameters
    ----------
    messages:
        Message dicts in the source protocol's native shape. The list is
        deep-copied before conversion so the input is never mutated.
    source_protocol, target_protocol:
        Protocol identifiers matching :data:`ModelProtocol` values (e.g.
        ``"anthropic_messages"``, ``"openai_compatible"``). If the two
        protocols match, messages are returned as a deep copy with no
        conversion applied.

    Returns
    -------
    list[dict[str, Any]]
        Converted messages in the target protocol's native shape.
    """
    if source_protocol == target_protocol:
        return copy.deepcopy(messages)

    converted = copy.deepcopy(messages)
    pair = (source_protocol, target_protocol)
    if pair == ("anthropic_messages", "openai_compatible"):
        return _anthropic_to_openai(converted)
    if pair == ("openai_compatible", "anthropic_messages"):
        return _openai_to_anthropic(converted)
    # Placeholder pairs: future protocols will plug in here.
    if target_protocol == "openai_compatible":
        # Conservative fallback: collapse non-OpenAI messages into a
        # best-effort OpenAI shape by extracting text content.
        return _generic_to_openai_fallback(converted)
    # Unknown conversion path -- return the deep-copied input verbatim
    # rather than raising so callers in streaming paths do not crash.
    return converted


def convert_tool_calls_for_provider(
    tool_calls: list[dict[str, Any]],
    source_protocol: ProtocolName,
    target_protocol: ProtocolName,
) -> list[dict[str, Any]]:
    """Convert tool call objects between provider formats.

    OpenAI tool calls look like::

        {"id": "call_abc", "type": "function",
         "function": {"name": "search", "arguments": "{...}"}}

    Anthropic tool calls are content blocks::

        {"type": "tool_use", "id": "toolu_abc", "name": "search", "input": {...}}
    """
    if source_protocol == target_protocol:
        return copy.deepcopy(tool_calls)

    pair = (source_protocol, target_protocol)
    if pair == ("anthropic_messages", "openai_compatible"):
        return _anthropic_tool_calls_to_openai(tool_calls)
    if pair == ("openai_compatible", "anthropic_messages"):
        return _openai_tool_calls_to_anthropic(tool_calls)
    return copy.deepcopy(tool_calls)


# ---------------------------------------------------------------------------
# Anthropic -> OpenAI
# ---------------------------------------------------------------------------
def _anthropic_to_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        # Map Anthropic roles: "user" and "assistant" exist in both. System
        # in Anthropic is typically sent separately; if it appears in the
        # message list pass it through.
        if isinstance(content, str):
            out.append({"role": _map_role_to_openai(role), "content": content})
            continue
        if isinstance(content, list):
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in content:
                block_type = block.get("type", "text") if isinstance(block, dict) else "text"
                if block_type == "text" and isinstance(block, dict):
                    text_parts.append(str(block.get("text", "")))
                elif block_type == "thinking" and isinstance(block, dict):
                    thinking_text = str(block.get("thinking", ""))
                    if thinking_text:
                        text_parts.append(f"<thinking>\n{thinking_text}\n</thinking>")
                elif block_type == "tool_use" and isinstance(block, dict):
                    tool_calls.append(
                        {
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": _json_dumps_if_needed(block.get("input", {})),
                            },
                        }
                    )
                elif block_type == "tool_result" and isinstance(block, dict):
                    # Anthropic stores tool results as part of a user turn;
                    # emit an OpenAI-style "tool" message separately.
                    result_content = _stringify_tool_result(block.get("content", ""))
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id", ""),
                            "content": result_content,
                        }
                    )
            converted: dict[str, Any] = {"role": _map_role_to_openai(role)}
            if text_parts:
                converted["content"] = "\n".join(text_parts)
            else:
                converted["content"] = ""
            if tool_calls:
                converted["tool_calls"] = tool_calls
            out.append(converted)
        else:
            out.append({"role": _map_role_to_openai(role), "content": str(content) if content is not None else ""})
    return out


def _map_role_to_openai(role: str) -> str:
    normalized = (role or "").strip().lower()
    if normalized in {"assistant", "user", "system", "tool"}:
        return normalized
    return "user"


def _anthropic_tool_calls_to_openai(
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for tc in tool_calls:
        if tc.get("type") == "tool_use":
            result.append(
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": _json_dumps_if_needed(tc.get("input", {})),
                    },
                }
            )
        else:
            result.append(copy.deepcopy(tc))
    return result


# ---------------------------------------------------------------------------
# OpenAI -> Anthropic
# ---------------------------------------------------------------------------
def _openai_to_anthropic(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "tool":
            # OpenAI tool messages become tool_result blocks inside a user turn.
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.get("tool_call_id", ""),
                            "content": str(content) if content is not None else "",
                        }
                    ],
                }
            )
            continue
        if role == "system":
            # Anthropic typically uses a separate system parameter; preserve
            # as a system role for callers that process message lists directly.
            out.append({"role": "system", "content": content})
            continue
        blocks: list[dict[str, Any]] = []
        if isinstance(content, str) and content:
            thinking_match = _extract_thinking_block(content)
            if thinking_match is not None:
                thinking_text, remaining = thinking_match
                if thinking_text:
                    blocks.append(
                        {
                            "type": "thinking",
                            "thinking": thinking_text,
                        }
                    )
                if remaining:
                    blocks.append({"type": "text", "text": remaining})
            else:
                blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            # Already in block form -- deep copy and pass through.
            for block in content:
                if isinstance(block, dict):
                    blocks.append(copy.deepcopy(block))
        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", "") if isinstance(tc, dict) else "",
                        "name": fn.get("name", "") if isinstance(fn, dict) else "",
                        "input": _json_loads_if_needed(
                            fn.get("arguments", "{}") if isinstance(fn, dict) else "{}"
                        ),
                    }
                )
        if not blocks:
            blocks.append({"type": "text", "text": ""})
        out.append({"role": "assistant" if role == "assistant" else "user", "content": blocks})
    return out


def _openai_tool_calls_to_anthropic(
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for tc in tool_calls:
        if tc.get("type") == "function":
            fn = tc.get("function", {})
            result.append(
                {
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": fn.get("name", "") if isinstance(fn, dict) else "",
                    "input": _json_loads_if_needed(
                        fn.get("arguments", "{}") if isinstance(fn, dict) else "{}"
                    ),
                }
            )
        else:
            result.append(copy.deepcopy(tc))
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _extract_thinking_block(content: str) -> tuple[str, str] | None:
    """Split ``<thinking>...</thinking>`` XML tags out of a string.

    Looks for a ``<thinking>`` open tag at the start of ``content`` (with
    optional leading whitespace). If a matching close tag is found, returns
    a ``(thinking_text, remaining_text)`` tuple; the close tag is sought
    anywhere after the open tag (not necessarily at end-of-string). If no
    matching close tag is found, returns ``None`` (so the content is
    treated as plain text rather than a truncated thinking block).
    """
    open_match = _THINKING_OPEN_RE.match(content)
    if not open_match:
        return None
    after_open = content[open_match.end():]
    close_match = _THINKING_CLOSE_RE.search(after_open)
    if not close_match:
        return None
    thinking = after_open[: close_match.start()].strip()
    remaining = after_open[close_match.end():].lstrip()
    return thinking, remaining


def _stringify_tool_result(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content) if content is not None else ""


def _json_dumps_if_needed(value: Any) -> str:
    import json

    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _json_loads_if_needed(value: Any) -> Any:
    import json

    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _generic_to_openai_fallback(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Best-effort flattening of unknown message shapes into OpenAI form."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = str(msg.get("role", "user"))
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(str(block.get("text", "")))
                    elif block.get("type") == "thinking":
                        text_parts.append(
                            f"<thinking>\n{block.get('thinking', '')}\n</thinking>"
                        )
                else:
                    text_parts.append(str(block))
            out.append({"role": _map_role_to_openai(role), "content": "\n".join(text_parts)})
        else:
            out.append(
                {"role": _map_role_to_openai(role), "content": str(content) if content is not None else ""}
            )
    return out


__all__ = [
    "convert_messages_for_provider",
    "convert_tool_calls_for_provider",
]
