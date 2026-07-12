from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from .agent_loop_helpers import (
    _latest_tool_result_content,
    _latest_turn_has_tool_result,
)
from .policy import _skill_install_name_from_text

_READ_ONLY_SKILL_TOOL_RE = re.compile(
    r"(?<![a-z0-9_])"
    r"(skills_search|skill_view|skills_list|skill_sources|skills_refresh_index)"
    r"(?![a-z0-9_])",
    re.IGNORECASE,
)


def explicit_skill_tools_satisfied(
    text: str,
    messages: list[Any],
    *,
    latest_turn_has_tool_result: Callable[[list[Any], str], bool] = _latest_turn_has_tool_result,
) -> bool:
    requested = {
        match.group(1).lower()
        for match in _READ_ONLY_SKILL_TOOL_RE.finditer(str(text or "").lower())
    }
    return bool(requested) and all(
        latest_turn_has_tool_result(messages, tool_name) for tool_name in requested
    )


def skill_install_args_from_search_result(
    text: str,
    messages: list[Any],
    *,
    latest_tool_result_content: Callable[[list[Any], str], str] = _latest_tool_result_content,
    skill_install_name_from_text: Callable[[str], str] = _skill_install_name_from_text,
) -> dict[str, Any] | None:
    content = latest_tool_result_content(messages, "skills_search")
    if not content:
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        return None
    results = [item for item in raw_results if isinstance(item, dict)]
    if not results:
        return None

    requested_skill = skill_install_name_from_text(text).lower()
    if requested_skill:
        exact = [
            item
            for item in results
            if str(item.get("skill_id") or "").strip().lower() == requested_skill
        ]
        if exact:
            results = exact
        else:
            return None
    if len(results) != 1:
        return None

    result = results[0]
    skill_id = str(result.get("skill_id") or "").strip()
    if not skill_id:
        return None
    args: dict[str, Any] = {"skill_id": skill_id}
    source_id = str(result.get("source_id") or "").strip()
    if source_id:
        args["source_id"] = source_id
    return args


__all__ = [
    "explicit_skill_tools_satisfied",
    "skill_install_args_from_search_result",
]
