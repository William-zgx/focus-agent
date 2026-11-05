"""Lenient value coercion helpers shared across layers (stdlib only)."""

from __future__ import annotations

from typing import Any


def positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def non_negative_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def optional_str(value: Any) -> str | None:
    """Strip ``value``; falsy input (None, "", 0, False) and blank text become None."""

    text = str(value or "").strip()
    return text or None


__all__ = ["float_or_none", "non_negative_int", "optional_str", "positive_int"]
