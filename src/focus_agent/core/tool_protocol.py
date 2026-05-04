from __future__ import annotations

import re
from typing import Iterable


TEXTUAL_TOOL_ARTIFACT_MARKERS = (
    "function_calls",
    "invoke name=",
    "<｜dsml｜",
    "<tool_call",
    "<tool_calls",
    "</tool_call",
    "</tool_calls",
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
_XMLISH_TOOL_CALL_RE = re.compile(
    r"(?is)(?:^|[\s<])/?<?function\s*=\s*[a-z_][\w.-]*\s*>|"
    r"<\s*/?\s*parameter\s*=|"
    r"(?:^|[\s<])/?<?parameter\s*=\s*[\w.-]+\s*>"
)
_INTERNAL_PROCESS_NARRATION_RE = re.compile(
    r"(?ims)(?:^|[\n。；;:：])\s*"
    r"(?:我(?:来|先)?(?:帮你|为你)?(?:查询|获取|搜索|查找)|"
    r"先(?:获取|查询|搜索|抓取)|让我(?:先|再)?(?:尝试|查询|搜索|获取|访问|抓取)|"
    r"现在让我|接下来我(?:会|将)?尝试|我(?:会|将|再)?尝试(?:通过)?)"
    r"(?=.{0,160}(?:搜索|查询|访问|获取|抓取|页面|数据|行情|日线|东方财富|数据源|"
    r"web_fetch|web_search|tool|fetch|search|browse|计算))"
)
_INTERNAL_SEARCH_RESULT_NARRATION_RE = re.compile(
    r"(?ims)(?:我已经|我已)(?:从|在).{0,12}搜索结果.{0,80}(?:获取|拿到|掌握|整理)"
)
_INTERNAL_CONTINUATION_LOOP_RE = re.compile(
    r"(?ims)(?=.{0,260}(?:获取|查询|搜索|执行|处理|分析|计划|数据|网页|页面|行情))"
    r"(?:如果(?:你)?(?:没有|无)(?:进一步|额外|其他|特别|新的?)?(?:指示|要求|需求|回复)|"
    r"如无(?:其他|额外|特别|新的?)?(?:要求|指示)|"
    r"当前(?:继续|正在)(?:执行|处理|获取|分析)|"
    r"我将(?:默认)?继续(?:执行|推进|处理)|"
    r"请确认是否继续|如果没有回复|请稍候|正在(?:获取|查询|处理|分析)(?:数据)?)"
)


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
    if _XMLISH_TOOL_CALL_RE.search(lowered):
        return True

    tool_names = _normalized_tool_names(known_tool_names)
    if any(match.group(1).lower() in tool_names for match in _BRACKET_TOOL_MARKER_RE.finditer(lowered)):
        return True

    return bool(
        _INTERNAL_PROCESS_NARRATION_RE.search(lowered)
        or _INTERNAL_SEARCH_RESULT_NARRATION_RE.search(lowered)
        or _INTERNAL_CONTINUATION_LOOP_RE.search(lowered)
    )
