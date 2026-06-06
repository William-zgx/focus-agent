from __future__ import annotations

import re

_ALL_FILTERABLE_TOOLSETS = ("web", "workspace", "artifact", "memory", "skill")
_WEAK_WORKSPACE_CONTEXT_MARKERS = frozenset({"项目"})


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
    "直接回复",
    "直接返回",
    "只回答",
    "只基于当前问题",
    "只基于当前消息",
    "只基于本轮问题",
    "一句话说明",
    "一句话解释",
    "single word",
    "only answer the current question",
    "only use the current question",
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
    "打开",
    "读取",
    "最新",
    "最近",
    "近期",
    "今天",
    "明天",
    "昨天",
    "本周",
    "这周",
    "现在",
    "当前",
    "实时",
    "新闻",
    "天气",
    "网页",
    "页面",
    "网址",
    "链接",
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
    "热门",
    "比较火",
    "火",
    "流行",
    "browse",
    "fetch",
    "web",
    "search",
    "url",
    "http://",
    "https://",
    "latest",
    "recent",
    "today",
    "tomorrow",
    "yesterday",
    "this week",
    "current",
    "now",
    "weather",
    "news",
    "price",
    "trending",
    "popular",
    "hot",
)


_LIVE_WEB_SEARCH_FIRST_MARKERS = (
    "查一下",
    "查下",
    "搜一下",
    "搜索",
    "最近",
    "近期",
    "本周",
    "这周",
    "今天",
    "明天",
    "昨天",
    "新闻",
    "天气",
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
    "热门",
    "比较火",
    "火",
    "流行",
    "browse",
    "search",
    "latest",
    "recent",
    "today",
    "tomorrow",
    "yesterday",
    "this week",
    "news",
    "weather",
    "price",
    "trending",
    "popular",
    "hot",
)


_LOCAL_WORKSPACE_QUALIFIERS = (
    "当前仓库",
    "这个仓库",
    "本仓库",
    "仓库里",
    "当前项目",
    "这个项目",
    "本项目",
    "项目里",
    "代码里",
    "this repo",
    "current repo",
    "this repository",
    "current repository",
    "this codebase",
    "current codebase",
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


_FRESH_EXTERNAL_INTENT_MARKERS = (
    "最新",
    "最近",
    "近期",
    "今天",
    "明天",
    "昨天",
    "本周",
    "这周",
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
    "热门",
    "比较火",
    "很火",
    "流行",
    "榜单",
    "排行",
    "latest",
    "recent",
    "today",
    "tomorrow",
    "yesterday",
    "this week",
    "current",
    "now",
    "weather",
    "news",
    "price",
    "trending",
    "popular",
    "hot",
)

_BARE_CURRENT_MARKERS = {"当前", "current", "now", "现在"}


_WEB_LOOKUP_ACTION_MARKERS = (
    "联网",
    "上网",
    "搜索",
    "查一下",
    "查下",
    "搜一下",
    "打开",
    "读取",
    "实际检索",
    "引用来源",
    "数据来源",
    "网页",
    "页面",
    "网址",
    "链接",
    "browse",
    "fetch",
    "web",
    "search",
    "url",
    "http://",
    "https://",
)


_ACADEMIC_WEB_LOOKUP_MARKERS = (
    "下载pdf",
    "下载 pdf",
    "获取pdf",
    "获取 pdf",
    "arxiv",
    "doi for",
    "pdf for",
    "find the pdf",
    "get the pdf",
    "paper pdf",
    "pdf link",
)


_RESOURCE_DOWNLOAD_ACTION_MARKERS = (
    "下载",
    "获取",
    "找到",
    "查找",
    "download",
    "get",
    "find",
)


_ACADEMIC_RESOURCE_MARKERS = (
    "论文",
    "arxiv",
    "doi",
    "paper",
    "preprint",
    "pdf",
)


_SYMBOL_LOOKUP_INTENT_MARKERS = (
    "定义",
    "调用",
    "引用",
    "位置",
    "使用",
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
_EN_CONTEXTUAL_CURRENT_RE = re.compile(
    r"(?i)\bcurrent\s+"
    r"(?:user|turn|request|question|prompt|message|instruction|constraint|answer|task|topic|"
    r"context|config|branch|conversation)\b"
)
_CN_CONTEXTUAL_CURRENT_MARKERS = (
    "当前用户",
    "当前轮",
    "当前请求",
    "当前问题",
    "当前提示",
    "当前消息",
    "当前指令",
    "当前约束",
    "当前回答",
    "当前任务",
    "当前主题",
    "当前上下文",
    "当前配置",
    "当前分支",
    "当前对话",
)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(_marker_matches(lowered, marker) for marker in markers)


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


def _contextual_current_hits(text: str) -> tuple[str, ...]:
    hits: list[str] = []
    if _EN_CONTEXTUAL_CURRENT_RE.search(text):
        hits.append("current")
    if any(marker in text for marker in _CN_CONTEXTUAL_CURRENT_MARKERS):
        hits.append("当前")
    return tuple(hits)


def _academic_web_lookup_hits(text: str) -> tuple[str, ...]:
    direct_hits = _matched_markers(text, _ACADEMIC_WEB_LOOKUP_MARKERS)
    action_hits = _matched_markers(text, _RESOURCE_DOWNLOAD_ACTION_MARKERS)
    resource_hits = _matched_markers(text, _ACADEMIC_RESOURCE_MARKERS)
    if action_hits and resource_hits:
        return tuple(dict.fromkeys((*direct_hits, *resource_hits)))
    return direct_hits


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
