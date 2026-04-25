from __future__ import annotations

import re
from typing import Iterable


TEXTUAL_TOOL_ARTIFACT_MARKERS = (
    "function_calls",
    "invoke name=",
    "<｜dsml｜",
    "<tool_call",
    '"tool_name"',
)

DEFAULT_TEXTUAL_TOOL_NAMES = frozenset(
    {
        "artifact_list",
        "artifact_read",
        "codebase_stats",
        "conversation_summary",
        "current_utc_time",
        "git_diff",
        "git_log",
        "git_status",
        "list_files",
        "read_file",
        "search_code",
        "skills_list",
        "skill_view",
        "web_fetch",
        "web_search",
        "write_text_artifact",
    }
)

_BRACKET_TOOL_MARKER_RE = re.compile(r"(?m)^\s*\[([A-Za-z_][\w.-]*)\]\s*")


def _normalized_tool_names(known_tool_names: Iterable[str] | None = None) -> set[str]:
    names = set(DEFAULT_TEXTUAL_TOOL_NAMES)
    if known_tool_names is not None:
        names.update(str(name).strip().lower() for name in known_tool_names if str(name).strip())
    return names


def looks_like_textual_tool_call_artifact(
    text: object,
    *,
    known_tool_names: Iterable[str] | None = None,
) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    if any(marker in lowered for marker in TEXTUAL_TOOL_ARTIFACT_MARKERS):
        return True

    tool_names = _normalized_tool_names(known_tool_names)
    return any(match.group(1).lower() in tool_names for match in _BRACKET_TOOL_MARKER_RE.finditer(lowered))
