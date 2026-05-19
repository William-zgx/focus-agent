from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from langchain.messages import ToolMessage

from ...agent_roles import AgentRole
from ...capabilities.tool_registry import ToolRuntimeMeta
from ...capabilities.tool_router import CapabilityPolicyEngine, ToolIntentPlan
from .policy_intent import (
    is_tool_carryover_confirmation as _is_tool_carryover_confirmation,
)
from .policy_intent import (
    pending_live_web_search_intent as _pending_live_web_search_intent,
)
from .policy_intent import (
    requires_temporal_anchor as _requires_temporal_anchor,
)

_DIRECT_ANSWER_NOTE = (
    "This turn should be answered directly. Do not call tools, browse the web, inspect files, "
    "or create artifacts unless the user explicitly changes that request."
)


_WORKSPACE_TOOL_NOTE = (
    "This turn may use only local workspace inspection tools. Do not use web tools or artifact-writing tools. "
    "For symbol, function, tool, definition, usage, or location lookups, prefer search_code first with the "
    "most specific query. When search_code only identifies a file or line and the user asks for exact nearby "
    "configuration, values, or membership, call read_file on that file before answering. Do not claim that a "
    "local value cannot be confirmed while read_file is available and the relevant file is known. Use list_files "
    "first only when the user asks to browse or enumerate files."
)


_LIVE_WEB_TOOL_NOTE = "This turn may use live web/time tools when needed. Do not inspect local project files unless the user asks."


_BRANCH_ACTION_GUARD_NOTE = (
    "Branch management is executed only through structured Branch Action confirmations. "
    "If the user asks to switch, fork, open, archive, or merge branches, do not claim the branch was created, "
    "opened, archived, merged, or switched unless the runtime has already returned a successful Branch Action "
    "or branch API result. Ask for confirmation or describe the pending action instead."
)


_ToolPolicy = Literal["direct_answer", "workspace_lookup", "live_web_research", "execution"]


@dataclass(frozen=True, slots=True)
class TurnToolExposure:
    policy: _ToolPolicy
    confidence: float
    reason_codes: tuple[str, ...]
    preferred_first_tool: str | None
    allowed_toolsets: tuple[str, ...]
    hard_denied_toolsets: tuple[str, ...]


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
    "火",
    "流行",
    "browse",
    "web",
    "search",
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
    "实际检索",
    "引用来源",
    "数据来源",
    "browse",
    "web",
    "search",
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
    "list",
    "recommend",
    "use",
    "workflow",
)


_SKILL_DISCOVERY_SEARCH_ACTION_MARKERS = tuple(
    marker for marker in _SKILL_DISCOVERY_ACTION_MARKERS if marker not in {"调用", "use"}
)
_CODE_OR_FILE_REFERENCE_RE = re.compile(
    r"(?i)(?:^|[\s`])(?:[\w.-]+/)+[\w.-]+\.(?:py|ts|tsx|js|jsx|md|toml|json|yaml|yml)\b"
    r"|\b[a-z][a-z0-9]+_[a-z0-9_]+\b"
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
    phrase_hits = _matched_markers(text, _SKILL_DISCOVERY_PHRASE_MARKERS)
    subject_hits = _matched_markers(text, _SKILL_DISCOVERY_SUBJECT_MARKERS)
    action_hits = _matched_markers(text, _SKILL_DISCOVERY_ACTION_MARKERS)
    if not phrase_hits and _CODE_OR_FILE_REFERENCE_RE.search(text):
        return ()
    if phrase_hits:
        return tuple(dict.fromkeys((*phrase_hits, *subject_hits, *action_hits)))
    if subject_hits and action_hits:
        return tuple(dict.fromkeys((*subject_hits, *action_hits)))
    return ()


def _skill_discovery_should_prefer_search(text: str) -> bool:
    phrase_hits = _matched_markers(text, _SKILL_DISCOVERY_PHRASE_MARKERS)
    subject_hits = _matched_markers(text, _SKILL_DISCOVERY_SUBJECT_MARKERS)
    search_action_hits = _matched_markers(text, _SKILL_DISCOVERY_SEARCH_ACTION_MARKERS)
    return bool(phrase_hits or (subject_hits and search_action_hits))


def _classify_turn_tool_policy(text: str) -> _ToolPolicy:
    return _classify_turn_tool_exposure(text).policy


def build_tool_intent_plan(
    text: str,
    *,
    active_skill_ids: tuple[str, ...] | list[str] = (),
    pending_tool_action: Mapping[str, Any] | None = None,
) -> ToolIntentPlan:
    normalized = " ".join(text.strip().split())
    pending_web_search = _pending_live_web_search_intent(pending_tool_action)
    if _is_tool_carryover_confirmation(normalized) and pending_web_search is not None:
        query = str(pending_web_search.get("query") or "").strip() or normalized
        reason_codes = [
            "pending_tool_action_carryover",
            "live_web_signal",
            "policy_live_web_research",
        ]
        if _requires_temporal_anchor(query):
            reason_codes.append("temporal_anchor_required")
        return ToolIntentPlan(
            normalized_text=normalized,
            policy="live_web_research",
            confidence=0.9,
            reason_codes=reason_codes,
            preferred_first_tool="web_search",
            preferred_first_args={"query": query},
            allowed_toolsets=["web"],
            denied_toolsets=[toolset for toolset in _ALL_FILTERABLE_TOOLSETS if toolset != "web"],
            source="pending_tool_action",
            temporal_anchor_required="temporal_anchor_required" in reason_codes,
        )

    exposure = _classify_turn_tool_exposure(normalized)
    source = "deterministic"

    no_tool = "explicit_no_tool" in exposure.reason_codes
    skill_ids = {
        str(skill_id).strip().lower() for skill_id in active_skill_ids if str(skill_id).strip()
    }
    if not no_tool and "plan" in skill_ids:
        exposure = _exposure(
            "direct_answer",
            confidence=0.95,
            reason_codes=(*exposure.reason_codes, "skill_plan_direct_answer"),
        )
        source = "skill:plan"
    elif not no_tool and ("review" in skill_ids or "security-review" in skill_ids):
        exposure = _exposure(
            "workspace_lookup",
            confidence=max(exposure.confidence, 0.9),
            reason_codes=(*exposure.reason_codes, "skill_review_workspace"),
            preferred_first_tool=exposure.preferred_first_tool,
        )
        source = "skill:review"
    elif not no_tool and ("research" in skill_ids or "web-research" in skill_ids):
        exposure = _exposure(
            "live_web_research",
            confidence=max(exposure.confidence, 0.9),
            reason_codes=(*exposure.reason_codes, "skill_research_web"),
            preferred_first_tool=exposure.preferred_first_tool or "web_search",
        )
        source = "skill:research"
    elif (
        not no_tool
        and skill_ids
        and not skill_ids <= {"eco"}
        and exposure.policy == "direct_answer"
    ):
        exposure = _exposure(
            "workspace_lookup",
            confidence=max(exposure.confidence, 0.85),
            reason_codes=(*exposure.reason_codes, "active_skill_workspace"),
            preferred_first_tool=exposure.preferred_first_tool,
            allowed_toolsets=("workspace",),
        )
        source = "skill:active"

    reason_codes = list(exposure.reason_codes)
    if exposure.policy == "live_web_research" and _requires_temporal_anchor(normalized):
        reason_codes.append("temporal_anchor_required")

    preferred_first_args = _preferred_first_args(exposure.preferred_first_tool, normalized)
    return ToolIntentPlan(
        normalized_text=normalized,
        policy=exposure.policy,
        confidence=exposure.confidence,
        reason_codes=list(dict.fromkeys(reason_codes)),
        preferred_first_tool=exposure.preferred_first_tool,
        preferred_first_args=preferred_first_args,
        allowed_toolsets=list(exposure.allowed_toolsets),
        denied_toolsets=list(exposure.hard_denied_toolsets),
        source=source,
        temporal_anchor_required="temporal_anchor_required" in reason_codes,
    )


def _turn_tool_exposure_from_intent_plan(intent_plan: ToolIntentPlan) -> TurnToolExposure:
    policy = str(intent_plan.policy or "direct_answer")
    if policy not in {"direct_answer", "workspace_lookup", "live_web_research", "execution"}:
        policy = "direct_answer"
    return TurnToolExposure(
        policy=policy,  # type: ignore[arg-type]
        confidence=float(intent_plan.confidence or 0.55),
        reason_codes=tuple(str(item) for item in intent_plan.reason_codes if str(item)),
        preferred_first_tool=intent_plan.preferred_first_tool,
        allowed_toolsets=tuple(str(item) for item in intent_plan.allowed_toolsets if str(item)),
        hard_denied_toolsets=tuple(str(item) for item in intent_plan.denied_toolsets if str(item)),
    )


def _preferred_first_args(tool_name: str | None, text: str) -> dict[str, Any]:
    if tool_name == "web_search":
        return {"query": text}
    if tool_name == "search_code":
        return {"query": _workspace_search_query(text)}
    if tool_name == "skills_search":
        return {"query": text}
    return {}


def _temporal_live_web_search_args(
    preferred_args: Mapping[str, Any] | None,
    *,
    fallback_query: str,
    current_utc_time: str | None,
) -> dict[str, Any]:
    base_query = ""
    if isinstance(preferred_args, Mapping):
        base_query = str(preferred_args.get("query") or "").strip()
    if not base_query:
        base_query = str(fallback_query or "").strip()
    if not base_query:
        return {}
    if not current_utc_time or not _requires_temporal_anchor(base_query):
        return {"query": base_query}
    anchored_query = _anchor_relative_time_query(base_query, current_utc_time)
    return {"query": anchored_query or base_query}


def _anchor_relative_time_query(query: str, current_utc_time: str) -> str:
    normalized_query = " ".join(str(query or "").strip().split())
    if not normalized_query or "原始查询：" in normalized_query:
        return normalized_query
    anchor = _parse_current_utc_time(current_utc_time)
    if anchor is None:
        return normalized_query
    date_parts = _relative_date_parts(normalized_query, anchor)
    if not date_parts:
        return normalized_query
    location_scope = _extract_location_or_scope(normalized_query)
    metadata = [
        f"原始查询：{normalized_query}",
        f"当前UTC时间：{anchor.isoformat().replace('+00:00', 'Z')}",
        *date_parts,
    ]
    if location_scope:
        metadata.append(f"地点/范围：{location_scope}")
    else:
        metadata.append("地点/范围：见原始查询")
    return f"{normalized_query}（{'; '.join(metadata)}）"


def _parse_current_utc_time(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        match = re.search(r"\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+-]+)?", text)
        if not match:
            return None
        try:
            parsed = datetime.fromisoformat(match.group(0).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _relative_date_parts(query: str, anchor: datetime) -> list[str]:
    lowered = query.lower()
    anchor_date = anchor.date()
    parts: list[str] = []
    if _contains_any(query, ("今天", "today", "现在", "当前", "current", "now")):
        parts.append(f"绝对日期(今天/UTC)：{anchor_date.isoformat()}")
    if _contains_any(query, ("明天", "tomorrow")):
        parts.append(f"绝对日期(明天/UTC)：{(anchor_date + timedelta(days=1)).isoformat()}")
    if _contains_any(query, ("昨天", "yesterday")):
        parts.append(f"绝对日期(昨天/UTC)：{(anchor_date - timedelta(days=1)).isoformat()}")
    if _contains_any(query, ("本周", "这周", "this week")):
        week_start = anchor_date - timedelta(days=anchor_date.weekday())
        week_end = week_start + timedelta(days=6)
        parts.append(f"绝对时间范围(本周/UTC)：{week_start.isoformat()} 至 {week_end.isoformat()}")
    if _contains_any(
        query,
        ("近一周", "最近一周", "过去一周", "last 7 days", "past week"),
    ) or re.search(r"(?<![a-z0-9_])recent(?:ly)?(?![a-z0-9_])", lowered):
        window_start = anchor_date - timedelta(days=6)
        parts.append(f"绝对时间范围(近一周/UTC)：{window_start.isoformat()} 至 {anchor_date.isoformat()}")
    return list(dict.fromkeys(parts))


def _extract_location_or_scope(query: str) -> str:
    patterns = (
        r"(?:今天|明天|昨天|本周|这周|近一周|最近一周|过去一周|最近|近期)\s*([\u4e00-\u9fffA-Za-z][\w\u4e00-\u9fff\s·.-]{1,24}?)(?:天气|新闻|股价|股票|行情|汇率|走势|波动|访问)",
        r"([\u4e00-\u9fff]{2,12})(?:今天|明天|昨天|本周|这周|近一周|最近|近期).{0,12}(?:天气|新闻|股价|股票|行情|汇率|走势|波动|访问)",
        r"(?:访问|到访|访华)([\u4e00-\u9fff]{2,12})",
        r"(?i)\b(?:in|for|at)\s+([a-z][a-z .'-]{1,40}?)(?:\s+(?:today|tomorrow|this week|weather|news|stock|price)|[?.!,]|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, query)
        if not match:
            continue
        value = _clean_location_scope(match.group(1))
        if value:
            return value
    return ""


def _clean_location_scope(value: str) -> str:
    cleaned = re.sub(
        r"^(?:帮我|请|查一下|查下|搜一下|搜索|看一下|看看|一下|有哪个|哪个|哪些|the)\s*",
        "",
        str(value or "").strip(),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，。,.?!？")
    return cleaned[:40]


def _tool_intent_plan_requires_temporal_anchor(intent_plan: ToolIntentPlan) -> bool:
    if str(intent_plan.policy or "") != "live_web_research":
        return False
    reason_codes = {str(item) for item in intent_plan.reason_codes if str(item)}
    if "temporal_anchor_required" in reason_codes:
        return True
    query = ""
    preferred_args = intent_plan.preferred_first_args
    if isinstance(preferred_args, Mapping):
        query = str(preferred_args.get("query") or "").strip()
    return _requires_temporal_anchor(query or str(intent_plan.normalized_text or ""))


def _classify_turn_tool_exposure(text: str) -> TurnToolExposure:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return _exposure(
            "direct_answer",
            confidence=1.0,
            reason_codes=("empty_turn",),
        )

    no_tool_hits = _matched_markers(normalized, _NO_TOOL_INTENT_MARKERS)
    if no_tool_hits:
        return _exposure(
            "direct_answer",
            confidence=1.0,
            reason_codes=("explicit_no_tool",),
        )

    local_context_hits = _matched_markers(normalized, _LOCAL_WORKSPACE_QUALIFIERS)
    explicit_workspace_hits = _matched_markers(normalized, _EXPLICIT_WORKSPACE_CONTEXT_MARKERS)
    workspace_hits = _matched_markers(normalized, _WORKSPACE_INTENT_MARKERS)
    symbol_hits = _matched_markers(normalized, _SYMBOL_LOOKUP_INTENT_MARKERS)
    file_browse_hits = _matched_markers(normalized, _FILE_BROWSE_INTENT_MARKERS)
    live_hits = _matched_markers(normalized, _LIVE_WEB_INTENT_MARKERS)
    fresh_external_hits = _matched_markers(normalized, _FRESH_EXTERNAL_INTENT_MARKERS)
    web_lookup_hits = _matched_markers(normalized, _WEB_LOOKUP_ACTION_MARKERS)
    if not web_lookup_hits:
        live_hits, fresh_external_hits = _filter_bare_current_hits(
            live_hits, fresh_external_hits
        )
    contextual_current_hits = set(_contextual_current_hits(normalized))
    if contextual_current_hits:
        live_hits = tuple(hit for hit in live_hits if hit not in contextual_current_hits)
        fresh_external_hits = tuple(
            hit for hit in fresh_external_hits if hit not in contextual_current_hits
        )
    academic_lookup_hits = _academic_web_lookup_hits(normalized)
    code_reference_hit = bool(_CODE_OR_FILE_REFERENCE_RE.search(normalized))
    if academic_lookup_hits:
        live_hits = tuple(dict.fromkeys((*live_hits, *academic_lookup_hits)))
        web_lookup_hits = tuple(dict.fromkeys((*web_lookup_hits, *academic_lookup_hits)))
    skill_discovery_hits = _skill_discovery_hits(normalized)
    if _contains_any(normalized, ("引用来源", "引用数据来源", "cite source", "cite sources")):
        symbol_hits = tuple(hit for hit in symbol_hits if hit not in {"引用", "reference"})
    execution_hits = _matched_markers(normalized, _EXECUTION_INTENT_MARKERS)
    creative_hits = _matched_markers(normalized, _CREATIVE_DIRECT_MARKERS)
    strong_explicit_workspace_hits = tuple(
        hit for hit in explicit_workspace_hits if hit not in _WEAK_WORKSPACE_CONTEXT_MARKERS
    )
    strong_workspace_hits = tuple(
        dict.fromkeys(
            [
                *local_context_hits,
                *strong_explicit_workspace_hits,
                *symbol_hits,
                *file_browse_hits,
                *(("code_reference",) if code_reference_hit else ()),
            ]
        )
    )

    workspace_score = (
        len(local_context_hits) * 4
        + (4 if code_reference_hit else 0)
        + len(symbol_hits) * 3
        + len(file_browse_hits) * 3
        + len(explicit_workspace_hits) * 2
        + len(workspace_hits)
    )
    live_web_score = len(web_lookup_hits) * 3 + len(fresh_external_hits) * 2 + len(live_hits)
    execution_score = len(execution_hits) * 3
    direct_score = len(creative_hits) * 2

    if local_context_hits:
        current_only_hits = {"当前", "current"} & set(fresh_external_hits)
        live_web_score = max(0, live_web_score - len(current_only_hits) * 3)

    has_workspace_signal = workspace_score > 0
    has_strong_workspace_signal = bool(strong_workspace_hits)
    has_live_web_signal = live_web_score > 0

    reason_codes: list[str] = []
    if creative_hits:
        reason_codes.append("creative_direct_signal")
    if strong_workspace_hits:
        reason_codes.append("local_workspace_context")
    if has_strong_workspace_signal or (workspace_hits and not has_live_web_signal):
        reason_codes.append("workspace_lookup_signal")
    if fresh_external_hits and has_live_web_signal:
        reason_codes.append("fresh_external_signal")
    if (web_lookup_hits or live_hits) and has_live_web_signal:
        reason_codes.append("live_web_signal")
    if execution_hits:
        reason_codes.append("execution_signal")
    if skill_discovery_hits:
        reason_codes.append("skill_discovery_signal")

    if skill_discovery_hits and (
        not execution_score or _skill_discovery_should_prefer_search(normalized)
    ):
        reason_codes.append("policy_workspace_lookup")
        return _exposure(
            "workspace_lookup",
            confidence=max(
                0.78,
                _confidence(len(skill_discovery_hits) * 3, max(workspace_score, live_web_score)),
            ),
            reason_codes=tuple(reason_codes),
            preferred_first_tool="skills_search",
            allowed_toolsets=("skill",),
        )

    if has_strong_workspace_signal and has_live_web_signal:
        reason_codes.append("mixed_live_web_workspace")
        return _exposure(
            "execution",
            confidence=_confidence(
                max(workspace_score, live_web_score), min(workspace_score, live_web_score)
            ),
            reason_codes=tuple(reason_codes),
            preferred_first_tool=_preferred_first_tool(
                normalized,
                policy="execution",
                symbol_hits=symbol_hits,
                file_browse_hits=file_browse_hits,
                web_lookup_hits=web_lookup_hits,
                fresh_external_hits=fresh_external_hits,
            ),
            allowed_toolsets=("web", "workspace"),
            hard_denied_toolsets=("artifact", "memory", "skill"),
        )

    if execution_score and execution_score >= max(workspace_score, live_web_score, direct_score):
        reason_codes.append("policy_execution")
        return _exposure(
            "execution",
            confidence=_confidence(
                execution_score, max(workspace_score, live_web_score, direct_score)
            ),
            reason_codes=tuple(reason_codes),
        )

    if has_live_web_signal and live_web_score >= max(workspace_score, direct_score):
        reason_codes.append("policy_live_web_research")
        return _exposure(
            "live_web_research",
            confidence=_confidence(live_web_score, max(workspace_score, direct_score)),
            reason_codes=tuple(reason_codes),
            preferred_first_tool=_preferred_first_tool(
                normalized,
                policy="live_web_research",
                symbol_hits=symbol_hits,
                file_browse_hits=file_browse_hits,
                web_lookup_hits=web_lookup_hits,
                fresh_external_hits=fresh_external_hits,
            ),
        )

    if has_workspace_signal:
        reason_codes.append("policy_workspace_lookup")
        return _exposure(
            "workspace_lookup",
            confidence=_confidence(workspace_score, max(live_web_score, direct_score)),
            reason_codes=tuple(reason_codes),
            preferred_first_tool=_preferred_first_tool(
                normalized,
                policy="workspace_lookup",
                symbol_hits=symbol_hits,
                file_browse_hits=file_browse_hits,
                web_lookup_hits=web_lookup_hits,
                fresh_external_hits=fresh_external_hits,
            ),
        )

    if direct_score:
        reason_codes.append("policy_direct_answer")
        return _exposure(
            "direct_answer",
            confidence=_confidence(
                direct_score, max(workspace_score, live_web_score, execution_score)
            ),
            reason_codes=tuple(reason_codes),
        )

    return _exposure(
        "direct_answer",
        confidence=0.55,
        reason_codes=("default_direct_answer",),
    )


def _filter_bare_current_hits(
    live_hits: tuple[str, ...],
    fresh_external_hits: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    live_non_current = tuple(hit for hit in live_hits if hit not in _BARE_CURRENT_MARKERS)
    fresh_non_current = tuple(
        hit for hit in fresh_external_hits if hit not in _BARE_CURRENT_MARKERS
    )
    if live_non_current or fresh_non_current:
        return live_hits, fresh_external_hits
    return live_non_current, fresh_non_current


def _exposure(
    policy: _ToolPolicy,
    *,
    confidence: float,
    reason_codes: tuple[str, ...],
    preferred_first_tool: str | None = None,
    allowed_toolsets: tuple[str, ...] | None = None,
    hard_denied_toolsets: tuple[str, ...] | None = None,
) -> TurnToolExposure:
    if allowed_toolsets is None:
        allowed_toolsets = _allowed_toolsets_for_policy(policy)
    if hard_denied_toolsets is None and policy == "direct_answer":
        hard_denied_toolsets = _ALL_FILTERABLE_TOOLSETS
    elif hard_denied_toolsets is None and allowed_toolsets:
        hard_denied_toolsets = tuple(
            toolset for toolset in _ALL_FILTERABLE_TOOLSETS if toolset not in allowed_toolsets
        )
    elif hard_denied_toolsets is None:
        hard_denied_toolsets = ()
    return TurnToolExposure(
        policy=policy,
        confidence=round(max(0.0, min(confidence, 1.0)), 2),
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        preferred_first_tool=preferred_first_tool,
        allowed_toolsets=allowed_toolsets,
        hard_denied_toolsets=hard_denied_toolsets,
    )


def _allowed_toolsets_for_policy(policy: _ToolPolicy) -> tuple[str, ...]:
    if policy == "workspace_lookup":
        return ("workspace",)
    if policy == "live_web_research":
        return ("web",)
    return ()


def _confidence(top_score: int, runner_up_score: int) -> float:
    if top_score <= 0:
        return 0.55
    return 0.6 + min(0.3, top_score * 0.04) + min(0.1, max(0, top_score - runner_up_score) * 0.03)


def _preferred_first_tool(
    text: str,
    *,
    policy: _ToolPolicy,
    symbol_hits: tuple[str, ...],
    file_browse_hits: tuple[str, ...],
    web_lookup_hits: tuple[str, ...],
    fresh_external_hits: tuple[str, ...],
) -> str | None:
    if policy == "workspace_lookup":
        if file_browse_hits and not symbol_hits:
            return "list_files"
        if (
            symbol_hits
            or _CODE_OR_FILE_REFERENCE_RE.search(text)
            or _contains_any(text, _CODE_SEARCH_TOOL_INTENT_MARKERS)
        ):
            return "search_code"
    if policy == "live_web_research":
        if web_lookup_hits or _contains_any(text, _LIVE_WEB_SEARCH_FIRST_MARKERS):
            return "web_search"
    if policy == "execution":
        wants_workspace_first = bool(symbol_hits) and not file_browse_hits
        wants_web_first = bool(web_lookup_hits or fresh_external_hits)
        if wants_workspace_first and not wants_web_first:
            return "search_code"
        if wants_web_first and not wants_workspace_first:
            return "web_search"
    return None


def _tools_for_policy(
    policy: _ToolPolicy,
    tools: list[Any],
    latest_user: str = "",
    *,
    role: AgentRole | str | None = None,
    exposure: TurnToolExposure | None = None,
) -> list[Any]:
    effective_policy = exposure.policy if exposure is not None else policy
    policy_engine = CapabilityPolicyEngine()
    roles = _roles_for_policy(effective_policy, role=role, exposure=exposure)
    candidates = [
        tool
        for tool in tools
        if any(
            policy_engine.tool_allowed(tool, role=effective_role, tool_policy=effective_policy)[0]
            for effective_role in roles
        )
    ]
    if exposure is not None:
        candidates = _filter_tools_by_exposure(candidates, exposure)
    if effective_policy == "workspace_lookup":
        normalized = " ".join(latest_user.strip().split())
        if _contains_any(normalized, _CODE_SEARCH_TOOL_INTENT_MARKERS) and not _contains_any(
            normalized, _FILE_BROWSE_INTENT_MARKERS
        ):
            focused = [
                tool for tool in candidates if "code_search" in _tool_runtime(tool).intent_tags
            ]
            if focused:
                return focused
    return candidates


def _roles_for_policy(
    policy: _ToolPolicy,
    *,
    role: AgentRole | str | None,
    exposure: TurnToolExposure | None,
) -> tuple[AgentRole | str, ...]:
    if role is not None:
        return (role,)
    if exposure is not None and set(exposure.allowed_toolsets) == {"skill"}:
        return (AgentRole.SKILL_SCOUT, AgentRole.PLANNER)
    if (
        exposure is not None
        and policy == "execution"
        and set(exposure.allowed_toolsets) == {"web", "workspace"}
    ):
        return (AgentRole.PLANNER, AgentRole.EXECUTOR)
    return (_default_role_for_policy(policy),)


def _filter_tools_by_exposure(tools: list[Any], exposure: TurnToolExposure) -> list[Any]:
    allowed_toolsets = set(exposure.allowed_toolsets)
    hard_denied_toolsets = set(exposure.hard_denied_toolsets)
    filtered: list[Any] = []
    for tool in tools:
        runtime = _tool_runtime(tool)
        if runtime.toolset in hard_denied_toolsets:
            continue
        if allowed_toolsets and runtime.toolset not in allowed_toolsets:
            continue
        if exposure.policy == "execution" and allowed_toolsets:
            if runtime.side_effect or runtime.requires_workspace_write:
                continue
        filtered.append(tool)
    return filtered


def _tool_runtime(tool: Any) -> ToolRuntimeMeta:
    return ToolRuntimeMeta.from_tool(tool)


def _default_role_for_policy(policy: _ToolPolicy) -> AgentRole:
    if policy == "live_web_research":
        return AgentRole.PLANNER
    return AgentRole.EXECUTOR


def _workspace_lookup_should_start_with_search(
    text: str, messages: list[Any], tools: list[Any], exposure: TurnToolExposure | None = None
) -> bool:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return False
    if any(isinstance(message, ToolMessage) for message in messages):
        return False
    if not any(str(getattr(tool, "name", "")) == "search_code" for tool in tools):
        return False
    if exposure is not None and exposure.preferred_first_tool is not None:
        return exposure.preferred_first_tool == "search_code"
    return _contains_any(normalized, _CODE_SEARCH_TOOL_INTENT_MARKERS) and not _contains_any(
        normalized,
        _FILE_BROWSE_INTENT_MARKERS,
    )


def _live_web_research_should_start_with_search(
    text: str, messages: list[Any], tools: list[Any], exposure: TurnToolExposure | None = None
) -> bool:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return False
    if _has_non_temporal_anchor_tool_result(messages):
        return False
    if not any(str(getattr(tool, "name", "")) == "web_search" for tool in tools):
        return False
    if exposure is not None and exposure.preferred_first_tool is not None:
        return exposure.preferred_first_tool == "web_search"
    return _contains_any(normalized, _LIVE_WEB_SEARCH_FIRST_MARKERS)


def _has_non_temporal_anchor_tool_result(messages: list[Any]) -> bool:
    latest_human_index = -1
    for index, message in enumerate(messages):
        if getattr(message, "type", None) == "human":
            latest_human_index = index

    call_names_by_id: dict[str, str] = {}
    for message in messages[latest_human_index + 1 :]:
        for call in getattr(message, "tool_calls", None) or ():
            if not isinstance(call, Mapping):
                continue
            call_id = str(call.get("id") or "").strip()
            name = str(call.get("name") or "").strip()
            if call_id and name:
                call_names_by_id[call_id] = name
        if isinstance(message, ToolMessage):
            name = call_names_by_id.get(str(message.tool_call_id or "").strip())
            if name != "current_utc_time":
                return True
    return False


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
    "TurnToolExposure",
    "build_tool_intent_plan",
    "_classify_turn_tool_exposure",
    "_classify_turn_tool_policy",
    "_live_web_research_should_start_with_search",
    "_temporal_live_web_search_args",
    "_tool_intent_plan_requires_temporal_anchor",
    "_tool_policy_note",
    "_tools_for_policy",
    "_workspace_lookup_should_start_with_search",
    "_workspace_search_query",
]
