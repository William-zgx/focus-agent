from __future__ import annotations

import re
from typing import Any, Literal

from langchain.messages import ToolMessage


_DIRECT_ANSWER_NOTE = (
    "This turn should be answered directly. Do not call tools, browse the web, inspect files, "
    "or create artifacts unless the user explicitly changes that request."
)


_WORKSPACE_TOOL_NOTE = (
    "This turn may use only local workspace inspection tools. Do not use web tools or artifact-writing tools. "
    "For symbol, function, tool, definition, usage, or location lookups, prefer search_code first with the "
    "most specific query. Use list_files first only when the user asks to browse or enumerate files."
)


_LIVE_WEB_TOOL_NOTE = "This turn may use live web/time tools when needed. Do not inspect local project files unless the user asks."


_BRANCH_ACTION_GUARD_NOTE = (
    "Branch management is executed only through structured Branch Action confirmations. "
    "If the user asks to switch, fork, open, archive, or merge branches, do not claim the branch was created, "
    "opened, archived, merged, or switched unless the runtime has already returned a successful Branch Action "
    "or branch API result. Ask for confirmation or describe the pending action instead."
)


_ToolPolicy = Literal["direct_answer", "workspace_lookup", "live_web_research", "execution"]


_WORKSPACE_TOOL_NAMES = frozenset(
    {
        "list_files",
        "read_file",
        "search_code",
        "codebase_stats",
        "git_status",
        "git_diff",
        "git_log",
        "skills_list",
        "skill_view",
        "artifact_list",
        "artifact_read",
        "conversation_summary",
    }
)


_LIVE_WEB_TOOL_NAMES = frozenset({"web_search", "web_fetch", "current_utc_time"})


_NO_TOOL_INTENT_MARKERS = (
    "不要联网",
    "不用联网",
    "别联网",
    "无需联网",
    "不要搜索",
    "不用搜索",
    "别搜索",
    "不要查",
    "不用查",
    "不用工具",
    "不要用工具",
    "不使用工具",
    "直接回答",
    "直接发给我",
    "只回答",
    "一句话说明",
    "一句话解释",
    "single word",
    "no tools",
    "without tools",
    "do not browse",
    "don't browse",
    "do not search",
    "don't search",
)


_CREATIVE_DIRECT_MARKERS = (
    "写一篇",
    "写一封",
    "帮我写",
    "作文",
    "文案",
    "润色",
    "翻译",
    "改写",
    "总结下面",
    "解释一下",
    "说明什么是",
    "是什么",
    "讲一下",
    "draft",
    "rewrite",
    "translate",
    "summarize",
    "explain",
)


_WORKSPACE_INTENT_MARKERS = (
    "仓库",
    "项目",
    "代码",
    "文件",
    "路径",
    "实现",
    "定义",
    "调用",
    "引用",
    "位置",
    "测试用例",
    "readme",
    "repo",
    "repository",
    "codebase",
    "source",
    "file",
    "function",
    "class",
    "definition",
    "implementation",
    "where is",
    "find usage",
    "search code",
)


_EXPLICIT_WORKSPACE_CONTEXT_MARKERS = (
    "仓库",
    "项目",
    "代码",
    "文件",
    "路径",
    "测试用例",
    "readme",
    "repo",
    "repository",
    "codebase",
    "source",
    "file",
    "function",
    "class",
    "definition",
    "implementation",
    "search code",
)


_CODE_SEARCH_TOOL_INTENT_MARKERS = (
    "定义",
    "调用",
    "引用",
    "位置",
    "使用",
    "工具",
    "函数",
    "类",
    "symbol",
    "function",
    "class",
    "definition",
    "usage",
    "reference",
    "where is",
    "find usage",
)


_FILE_BROWSE_INTENT_MARKERS = (
    "列出文件",
    "有哪些文件",
    "文件列表",
    "目录",
    "list files",
    "browse files",
    "file list",
    "directory",
)


_LIVE_WEB_INTENT_MARKERS = (
    "联网",
    "上网",
    "搜索",
    "查一下",
    "查下",
    "搜一下",
    "最新",
    "今天",
    "现在",
    "当前",
    "实时",
    "新闻",
    "天气",
    "价格",
    "汇率",
    "股价",
    "股票",
    "行情",
    "走势",
    "波动",
    "涨跌",
    "涨跌幅",
    "涨幅",
    "跌幅",
    "收盘价",
    "开盘价",
    "最高价",
    "最低价",
    "成交量",
    "龙头股",
    "个股",
    "板块",
    "a股",
    "港股",
    "美股",
    "财报",
    "基本面",
    "估值",
    "近一",
    "过去",
    "年内",
    "今年",
    "browse",
    "web",
    "search",
    "latest",
    "today",
    "current",
    "now",
    "weather",
    "news",
    "price",
)


_LIVE_WEB_SEARCH_FIRST_MARKERS = (
    "查一下",
    "查下",
    "搜一下",
    "搜索",
    "新闻",
    "价格",
    "股价",
    "股票",
    "龙头股",
    "个股",
    "板块",
    "a股",
    "港股",
    "美股",
    "财报",
    "基本面",
    "估值",
    "波动",
    "走势",
    "行情",
    "涨跌",
    "涨跌幅",
    "涨幅",
    "跌幅",
    "收盘价",
    "开盘价",
    "最高价",
    "最低价",
    "成交量",
    "近一",
    "过去",
    "年内",
    "今年",
    "browse",
    "search",
    "latest",
    "news",
    "price",
)


_EXECUTION_INTENT_MARKERS = (
    "开始修复",
    "修复",
    "实现",
    "改一下",
    "修改",
    "复现",
    "测试",
    "跑一下",
    "运行",
    "启动",
    "构建",
    "提交",
    "推送",
    "部署",
    "fix",
    "implement",
    "change",
    "modify",
    "reproduce",
    "test",
    "run",
    "start",
    "build",
    "commit",
    "push",
    "deploy",
)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _classify_turn_tool_policy(text: str) -> _ToolPolicy:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return "direct_answer"

    has_no_tool_intent = _contains_any(normalized, _NO_TOOL_INTENT_MARKERS)
    if has_no_tool_intent:
        return "direct_answer"

    has_live_web_intent = _contains_any(normalized, _LIVE_WEB_INTENT_MARKERS)
    has_workspace_intent = _contains_any(normalized, _WORKSPACE_INTENT_MARKERS)
    has_explicit_workspace_context = _contains_any(
        normalized,
        _EXPLICIT_WORKSPACE_CONTEXT_MARKERS,
    )

    if _contains_any(normalized, _EXECUTION_INTENT_MARKERS):
        return "execution"
    if has_live_web_intent and (not has_workspace_intent or not has_explicit_workspace_context):
        return "live_web_research"
    if has_workspace_intent:
        return "workspace_lookup"
    if has_live_web_intent:
        return "live_web_research"
    if _contains_any(normalized, _CREATIVE_DIRECT_MARKERS):
        return "direct_answer"
    return "direct_answer"


def _tools_for_policy(policy: _ToolPolicy, tools: list[Any], latest_user: str = "") -> list[Any]:
    if policy == "direct_answer":
        return []
    if policy == "workspace_lookup":
        allowed_names = _WORKSPACE_TOOL_NAMES
        normalized = " ".join(latest_user.strip().split())
        if _contains_any(normalized, _CODE_SEARCH_TOOL_INTENT_MARKERS) and not _contains_any(
            normalized, _FILE_BROWSE_INTENT_MARKERS
        ):
            allowed_names = frozenset({"search_code", "read_file"})
        return [tool for tool in tools if getattr(tool, "name", "") in allowed_names]
    if policy == "live_web_research":
        return [tool for tool in tools if getattr(tool, "name", "") in _LIVE_WEB_TOOL_NAMES]
    return list(tools)


def _workspace_lookup_should_start_with_search(
    text: str, messages: list[Any], tools: list[Any]
) -> bool:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return False
    if any(isinstance(message, ToolMessage) for message in messages):
        return False
    if not any(str(getattr(tool, "name", "")) == "search_code" for tool in tools):
        return False
    return _contains_any(normalized, _CODE_SEARCH_TOOL_INTENT_MARKERS) and not _contains_any(
        normalized,
        _FILE_BROWSE_INTENT_MARKERS,
    )


def _live_web_research_should_start_with_search(
    text: str, messages: list[Any], tools: list[Any]
) -> bool:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return False
    if any(isinstance(message, ToolMessage) for message in messages):
        return False
    if not any(str(getattr(tool, "name", "")) == "web_search" for tool in tools):
        return False
    return _contains_any(normalized, _LIVE_WEB_SEARCH_FIRST_MARKERS)


def _workspace_search_query(text: str) -> str:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?", text)
    seen: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in {"repo", "repository", "codebase", "source", "file", "function", "class"}:
            continue
        if token not in seen:
            seen.append(token)
    if seen:
        return " ".join(seen[:6])
    return text.strip()


def _tool_policy_note(policy: _ToolPolicy) -> str:
    if policy == "direct_answer":
        return _DIRECT_ANSWER_NOTE
    if policy == "workspace_lookup":
        return _WORKSPACE_TOOL_NOTE
    if policy == "live_web_research":
        return _LIVE_WEB_TOOL_NOTE
    return _BRANCH_ACTION_GUARD_NOTE


__all__ = [
    "_BRANCH_ACTION_GUARD_NOTE",
    "_DIRECT_ANSWER_NOTE",
    "_LIVE_WEB_TOOL_NOTE",
    "_WORKSPACE_TOOL_NOTE",
    "_classify_turn_tool_policy",
    "_live_web_research_should_start_with_search",
    "_tool_policy_note",
    "_tools_for_policy",
    "_workspace_lookup_should_start_with_search",
    "_workspace_search_query",
]
