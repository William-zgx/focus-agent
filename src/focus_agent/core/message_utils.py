"""Leaf helpers for message-type detection and text clipping shared across core and services."""

from __future__ import annotations

from typing import Any


def message_type_name(message: Any) -> str:
    if isinstance(message, dict):
        raw_type = message.get("type") or message.get("role") or message.get("_type") or ""
        message_type = str(raw_type or "").strip().lower()
        return {
            "assistant": "ai",
            "user": "human",
        }.get(message_type, message_type)
    return (
        str(
            getattr(message, "type", message.__class__.__name__.replace("Message", "").lower())
            or ""
        )
        .strip()
        .lower()
    )


def is_ai_message_type(message_type: Any) -> bool:
    return str(message_type or "").strip().lower() in {"ai", "assistant"}


def is_human_message_type(message_type: Any) -> bool:
    return str(message_type or "").strip().lower() in {"human", "user"}


def is_tool_message_type(message_type: Any) -> bool:
    return str(message_type or "").strip().lower() == "tool"


def clip_text(value: Any, max_chars: int) -> str:
    """Collapse whitespace and clip to ``max_chars`` with a trailing ellipsis."""
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"
