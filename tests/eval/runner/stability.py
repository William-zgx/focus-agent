"""Offline fixtures for the harness stability eval suite."""

from __future__ import annotations

import json
from typing import Any

from langchain.messages import AIMessage, HumanMessage
from langchain.tools import tool as langchain_tool


def make_harness_stability_model(*_args: Any, **_kwargs: Any) -> Any:
    """Scripted fake model used by the harness_stability dataset."""

    class HarnessStabilityRunnable:
        def __init__(self, allow_tools: bool):
            self.allow_tools = allow_tools

        def with_config(self, _config: Any) -> HarnessStabilityRunnable:
            return self

        def invoke(self, messages: Any) -> AIMessage:
            return harness_stability_response(list(messages), allow_tools=self.allow_tools)

    class HarnessStabilityModel:
        def bind_tools(self, _tools: Any) -> HarnessStabilityRunnable:
            return HarnessStabilityRunnable(allow_tools=True)

        def with_config(self, _config: Any) -> HarnessStabilityRunnable:
            return HarnessStabilityRunnable(allow_tools=False)

    return HarnessStabilityModel()


def harness_stability_response(messages: list[Any], *, allow_tools: bool) -> AIMessage:
    latest_user = _latest_human_text(messages)
    tool_names = _ai_tool_call_names(messages)

    if allow_tools and "lookup" in latest_user and tool_names.count("lookup") < 1:
        return AIMessage(
            content="",
            tool_calls=[{"id": "hs-lookup-1", "name": "lookup", "args": {"query": "bounded"}}],
        )
    if allow_tools and "超时" in latest_user and tool_names.count("web_search") < 1:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "hs-web-1",
                    "name": "web_search",
                    "args": {"query": "timeout fixture"},
                }
            ],
        )
    if allow_tools and "并行拆" in latest_user and tool_names.count("task") < 1:
        return AIMessage(
            content="",
            tool_calls=[{"id": "hs-task-1", "name": "task", "args": {"count": 3}}],
        )

    if "lookup" in latest_user:
        return AIMessage(content="检测到重复 lookup 风险，已停止循环并给出当前可用结论。")
    if "坏 JSON" in latest_user:
        return AIMessage(content="计划下一步：坏 JSON 无法解析时先修复结构，失败则降级为文本计划。")
    if "超时" in latest_user:
        return AIMessage(content="web_search 超时失败，已去重 fallback，建议稍后重试。")
    if "并行拆" in latest_user:
        return AIMessage(content="并行任务已受限制，最多 3 个同时运行。")
    if "不要联网" in latest_user:
        return AIMessage(content="遵循不联网要求，web_search 无法调用，已拒绝该工具请求。")
    if "rollback" in latest_user:
        return AIMessage(content="rollback 后恢复连接，重复 message.delta 已处理。")
    return AIMessage(content="harness stability fixture completed.")


def harness_stability_tools() -> tuple[Any, ...]:
    @langchain_tool
    def lookup(query: str = "") -> str:
        """Deterministic lookup fixture for harness stability evals."""
        return json.dumps({"query": query, "status": "ok"}, ensure_ascii=False)

    @langchain_tool
    def web_search(query: str = "") -> str:
        """Deterministic web search timeout fixture."""
        return json.dumps({"query": query, "error": "timeout"}, ensure_ascii=False)

    @langchain_tool
    def task(count: int = 1) -> str:
        """Deterministic bounded subtask fixture."""
        bounded = min(max(int(count or 1), 1), 3)
        return json.dumps({"requested": count, "started": bounded}, ensure_ascii=False)

    lookup.metadata = {
        "toolset": "workspace",
        "intent_policies": ("workspace_lookup", "execution"),
        "allowed_roles": ("executor", "critic"),
        "max_calls_per_turn": 4,
    }
    web_search.metadata = {
        "toolset": "web",
        "requires_network": True,
        "intent_policies": ("live_web_research", "execution"),
        "allowed_roles": ("planner",),
        "timeout_seconds": 0.01,
        "max_calls_per_turn": 3,
    }
    task.metadata = {
        "toolset": "workspace",
        "parallel_safe": True,
        "intent_policies": ("workspace_lookup", "execution"),
        "allowed_roles": ("executor", "critic"),
        "max_calls_per_turn": 4,
    }
    return (lookup, web_search, task)


def _latest_human_text(messages: list[Any]) -> str:
    for msg in reversed(messages or []):
        if isinstance(msg, HumanMessage):
            return str(msg.content or "")
    return ""


def _ai_tool_call_names(messages: list[Any]) -> list[str]:
    names: list[str] = []
    for msg in messages or []:
        if isinstance(msg, AIMessage):
            for call in getattr(msg, "tool_calls", None) or []:
                names.append(str(call.get("name") or ""))
    return names
