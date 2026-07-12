from __future__ import annotations

import re

_SKILL_DISCOVERY_SUBJECT_MARKERS = (
    "skill",
    "skills",
    "技能",
    "能力",
    "capability",
    "capabilities",
)


_SKILL_DISCOVERY_PHRASE_MARKERS = (
    "可用工具",
    "工具列表",
    "工具清单",
    "可用 skill",
    "可用 skills",
    "可用技能",
    "可用能力",
    "相关能力",
    "内置能力",
    "现成能力",
    "现成流程",
    "已有流程",
    "现有流程",
    "available tool",
    "available tools",
    "available skill",
    "available skills",
    "available capability",
    "available capabilities",
    "skill catalog",
    "skill list",
    "tool catalog",
    "tool list",
    "capability catalog",
    "capability list",
)


_SKILL_DISCOVERY_ACTION_MARKERS = (
    "安装",
    "装一下",
    "添加",
    "加入",
    "使用",
    "启用",
    "加载",
    "采用",
    "搜索",
    "查一下",
    "查下",
    "查找",
    "找到",
    "找",
    "有没有",
    "有哪些",
    "列出",
    "推荐",
    "适合",
    "现成",
    "调用",
    "search",
    "find",
    "discover",
    "install",
    "add",
    "list",
    "recommend",
    "use",
    "workflow",
)
_SKILL_EXECUTION_ACTION_MARKERS = (
    "使用",
    "启用",
    "加载",
    "采用",
    "调用",
    "use",
    "activate",
    "load",
    "apply",
    "invoke",
)
_SKILL_TASK_EXECUTION_MARKERS = (
    "看一下",
    "看一看",
    "查看",
    "查询",
    "分析",
    "处理",
    "获取",
    "拉取",
    "运行",
    "执行",
    "计算",
    "比较",
    "生成",
    "排查",
    "活动情况",
    "analyze",
    "fetch",
    "get",
    "run",
    "execute",
    "query",
    "check",
    "compare",
    "generate",
)
_SKILL_INSTALL_ACTION_MARKERS = (
    "安装",
    "装一下",
    "添加",
    "加入",
    "install",
    "add",
)


_SKILL_DISCOVERY_SEARCH_ACTION_MARKERS = tuple(
    marker
    for marker in _SKILL_DISCOVERY_ACTION_MARKERS
    if marker not in set(_SKILL_EXECUTION_ACTION_MARKERS)
)
_SKILL_DISCOVERY_TOOL_MARKERS = (
    "skills_search",
    "skills_list",
    "skill_view",
    "skill_install",
    "skills_refresh_index",
    "skill_sources",
)
_CODE_FILE_REFERENCE_RE = re.compile(
    r"(?i)(?:^|[\s`])(?:[\w.-]+/)+[\w.-]+\.(?:py|ts|tsx|js|jsx|md|toml|json|yaml|yml)\b"
)
_CODE_OR_FILE_REFERENCE_RE = re.compile(
    _CODE_FILE_REFERENCE_RE.pattern + r"|\b[a-z][a-z0-9]+_[a-z0-9_]+\b"
)


def _marker_matches(lowered_text: str, marker: str) -> bool:
    normalized_marker = marker.strip().lower()
    if not normalized_marker:
        return False
    if re.fullmatch(r"[a-z0-9]+(?:\s+[a-z0-9]+)*", normalized_marker):
        pattern = (
            r"(?<![a-z0-9_])"
            + r"\s+".join(re.escape(part) for part in normalized_marker.split())
            + r"(?![a-z0-9_])"
        )
        return re.search(pattern, lowered_text) is not None
    return normalized_marker in lowered_text


def _matched_markers(text: str, markers: tuple[str, ...]) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(marker for marker in markers if _marker_matches(lowered, marker))


def _skill_discovery_hits(text: str) -> tuple[str, ...]:
    tool_hits = _matched_markers(text, _SKILL_DISCOVERY_TOOL_MARKERS)
    phrase_hits = _matched_markers(text, _SKILL_DISCOVERY_PHRASE_MARKERS)
    subject_hits = _matched_markers(text, _SKILL_DISCOVERY_SUBJECT_MARKERS)
    action_hits = _matched_markers(text, _SKILL_DISCOVERY_ACTION_MARKERS)
    if not phrase_hits and _CODE_FILE_REFERENCE_RE.search(text):
        return ()
    if not phrase_hits and not tool_hits and _CODE_OR_FILE_REFERENCE_RE.search(text):
        return ()
    if tool_hits:
        return tuple(dict.fromkeys((*tool_hits, *phrase_hits, *subject_hits, *action_hits)))
    if phrase_hits:
        return tuple(dict.fromkeys((*phrase_hits, *subject_hits, *action_hits)))
    if subject_hits and action_hits:
        return tuple(dict.fromkeys((*subject_hits, *action_hits)))
    return ()


def _skill_install_hits(text: str) -> tuple[str, ...]:
    tool_hits = _matched_markers(text, ("skill_install",))
    action_hits = _matched_markers(text, _SKILL_INSTALL_ACTION_MARKERS)
    subject_hits = _matched_markers(text, _SKILL_DISCOVERY_SUBJECT_MARKERS)
    if not action_hits and not tool_hits:
        return ()
    if _CODE_FILE_REFERENCE_RE.search(text):
        return ()
    if tool_hits:
        return tuple(dict.fromkeys((*tool_hits, *action_hits, *subject_hits)))
    if action_hits and subject_hits:
        return tuple(dict.fromkeys((*action_hits, *subject_hits)))
    return ()


def _skill_discovery_preferred_tool(text: str) -> str | None:
    tool_hits = _matched_markers(text, _SKILL_DISCOVERY_TOOL_MARKERS)
    if "skills_search" in tool_hits:
        return "skills_search"
    for tool_name in (
        "skill_view",
        "skills_list",
        "skill_sources",
        "skills_refresh_index",
        "skill_install",
    ):
        if tool_name in tool_hits:
            return tool_name
    if _skill_discovery_should_prefer_search(text):
        return "skills_search"
    return None


def _skill_discovery_should_prefer_search(text: str) -> bool:
    tool_hits = _matched_markers(text, _SKILL_DISCOVERY_TOOL_MARKERS)
    if "skills_search" in tool_hits:
        return True
    phrase_hits = _matched_markers(text, _SKILL_DISCOVERY_PHRASE_MARKERS)
    subject_hits = _matched_markers(text, _SKILL_DISCOVERY_SUBJECT_MARKERS)
    search_action_hits = _matched_markers(text, _SKILL_DISCOVERY_SEARCH_ACTION_MARKERS)
    return bool(phrase_hits or (subject_hits and search_action_hits))


def _active_skill_execution_hits(text: str) -> tuple[str, ...]:
    if _matched_markers(text, _SKILL_DISCOVERY_TOOL_MARKERS):
        return ()
    action_hits = _matched_markers(text, _SKILL_EXECUTION_ACTION_MARKERS)
    subject_hits = _matched_markers(text, _SKILL_DISCOVERY_SUBJECT_MARKERS)
    task_hits = _matched_markers(text, _SKILL_TASK_EXECUTION_MARKERS)
    if action_hits and subject_hits and task_hits:
        return tuple(dict.fromkeys((*action_hits, *subject_hits, *task_hits)))
    return ()


def _active_skill_task_execution_hits(text: str) -> tuple[str, ...]:
    if _matched_markers(text, _SKILL_DISCOVERY_TOOL_MARKERS):
        return ()
    return _matched_markers(text, _SKILL_TASK_EXECUTION_MARKERS)
