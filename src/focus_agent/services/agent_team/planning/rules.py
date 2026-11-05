from __future__ import annotations

from typing import Any

_RESEARCH_MARKERS = (
    "research",
    "plan",
    "guide",
    "strategy",
    "travel",
    "itinerary",
    "compare",
    "分析",
    "调研",
    "规划",
    "方案",
    "攻略",
    "旅行",
    "行程",
    "对比",
)
_DEBUGGING_MARKERS = (
    "debug",
    "diagnose",
    "troubleshoot",
    "root cause",
    "regression",
    "bug",
    "failure",
    "error",
    "crash",
    "排查",
    "定位",
    "诊断",
    "问题",
    "故障",
    "报错",
    "异常",
)
_REVIEW_MARKERS = (
    "review",
    "audit",
    "inspect",
    "critique",
    "assess",
    "风险评审",
    "审查",
    "评审",
    "审核",
)
_WRITING_MARKERS = (
    "write",
    "draft",
    "document",
    "docs",
    "readme",
    "summary",
    "proposal",
    "文档",
    "撰写",
    "编写",
    "总结",
    "说明",
)
_IMPLEMENTATION_MARKERS = (
    "implement",
    "build",
    "fix",
    "refactor",
    "backend",
    "frontend",
    "sdk",
    "api",
    "database",
    "ui",
    "实现",
    "开发",
    "修复",
    "重构",
    "前端",
    "后端",
    "接口",
    "代码",
)
_VERIFICATION_MARKERS = (
    "verify",
    "test",
    "qa",
    "验证",
    "测试",
    "检查",
)


def max_tasks_for_options(options: Any) -> int:
    if options.max_tasks is not None:
        return min(8, max(1, int(options.max_tasks)))
    if is_coarse_plan(options):
        return 3
    if str(options.granularity or "").strip().lower() in {"fine", "detailed", "high"}:
        return 8
    return 6


def is_coarse_plan(options: Any) -> bool:
    return str(options.granularity or "").strip().lower() in {"coarse", "low", "small"}


def contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def infer_focus(goal: str, options: Any) -> str:
    explicit = str(options.focus or "").strip().lower()
    if explicit in {
        "research",
        "debugging",
        "review",
        "implementation",
        "verification",
        "writing",
    }:
        return explicit
    normalized = goal.lower()
    if any(marker in normalized for marker in _DEBUGGING_MARKERS):
        return "debugging"
    if any(marker in normalized for marker in _REVIEW_MARKERS):
        return "review"
    if any(marker in normalized for marker in _WRITING_MARKERS):
        return "writing"
    if any(marker in normalized for marker in _IMPLEMENTATION_MARKERS):
        return "implementation"
    if any(marker in normalized for marker in _VERIFICATION_MARKERS):
        return "verification"
    if any(marker in normalized for marker in _RESEARCH_MARKERS):
        return "research"
    return "research" if contains_cjk(goal) and "攻略" in goal else "implementation"


def focused_goal(goal: str, options: Any) -> str:
    normalized = " ".join(str(goal or "").split())
    focus = " ".join(str(options.focus or "").split())
    if not focus or focus.lower() == "auto":
        return normalized
    return f"{normalized}\n\nFocus: {focus}"


__all__ = [
    "contains_cjk",
    "focused_goal",
    "infer_focus",
    "is_coarse_plan",
    "max_tasks_for_options",
]
