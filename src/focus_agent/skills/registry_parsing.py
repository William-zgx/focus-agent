from __future__ import annotations

from typing import Any

from ..core.types import PromptMode


def _normalize_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _parse_scalar(value: str) -> Any:
    stripped = value.strip()
    if not stripped:
        return ""
    if stripped.startswith("[") and stripped.endswith("]"):
        inner = stripped[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("\"'") for item in inner.split(",") if item.strip()]
    lowered = stripped.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    return stripped.strip("\"'")


def _parse_frontmatter_block(block: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    current_list_key: str | None = None

    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list_key:
            parsed.setdefault(current_list_key, [])
            parsed[current_list_key].append(_parse_scalar(stripped[2:]))
            continue
        if ":" not in line:
            current_list_key = None
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not value:
            parsed[key] = []
            current_list_key = key
            continue
        parsed[key] = _parse_scalar(value)
        current_list_key = None

    return parsed


def _split_frontmatter(raw_text: str) -> tuple[dict[str, Any], str]:
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, raw_text.strip()

    for index in range(1, len(lines)):
        if lines[index].strip() != "---":
            continue
        frontmatter = "\n".join(lines[1:index])
        body = "\n".join(lines[index + 1 :]).strip()
        return _parse_frontmatter_block(frontmatter), body

    return {}, raw_text.strip()


def _coerce_prompt_mode(value: Any) -> PromptMode | None:
    if not value:
        return None
    try:
        return PromptMode(str(value).strip())
    except ValueError:
        return None


__all__ = [
    "_coerce_prompt_mode",
    "_normalize_list",
    "_parse_frontmatter_block",
    "_parse_scalar",
    "_split_frontmatter",
]
