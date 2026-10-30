"""Consistent parsing of environment-style string values.

All helpers strip and casefold input; missing, empty, or unparseable values fall
back to the caller's default instead of raising or silently becoming ``False``.
"""

from __future__ import annotations

from collections.abc import Mapping

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def parse_bool(value: object) -> bool | None:
    """Return True/False for recognised flag values, otherwise None."""

    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().casefold()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return None


def env_bool(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    parsed = parse_bool(env.get(name))
    return default if parsed is None else parsed


def env_int(env: Mapping[str, str], name: str, default: int) -> int:
    text = str(env.get(name) or "").strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        return default


def env_float(env: Mapping[str, str], name: str, default: float) -> float:
    text = str(env.get(name) or "").strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


__all__ = [
    "FALSE_VALUES",
    "TRUE_VALUES",
    "env_bool",
    "env_float",
    "env_int",
    "parse_bool",
]
