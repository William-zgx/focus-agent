from __future__ import annotations

from typing import Any

from ..core.types import PromptMode
from .models import SkillEntrypoint


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
    if stripped.lstrip("-").isdigit():
        try:
            return int(stripped)
        except ValueError:
            pass
    return stripped.strip("\"'")


def _parse_frontmatter_block(block: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    current_list_key: str | None = None
    current_map_key: str | None = None
    current_nested_key: str | None = None
    raw_lines = block.splitlines()

    def next_meaningful_line(start_index: int) -> str:
        for candidate in raw_lines[start_index + 1 :]:
            stripped_candidate = candidate.strip()
            if stripped_candidate and not stripped_candidate.startswith("#"):
                return stripped_candidate
        return ""

    for index, raw_line in enumerate(raw_lines):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent > 0 and stripped.startswith("- ") and current_list_key:
            parsed.setdefault(current_list_key, [])
            parsed[current_list_key].append(_parse_scalar(stripped[2:]))
            continue
        if indent > 0 and current_map_key and ":" in stripped:
            key, raw_value = stripped.split(":", 1)
            key = key.strip()
            value = raw_value.strip()
            current_map = parsed.setdefault(current_map_key, {})
            if not isinstance(current_map, dict):
                continue
            if not value:
                current_map[key] = {}
                current_nested_key = key
                continue
            if indent >= 4 and current_nested_key:
                nested = current_map.setdefault(current_nested_key, {})
                if isinstance(nested, dict):
                    nested[key] = _parse_scalar(value)
                continue
            current_map[key] = _parse_scalar(value)
            current_nested_key = None
            continue
        if ":" not in line:
            current_list_key = None
            current_map_key = None
            current_nested_key = None
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not value:
            if next_meaningful_line(index).startswith("- "):
                parsed[key] = []
                current_list_key = key
                current_map_key = None
            else:
                parsed[key] = {}
                current_map_key = key
                current_list_key = None
            current_nested_key = None
            continue
        parsed[key] = _parse_scalar(value)
        current_list_key = None
        current_map_key = None
        current_nested_key = None

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


def _normalize_entrypoints(value: Any) -> tuple[SkillEntrypoint, ...]:
    if not isinstance(value, dict):
        return ()
    entrypoints: list[SkillEntrypoint] = []
    for raw_name, raw_config in value.items():
        name = str(raw_name or "").strip()
        if not name or not isinstance(raw_config, dict):
            continue
        command = _normalize_list(raw_config.get("command"))
        if not command:
            continue
        dependencies = _normalize_list(raw_config.get("dependencies"))
        timeout_seconds = _coerce_optional_int(raw_config.get("timeout_seconds"))
        memory_mb = _coerce_optional_int(raw_config.get("memory_mb"))
        output_dir_arg = str(raw_config.get("output_dir_arg") or "").strip() or None
        entrypoints.append(
            SkillEntrypoint(
                name=name,
                command=command,
                dependencies=dependencies,
                network=bool(raw_config.get("network", False)),
                timeout_seconds=timeout_seconds,
                memory_mb=memory_mb,
                output_dir_arg=output_dir_arg,
            )
        )
    return tuple(entrypoints)


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "_coerce_prompt_mode",
    "_normalize_entrypoints",
    "_normalize_list",
    "_parse_frontmatter_block",
    "_parse_scalar",
    "_split_frontmatter",
]
