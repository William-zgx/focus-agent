from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any, Literal

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from ..agent_roles import build_role_route_plan
from ..agent_delegation import (
    build_agent_delegation_plan,
    build_failure_records,
    build_model_route_decision,
    build_review_queue,
)
from ..agent_context_engineering import build_context_engineering_decision
from ..agent_task_ledger import (
    apply_critic_retry_tasks,
    build_agent_task_ledger,
    build_delegated_artifacts,
    evaluate_critic_gate,
    synthesize_delegated_artifacts,
)
from ..capabilities import ToolRegistry, build_tool_registry
from ..capabilities.tool_runtime import (
    ToolExecutionInput,
    ToolResultCacheStore,
    build_cache_scope_key,
    build_tool_error_message,
    execute_tool_calls,
)
from ..capabilities.tool_router import build_tool_route_plan, infer_tool_router_role
from ..config import Settings
from ..core.context_policy import (
    apply_prompt_budget_guard,
    assemble_context as build_context_slice,
)
from ..core.request_context import RequestContext
from ..core.state import AgentState
from ..core.tool_protocol import looks_like_textual_tool_call_artifact
from ..core.types import ContextBudget, Plan, PlanStep, PromptMode, ReflectionVerdict
from ..memory import (
    MemoryExtractor,
    MemoryPolicy,
    MemoryRetriever,
    MemoryWriteRequest,
    MemoryWriter,
    render_memory_block,
)
from ..model_registry import create_chat_model, default_thinking_enabled, supports_thinking_mode
from ..skills import SkillRegistry

_MAX_CONSECUTIVE_TOOL_CALL_ROUNDS = 2
_TOOL_EXHAUSTION_NOTE = (
    "You have enough tool results for this turn. Do not call more tools. "
    "Answer the user directly using the information already gathered, and state any uncertainty plainly."
)
_DIRECT_ANSWER_NOTE = (
    "This turn should be answered directly. Do not call tools, browse the web, inspect files, "
    "or create artifacts unless the user explicitly changes that request."
)
_WORKSPACE_TOOL_NOTE = (
    "This turn may use only local workspace inspection tools. Do not use web tools or artifact-writing tools. "
    "For symbol, function, tool, definition, usage, or location lookups, prefer search_code first with the "
    "most specific query. Use list_files first only when the user asks to browse or enumerate files."
)
_LIVE_WEB_TOOL_NOTE = (
    "This turn may use live web/time tools when needed. Do not inspect local project files unless the user asks."
)
_TOOL_CALL_PROTOCOL_REPAIR_NOTE = (
    "If you need a tool, emit a real tool call through the tool-calling interface. "
    "Do not write DSML tags, XML, or function-call payloads into the assistant text. "
    "If no tool is needed, answer directly in natural language."
)
_TOOL_CALL_MARKUP_REPAIR_NOTE = (
    "Do not emit tool-call markup, XML, JSON function-call payloads, or DSML tags. "
    "Write only the final user-facing answer in natural language."
)
_TOOL_CALL_LAST_RESORT_NOTE = (
    "The previous draft still contained internal tool-call markup. "
    "Do not call more tools. Using only the information already gathered in this conversation, "
    "write a concise final answer for the user in natural language."
)
_TOOL_CALL_REPAIR_FALLBACK_TEXT = (
    "我已经拿到工具结果，但还没有足够可用的信息形成完整结论。请稍后重试，或换一个更稳定的模型。"
)
_TOOL_RESULT_SYNTHESIS_NOTE = (
    "You are writing the final user-facing answer after tool use. Do not call tools. "
    "Use only the tool observations provided below. If the user wrote Chinese, answer in Chinese. "
    "Do not mention formatting failures or internal retries. State uncertainty plainly, and include "
    "dates, numbers, and source names when available."
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
_REASONING_MESSAGE_BLOCK_TYPES = frozenset(
    {"reasoning", "reasoning_delta", "reasoning_content", "reasoningcontent", "thinking", "thinking_delta"}
)
_TOOL_MESSAGE_BLOCK_TYPES = frozenset(
    {"tool_call", "tool_call_chunk", "server_tool_call", "server_tool_call_chunk"}
)

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
    "波动",
    "走势",
    "行情",
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


def _has_tool_calls(message: Any) -> bool:
    return bool(getattr(message, "tool_calls", None))


def _find_trailing_tool_span_start(messages: list[Any]) -> int | None:
    if not messages:
        return None

    index = len(messages) - 1
    while index >= 0 and isinstance(messages[index], ToolMessage):
        index -= 1

    if index < 0:
        return None
    if _has_tool_calls(messages[index]):
        return index
    return None


def _collapse_unanswered_trailing_humans(messages: list[Any]) -> list[Any]:
    if len(messages) < 2:
        return messages

    tail_start = len(messages)
    index = len(messages) - 1
    while index >= 0 and isinstance(messages[index], HumanMessage):
        tail_start = index
        index -= 1

    trailing_human_count = len(messages) - tail_start
    if trailing_human_count <= 1:
        return messages
    return [*messages[:tail_start], messages[-1]]


def _messages_for_model(state: AgentState) -> list[Any]:
    recent_messages = list(state.get("recent_messages") or [])
    messages = list(state.get("messages", []) or [])
    trailing_tool_span_start = _find_trailing_tool_span_start(messages)
    if trailing_tool_span_start is None:
        selected = _collapse_unanswered_trailing_humans(recent_messages or messages)
    else:
        selected = _collapse_unanswered_trailing_humans([*recent_messages, *messages[trailing_tool_span_start:]])
    return [_sanitize_assistant_tool_call_message(message) for message in selected]


def _count_tool_call_rounds_since_latest_human(messages: list[Any]) -> int:
    rounds = 0
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            rounds += 1
    return rounds


def _should_force_tool_free_answer(messages: list[Any]) -> bool:
    if not messages or not isinstance(messages[-1], ToolMessage):
        return False
    return _count_tool_call_rounds_since_latest_human(messages) >= _MAX_CONSECUTIVE_TOOL_CALL_ROUNDS


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _stringify_message_block(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "".join(_stringify_message_block(item) for item in value)
    if isinstance(value, dict):
        for key in (
            "text",
            "content",
            "value",
            "reasoning_content",
            "reasoningcontent",
            "reasoning",
            "summary",
        ):
            if value.get(key) is not None:
                return _stringify_message_block(value[key])
        return ""
    return str(value)


def _sanitize_assistant_tool_call_message(message: Any) -> Any:
    if not isinstance(message, AIMessage) or not getattr(message, "tool_calls", None):
        return message
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return message

    visible_parts: list[str] = []
    reasoning_parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            if block.strip():
                visible_parts.append(block)
            continue
        if not isinstance(block, dict):
            text = _stringify_message_block(block).strip()
            if text:
                visible_parts.append(text)
            continue
        block_type = str(block.get("type") or "").strip().lower()
        if block_type in _REASONING_MESSAGE_BLOCK_TYPES:
            text = _stringify_message_block(block).strip()
            if text:
                reasoning_parts.append(text)
            continue
        if block_type in _TOOL_MESSAGE_BLOCK_TYPES:
            continue
        text = _stringify_message_block(block).strip()
        if text:
            visible_parts.append(text)

    additional_kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
    if reasoning_parts and not additional_kwargs.get("reasoning_content"):
        additional_kwargs["reasoning_content"] = "".join(reasoning_parts)

    return AIMessage(
        content="".join(visible_parts).strip(),
        additional_kwargs=additional_kwargs,
        response_metadata=dict(getattr(message, "response_metadata", {}) or {}),
        name=getattr(message, "name", None),
        id=getattr(message, "id", None),
        tool_calls=list(getattr(message, "tool_calls", []) or []),
        invalid_tool_calls=list(getattr(message, "invalid_tool_calls", []) or []),
        usage_metadata=getattr(message, "usage_metadata", None),
    )


def _thinking_mode_requires_reasoning_content(
    *,
    model_id: str,
    thinking_mode: str,
    settings: Settings,
) -> bool:
    normalized = str(thinking_mode or "").strip().lower()
    if normalized == "disabled":
        return False
    if normalized == "enabled":
        return supports_thinking_mode(model_id, settings=settings)
    return default_thinking_enabled(model_id, settings=settings)


def _ensure_reasoning_content_for_tool_call_history(
    messages: list[Any],
    *,
    model_id: str,
    thinking_mode: str,
    settings: Settings,
) -> list[Any]:
    if not _thinking_mode_requires_reasoning_content(
        model_id=model_id,
        thinking_mode=thinking_mode,
        settings=settings,
    ):
        return messages

    fixed: list[Any] = []
    for message in messages:
        if not isinstance(message, AIMessage) or not getattr(message, "tool_calls", None):
            fixed.append(message)
            continue

        additional_kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
        if _stringify_message_block(additional_kwargs.get("reasoning_content")).strip():
            fixed.append(message)
            continue

        additional_kwargs["reasoning_content"] = (
            "Tool-call reasoning was preserved for the provider protocol."
        )
        fixed.append(
            AIMessage(
                content=getattr(message, "content", ""),
                additional_kwargs=additional_kwargs,
                response_metadata=dict(getattr(message, "response_metadata", {}) or {}),
                name=getattr(message, "name", None),
                id=getattr(message, "id", None),
                tool_calls=list(getattr(message, "tool_calls", []) or []),
                invalid_tool_calls=list(getattr(message, "invalid_tool_calls", []) or []),
                usage_metadata=getattr(message, "usage_metadata", None),
            )
        )
    return fixed


def _known_tool_names(available_tools: list[Any] | tuple[Any, ...] | None = None) -> set[str]:
    return {
        str(getattr(tool, "name", "")).strip()
        for tool in available_tools or []
        if str(getattr(tool, "name", "")).strip()
    }


def _looks_like_textual_tool_call_artifact(
    message: Any,
    *,
    known_tool_names: list[str] | set[str] | tuple[str, ...] | None = None,
) -> bool:
    return looks_like_textual_tool_call_artifact(
        _message_text(message),
        known_tool_names=known_tool_names,
    )


def _latest_human_message_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return _message_text(message)
    return ""


def _latest_final_ai_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            return _message_text(message)
    return ""


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

    if _contains_any(normalized, _EXECUTION_INTENT_MARKERS):
        return "execution"
    if _contains_any(normalized, _WORKSPACE_INTENT_MARKERS):
        return "workspace_lookup"
    if _contains_any(normalized, _LIVE_WEB_INTENT_MARKERS):
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
        if (
            _contains_any(normalized, _CODE_SEARCH_TOOL_INTENT_MARKERS)
            and not _contains_any(normalized, _FILE_BROWSE_INTENT_MARKERS)
        ):
            allowed_names = frozenset({"search_code", "read_file"})
        return [tool for tool in tools if getattr(tool, "name", "") in allowed_names]
    if policy == "live_web_research":
        return [tool for tool in tools if getattr(tool, "name", "") in _LIVE_WEB_TOOL_NAMES]
    return list(tools)


def _workspace_lookup_should_start_with_search(text: str, messages: list[Any], tools: list[Any]) -> bool:
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


def _live_web_research_should_start_with_search(text: str, messages: list[Any], tools: list[Any]) -> bool:
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


def _context_budget_from_state(state: AgentState) -> ContextBudget:
    value = state.get("context_budget")
    if isinstance(value, ContextBudget):
        budget = value
    elif isinstance(value, dict):
        budget = ContextBudget.model_validate(value)
    else:
        budget = ContextBudget()
    selected_model = str(state.get("selected_model") or "").strip()
    if budget.tokenizer_id or not selected_model:
        return budget
    return budget.model_copy(update={"tokenizer_id": selected_model})


def _tool_policy_note(policy: _ToolPolicy) -> str:
    if policy == "direct_answer":
        return _DIRECT_ANSWER_NOTE
    if policy == "workspace_lookup":
        return _WORKSPACE_TOOL_NOTE
    if policy == "live_web_research":
        return _LIVE_WEB_TOOL_NOTE
    return ""


def _truncate_inline(value: Any, *, max_chars: int = 180) -> str:
    text = " ".join(str(value).split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1]}…"


def _latest_turn_messages(messages: list[Any]) -> list[Any]:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index:]
    return messages


def _fallback_answer_from_tool_results(prompt_messages: list[Any]) -> str:
    snippets = _tool_result_snippets(prompt_messages)
    if not snippets:
        return _TOOL_CALL_REPAIR_FALLBACK_TEXT
    unique_snippets = list(dict.fromkeys(snippets))
    return "我先根据已拿到的工具结果给出一个保守整理：\n" + "\n".join(unique_snippets[:10])


def _tool_call_args_summary(args: Any) -> str:
    if not isinstance(args, dict) or not args:
        return ""
    preferred = []
    for key in ("query", "url", "path", "symbol", "ticker"):
        value = args.get(key)
        if value:
            preferred.append(f"{key}={_truncate_inline(value, max_chars=80)}")
    if preferred:
        return ", ".join(preferred[:3])
    return _truncate_inline(json.dumps(args, ensure_ascii=False, default=str), max_chars=120)


def _tool_runtime_summary(message: ToolMessage) -> str:
    artifact = getattr(message, "artifact", None)
    runtime = artifact.get("runtime") if isinstance(artifact, dict) else None
    if not isinstance(runtime, dict):
        return ""
    parts: list[str] = []
    if runtime.get("cache_hit"):
        parts.append("cache_hit")
    if runtime.get("fallback_used"):
        fallback_group = runtime.get("fallback_group")
        parts.append(f"fallback={fallback_group}" if fallback_group else "fallback")
    if runtime.get("duration_ms") is not None:
        parts.append(f"{float(runtime.get('duration_ms') or 0):.0f}ms")
    return f" ({', '.join(parts)})" if parts else ""


def _tool_observation_summary(payload: Any, raw: str) -> str:
    if isinstance(payload, dict):
        for key in ("answer", "summary", "reference", "error", "path", "query"):
            value = payload.get(key)
            if value:
                return _truncate_inline(value)
        results = payload.get("results")
        if isinstance(results, list) and results:
            result = results[0]
            if isinstance(result, dict):
                title = str(result.get("title") or "").strip()
                url = str(result.get("url") or result.get("ref") or "").strip()
                content = str(result.get("content") or result.get("snippet") or result.get("line") or "").strip()
                return _truncate_inline(" ".join(part for part in (title, url, content) if part))
    return _truncate_inline(raw)


def _tool_result_snippets(prompt_messages: list[Any]) -> list[str]:
    snippets: list[str] = []
    pending_calls: dict[str, dict[str, Any]] = {}
    for message in _latest_turn_messages(prompt_messages):
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", None) or []:
                if not isinstance(call, dict):
                    continue
                call_id = str(call.get("id") or "")
                if not call_id:
                    continue
                pending_calls[call_id] = {
                    "name": str(call.get("name") or "tool"),
                    "args": dict(call.get("args") or {}),
                }
            continue
        if not isinstance(message, ToolMessage):
            continue
        raw = _message_text(message)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None

        call_id = str(getattr(message, "tool_call_id", "") or "")
        call = pending_calls.pop(call_id, None)
        if call is not None:
            args_summary = _tool_call_args_summary(call.get("args"))
            status = str(getattr(message, "status", "success") or "success")
            runtime_summary = _tool_runtime_summary(message)
            observation = _tool_observation_summary(payload, raw)
            arg_block = f"({args_summary})" if args_summary else ""
            snippets.append(
                f"- 工具 {call['name']}{arg_block} 返回 {status}{runtime_summary}: {observation}"
            )

        if isinstance(payload, dict):
            query = payload.get("query")
            if query:
                snippets.append(f"- 查询：{_truncate_inline(query)}")
            answer = payload.get("answer")
            if answer:
                snippets.append(f"- {_truncate_inline(answer)}")
            summary = payload.get("summary")
            if summary:
                snippets.append(f"- {_truncate_inline(summary)}")
            reference = payload.get("reference")
            if reference:
                snippets.append(f"- {_truncate_inline(reference)}")
            refs = payload.get("refs")
            if isinstance(refs, list):
                for ref in refs[:8]:
                    if ref:
                        snippets.append(f"- 来源：{_truncate_inline(ref)}")
            results = payload.get("results")
            if isinstance(results, list):
                for result in results[:8]:
                    if not isinstance(result, dict):
                        continue
                    path = result.get("path")
                    line_number = result.get("line_number")
                    line = result.get("line")
                    if path and line_number:
                        snippets.append(f"- {path}:{line_number} {_truncate_inline(line)}")
                    elif path:
                        snippets.append(f"- {path} {_truncate_inline(line or result)}")
                    else:
                        title = str(result.get("title") or "").strip()
                        url = str(result.get("url") or "").strip()
                        ref = str(result.get("ref") or "").strip()
                        content = str(result.get("content") or result.get("snippet") or "").strip()
                        result_summary = " ".join(part for part in [title, url or ref, content] if part)
                        if result_summary:
                            snippets.append(f"- {_truncate_inline(result_summary)}")
            path = payload.get("path")
            if path and not any(str(path) in snippet for snippet in snippets):
                line_hint = ""
                start_line = payload.get("start_line")
                end_line = payload.get("end_line")
                if start_line and end_line:
                    line_hint = f":{start_line}-{end_line}"
                snippets.append(f"- {path}{line_hint}")
        elif raw:
            snippets.append(f"- {_truncate_inline(raw)}")

    return list(dict.fromkeys(snippets))


def _tool_result_synthesis_prompt(source_messages: list[Any]) -> list[Any]:
    latest_user = _latest_human_message_text(source_messages) or "请整理本轮工具结果。"
    snippets = _tool_result_snippets(source_messages)
    digest = "\n".join(snippets[:12]) or _TOOL_CALL_REPAIR_FALLBACK_TEXT
    return [
        SystemMessage(content=_TOOL_RESULT_SYNTHESIS_NOTE),
        HumanMessage(content=f"用户问题：{latest_user}\n\n本轮工具轨迹与工具结果：\n{digest}\n\n请直接给出最终答复。"),
    ]


def _has_tool_result_messages(prompt_messages: list[Any]) -> bool:
    return any(isinstance(message, ToolMessage) for message in prompt_messages)


def _tool_result_fallback_message(prompt_messages: list[Any]) -> AIMessage:
    return AIMessage(content=_fallback_answer_from_tool_results(prompt_messages))


def _invoke_tool_result_synthesis(
    model: Any,
    source_messages: list[Any],
    *,
    known_tool_names: set[str] | None = None,
) -> Any | None:
    invoke = getattr(model, "invoke", None)
    if not callable(invoke):
        return None
    try:
        response = invoke(_tool_result_synthesis_prompt(source_messages))
    except Exception:
        return None
    if getattr(response, "tool_calls", None):
        return None
    if not _message_text(response).strip():
        return None
    if _looks_like_textual_tool_call_artifact(response, known_tool_names=known_tool_names):
        return None
    return response


def _invoke_with_tool_result_fallback(
    model: Any,
    prompt_messages: list[Any],
    *,
    fallback_messages: list[Any] | None = None,
    known_tool_names: set[str] | None = None,
) -> Any:
    try:
        return model.invoke(prompt_messages)
    except Exception:
        source_messages = fallback_messages or prompt_messages
        if _has_tool_result_messages(source_messages):
            synthesized = _invoke_tool_result_synthesis(
                model,
                source_messages,
                known_tool_names=known_tool_names,
            )
            if synthesized is not None:
                return synthesized
            return _tool_result_fallback_message(source_messages)
        raise


def _repair_textual_tool_call_response(
    *,
    response: Any,
    prompt_messages: list[Any],
    fallback_messages: list[Any] | None = None,
    context_budget: ContextBudget,
    selected_model: str,
    selected_thinking_mode: str,
    available_tools: list[Any],
    model_for,
    model_with_tools_for,
) -> Any:
    known_names = _known_tool_names(available_tools)
    if not _looks_like_textual_tool_call_artifact(response, known_tool_names=known_names):
        return response

    repaired_prompt = apply_prompt_budget_guard(
        [
            prompt_messages[0],
            SystemMessage(content=_TOOL_CALL_PROTOCOL_REPAIR_NOTE),
            *prompt_messages[1:],
            AIMessage(content=_message_text(response)),
        ],
        budget=context_budget,
    )
    repaired = _invoke_with_tool_result_fallback(
        model_with_tools_for(selected_model, selected_thinking_mode, available_tools),
        repaired_prompt,
        fallback_messages=fallback_messages or prompt_messages,
        known_tool_names=known_names,
    )
    if not _looks_like_textual_tool_call_artifact(repaired, known_tool_names=known_names):
        return repaired

    fallback_prompt = apply_prompt_budget_guard(
        [
            prompt_messages[0],
            SystemMessage(content=_TOOL_CALL_MARKUP_REPAIR_NOTE),
            *prompt_messages[1:],
            AIMessage(content=_message_text(repaired)),
        ],
        budget=context_budget,
    )
    return _invoke_with_tool_result_fallback(
        model_for(selected_model, selected_thinking_mode),
        fallback_prompt,
        fallback_messages=fallback_messages or prompt_messages,
        known_tool_names=known_names,
    )


def _repair_tool_free_answer_response(
    *,
    response: Any,
    prompt_messages: list[Any],
    fallback_messages: list[Any] | None = None,
    context_budget: ContextBudget,
    selected_model: str,
    selected_thinking_mode: str,
    model_for,
) -> Any:
    fallback_source_messages = fallback_messages or prompt_messages
    if not _message_text(response).strip() and _has_tool_result_messages(fallback_source_messages):
        synthesized = _invoke_tool_result_synthesis(
            model_for(selected_model, selected_thinking_mode),
            fallback_source_messages,
        )
        if synthesized is not None:
            return synthesized
        return _tool_result_fallback_message(fallback_source_messages)

    if not _looks_like_textual_tool_call_artifact(response):
        return response

    repaired_prompt = apply_prompt_budget_guard(
        [
            prompt_messages[0],
            SystemMessage(content=_TOOL_EXHAUSTION_NOTE),
            SystemMessage(content=_TOOL_CALL_MARKUP_REPAIR_NOTE),
            *prompt_messages[1:],
            AIMessage(content=_message_text(response)),
        ],
        budget=context_budget,
    )
    repaired = _invoke_with_tool_result_fallback(
        model_for(selected_model, selected_thinking_mode),
        repaired_prompt,
        fallback_messages=fallback_source_messages,
    )
    if not _looks_like_textual_tool_call_artifact(repaired):
        return repaired

    final_prompt = apply_prompt_budget_guard(
        [
            prompt_messages[0],
            SystemMessage(content=_TOOL_EXHAUSTION_NOTE),
            SystemMessage(content=_TOOL_CALL_MARKUP_REPAIR_NOTE),
            SystemMessage(content=_TOOL_CALL_LAST_RESORT_NOTE),
            *prompt_messages[1:],
            AIMessage(content=_message_text(repaired)),
        ],
        budget=context_budget,
    )
    final_attempt = _invoke_with_tool_result_fallback(
        model_for(selected_model, selected_thinking_mode),
        final_prompt,
        fallback_messages=fallback_source_messages,
    )
    if not _looks_like_textual_tool_call_artifact(final_attempt):
        return final_attempt

    synthesized = _invoke_tool_result_synthesis(
        model_for(selected_model, selected_thinking_mode),
        fallback_source_messages,
    )
    if synthesized is not None:
        return synthesized

    return _tool_result_fallback_message(fallback_source_messages)


_PLAN_TRIGGER_KEYWORDS = (
    "然后",
    "接着",
    "之后",
    "并且",
    "对比",
    "分析",
    "then",
    "and then",
    "compare",
    "analyze",
    "step by step",
)


def _should_plan(
    *,
    state: AgentState,
    scene: str,
    plan_scenes: tuple[str, ...],
    min_chars: int,
) -> bool:
    existing = state.get("plan")
    if existing is not None:
        meta = state.get("plan_meta") or {}
        return bool(meta.get("replan_requested"))

    task_brief = str(state.get("task_brief") or "")
    if not task_brief:
        return False
    scene_allowed = scene in plan_scenes
    long_enough = len(task_brief) >= min_chars
    lowered = task_brief.lower()
    multi_step = any(keyword in lowered for keyword in _PLAN_TRIGGER_KEYWORDS)
    if long_enough:
        return True
    if scene_allowed and multi_step:
        return True
    return False


def _format_plan_block(plan: Plan, current_step_id: str) -> str:
    if not plan.steps:
        return ""
    lines = ["## 当前计划", f"目标验收: {plan.success_criteria or '(未声明)'}"]
    for step in plan.steps:
        marker = "✓" if step.done else ("➤" if step.id == current_step_id else "•")
        line = f"- {marker} [{step.id}] {step.goal}"
        if step.expected_tools:
            line += f"  (建议工具: {', '.join(step.expected_tools)})"
        if step.note:
            line += f"  // {step.note}"
        lines.append(line)
    lines.append(
        "完成当前步骤后，如仍需工具请继续调用；若已可给出最终答复，直接用自然语言回答。"
    )
    return "\n".join(lines)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        newline = stripped.find("\n")
        if newline != -1:
            stripped = stripped[newline + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _parse_plan_json(text: str, *, created_at_call: int, replan_count: int) -> Plan | None:
    obj = _extract_json_object(text)
    if obj is None:
        return None
    raw_steps = obj.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return None
    steps: list[PlanStep] = []
    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            continue
        step_id = str(raw.get("id") or f"s{index + 1}")
        goal = str(raw.get("goal") or "").strip()
        if not goal:
            continue
        expected = raw.get("expected_tools") or []
        expected_tools = [str(t) for t in expected if isinstance(t, (str, int))]
        steps.append(PlanStep(id=step_id, goal=goal, expected_tools=expected_tools))
    if not steps:
        return None
    return Plan(
        steps=steps,
        success_criteria=str(obj.get("success_criteria") or "").strip(),
        created_at_call=created_at_call,
        replan_count=replan_count,
    )


def _parse_reflection_json(text: str) -> ReflectionVerdict | None:
    obj = _extract_json_object(text)
    if obj is None:
        return None
    status = str(obj.get("status") or "").strip().lower()
    if status not in {"done", "replan"}:
        return None
    missing_raw = obj.get("missing") or []
    missing = [str(m) for m in missing_raw if isinstance(m, (str, int))]
    return ReflectionVerdict(
        status=status,  # type: ignore[arg-type]
        reasoning=str(obj.get("reasoning") or ""),
        missing=missing,
    )


def _collect_tool_names_since_latest_human(messages: list[Any]) -> list[str]:
    names: list[str] = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", None) or []:
                name = call.get("name") if isinstance(call, dict) else None
                if name:
                    names.append(str(name))
    names.reverse()
    return names


def _resolve_prompt_mode(state: AgentState) -> PromptMode:
    stored = state.get("prompt_mode")
    if isinstance(stored, PromptMode):
        return stored
    if isinstance(stored, str):
        try:
            return PromptMode(stored)
        except ValueError:
            pass
    if state.get("merge_proposal") and not state.get("merge_decision"):
        return PromptMode.BRANCH_REVIEW
    return PromptMode.EXPLORE


def build_graph(
    *,
    settings: Settings,
    checkpointer=None,
    store=None,
    memory_retriever: MemoryRetriever | None = None,
    memory_policy: MemoryPolicy | None = None,
    memory_writer: MemoryWriter | None = None,
    memory_extractor: MemoryExtractor | None = None,
    skill_registry: SkillRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
):
    effective_skill_registry = skill_registry or SkillRegistry.from_settings(settings)
    effective_tool_registry = tool_registry or build_tool_registry(
        settings=settings,
        skill_registry=effective_skill_registry,
        store=store,
        checkpointer=checkpointer,
    )
    tools = list(effective_tool_registry.tools)
    tools_by_name = effective_tool_registry.by_name
    tool_runtime_by_name = effective_tool_registry.runtime_by_name
    effective_memory_policy = memory_policy or getattr(memory_retriever, "policy", None) or MemoryPolicy()
    effective_memory_retriever = memory_retriever or MemoryRetriever(store=store, policy=effective_memory_policy)
    effective_memory_writer = memory_writer or MemoryWriter(store=store, policy=effective_memory_policy)
    effective_memory_extractor = memory_extractor or MemoryExtractor()
    base_model_cache: dict[str, Any] = {}
    model_cache: dict[str, Any] = {}
    model_with_tools_cache: dict[str, Any] = {}
    tool_result_cache = ToolResultCacheStore()

    def base_model_for(model_id: str, thinking_mode: str):
        cache_key = f"{model_id}|{thinking_mode or ''}"
        cached = base_model_cache.get(cache_key)
        if cached is not None:
            return cached
        model = create_chat_model(
            model_id,
            temperature=settings.temperature,
            thinking_mode=thinking_mode or None,
            settings=settings,
        )
        base_model_cache[cache_key] = model
        return model

    def model_for(model_id: str, thinking_mode: str):
        cache_key = f"{model_id}|{thinking_mode or ''}"
        cached = model_cache.get(cache_key)
        if cached is not None:
            return cached
        model = base_model_for(model_id, thinking_mode).with_config({"run_name": "focus_agent_model"})
        model_cache[cache_key] = model
        return model

    def model_with_tools_for(model_id: str, thinking_mode: str, available_tools: list[Any] | None = None):
        selected_tools = list(tools if available_tools is None else available_tools)
        tool_key = ",".join(sorted(str(getattr(tool, "name", "")) for tool in selected_tools))
        cache_key = f"{model_id}|{thinking_mode or ''}|{tool_key}"
        cached = model_with_tools_cache.get(cache_key)
        if cached is not None:
            return cached
        bound = base_model_for(model_id, thinking_mode).bind_tools(selected_tools).with_config(
            {"run_name": "focus_agent_model"}
        )
        model_with_tools_cache[cache_key] = bound
        return bound

    def bootstrap_turn(state: AgentState) -> dict[str, Any]:
        return {"llm_calls": state.get("llm_calls", 0)}

    def retrieve_memory(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        latest_user = _latest_human_message_text(state.get("messages", []))
        prompt_mode = _resolve_prompt_mode(state)
        bundle = effective_memory_retriever.retrieve_for_turn(
            context=runtime.context,
            state=dict(state),
            query=latest_user,
            prompt_mode=prompt_mode,
        )
        return {
            "retrieved_memories": [
                {
                    **hit.record.model_dump(mode="json"),
                    "score": hit.score,
                    "matched_terms": hit.matched_terms,
                }
                for hit in bundle.hits
            ],
            "memory_prompt_block": render_memory_block(bundle),
            "prompt_mode": prompt_mode,
        }

    def assemble_context(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        latest_user = _latest_human_message_text(state.get("messages", []))
        prompt_mode = _resolve_prompt_mode(state)
        active_skill_ids = tuple(
            runtime.context.skill_hints
            or tuple(str(item) for item in state.get("active_skill_ids", []) or ())
        )
        active_skills_block = effective_skill_registry.render_active_skills_block(active_skill_ids)
        available_skills_block = effective_skill_registry.render_available_skills_block()
        context_slice = build_context_slice(
            {
                **dict(state),
                "pinned_items": deepcopy(state.get("pinned_items", [])),
                "merge_queue": deepcopy(state.get("merge_queue", [])),
                "_memory_lines": [
                    item.get("summary") or item.get("content") or str(item)
                    for item in state.get("retrieved_memories", [])
                ],
                "_scene": runtime.context.scene,
                "_active_skills_block": active_skills_block,
                "_available_skills_block": available_skills_block,
            },
            prompt_mode,
        )
        task_brief = state.get("task_brief")
        if not task_brief and latest_user:
            task_brief = latest_user[:300]
        assembled_context = context_slice.render_prompt()
        updates: dict[str, Any] = {
            "recent_messages": context_slice.recent_messages,
            "assembled_context": assembled_context,
            "task_brief": task_brief or state.get("task_brief", ""),
            "prompt_mode": prompt_mode,
            "active_skill_ids": list(active_skill_ids),
            "active_skills_block": active_skills_block,
            "available_skills_block": available_skills_block,
        }
        if settings.agent_context_engineering_v2_enabled:
            decision = build_context_engineering_decision(
                settings=settings,
                state={
                    **dict(state),
                    "recent_messages": context_slice.recent_messages,
                    "context_budget": _context_budget_from_state(state),
                },
                prompt_mode=prompt_mode,
                assembled_context=assembled_context,
                role="executor",
                artifact_dir=settings.artifact_dir,
            ).model_dump(mode="json")
            compressed_prompt = decision.pop("compressed_prompt", None)
            if compressed_prompt:
                updates["assembled_context"] = str(compressed_prompt)
            updates["context_budget_decision"] = decision.get("budget")
            updates["context_compression_plan"] = decision.get("compression_plan")
            updates["context_artifact_refs"] = list(decision.get("artifact_refs") or [])
            updates["role_context_views"] = list(decision.get("role_context_views") or [])
            updates["plan_meta"] = {
                **(state.get("plan_meta") or {}),
                "context_budget_decision": updates["context_budget_decision"],
                "context_compression_plan": updates["context_compression_plan"],
                "context_artifact_refs": updates["context_artifact_refs"],
                "role_context_views": updates["role_context_views"],
            }
        return updates

    def role_route_dry_run(state: AgentState) -> dict[str, Any]:
        if not settings.agent_role_routing_enabled:
            return {}
        latest_user = _latest_human_message_text(list(state.get("messages", []) or []))
        task_text = latest_user or str(state.get("task_brief") or "")
        tool_policy = _classify_turn_tool_policy(task_text)
        plan = build_role_route_plan(
            settings=settings,
            task_text=task_text,
            available_tool_names=[str(getattr(tool, "name", "")) for tool in tools],
            tool_policy=tool_policy,
        )
        return {"role_route_plan": plan.model_dump(mode="json")}

    def delegation_governance(state: AgentState) -> dict[str, Any]:
        latest_user = _latest_human_message_text(list(state.get("messages", []) or []))
        task_text = latest_user or str(state.get("task_brief") or "")
        tool_policy = _classify_turn_tool_policy(task_text)
        available_tool_names = [str(getattr(tool, "name", "")) for tool in tools]
        updates: dict[str, Any] = {}
        meta = dict(state.get("plan_meta") or {})
        if settings.agent_delegation_enabled:
            delegation_plan = build_agent_delegation_plan(
                settings=settings,
                task_text=task_text,
                role_route_plan=state.get("role_route_plan"),
                available_tool_names=available_tool_names,
                tool_policy=tool_policy,
            ).model_dump(mode="json")
            updates["agent_delegation_plan"] = delegation_plan
            updates["agent_runs"] = list(delegation_plan.get("runs") or [])
            meta["agent_delegation_plan"] = delegation_plan
        if settings.agent_model_router_enabled:
            role = infer_tool_router_role(state.get("role_route_plan"))
            decision = build_model_route_decision(
                settings=settings,
                role=role,
                selected_model=str(state.get("selected_model") or settings.model),
                task_text=task_text,
                tool_risk="low",
                context_size=len(str(state.get("assembled_context") or "")),
            ).model_dump(mode="json")
            updates["model_route_decision"] = decision
            meta["model_route_decision"] = decision
            if decision.get("enabled") and decision.get("mode") == "enforce":
                updates["selected_model"] = str(decision.get("effective_model") or state.get("selected_model") or settings.model)
        if settings.agent_task_ledger_enabled:
            delegation_plan = updates.get("agent_delegation_plan") or state.get("agent_delegation_plan") or {}
            ledger = build_agent_task_ledger(
                settings=settings,
                delegation_plan=delegation_plan,
            ).model_dump(mode="json")
            artifacts = [
                item.model_dump(mode="json")
                for item in build_delegated_artifacts(
                    ledger=ledger,
                    delegation_plan=delegation_plan,
                    memory_curator_decision=state.get("memory_curator_decision"),
                    tool_route_plan=state.get("tool_route_plan"),
                    context_artifact_refs=state.get("context_artifact_refs") or [],
                )
            ]
            critic_result = None
            if settings.agent_critic_gate_enabled:
                critic_result = evaluate_critic_gate(
                    settings=settings,
                    ledger=ledger,
                    artifacts=artifacts,
                ).model_dump(mode="json")
                ledger = apply_critic_retry_tasks(
                    ledger=ledger,
                    critic_gate_result=critic_result,
                ).model_dump(mode="json")
            synthesis_result = None
            if settings.agent_artifact_synthesis_enabled:
                synthesis_result = synthesize_delegated_artifacts(
                    settings=settings,
                    artifacts=artifacts,
                    critic_gate_result=critic_result,
                ).model_dump(mode="json")
            updates["agent_task_ledger"] = ledger
            updates["delegated_artifacts"] = artifacts
            meta["agent_task_ledger"] = ledger
            meta["delegated_artifacts"] = artifacts
            if critic_result is not None:
                updates["critic_gate_result"] = critic_result
                meta["critic_gate_result"] = critic_result
            if synthesis_result is not None:
                updates["artifact_synthesis_result"] = synthesis_result
                meta["artifact_synthesis_result"] = synthesis_result
        if meta != dict(state.get("plan_meta") or {}):
            updates["plan_meta"] = meta
        return updates

    def plan_node(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        if not settings.plan_act_reflect_enabled:
            return {}
        scene = str(getattr(runtime.context, "scene", "") or "")
        if not _should_plan(
            state=state,
            scene=scene,
            plan_scenes=tuple(settings.plan_scenes),
            min_chars=int(settings.plan_task_brief_min_chars),
        ):
            return {}

        model_route_decision = state.get("model_route_decision") or {}
        if (
            isinstance(model_route_decision, dict)
            and model_route_decision.get("enabled")
            and model_route_decision.get("mode") == "enforce"
            and model_route_decision.get("effective_model")
        ):
            selected_model = str(model_route_decision.get("effective_model"))
        else:
            selected_model = str(state.get("selected_model") or settings.model)
        task_brief = str(state.get("task_brief") or _latest_human_message_text(state.get("messages", [])))
        tool_names = [t.name for t in tools][:20]
        prior_reflection = state.get("reflection")
        replan_count = 0
        existing_plan = state.get("plan")
        if isinstance(existing_plan, Plan):
            replan_count = existing_plan.replan_count + 1

        system = SystemMessage(
            content=(
                "你是一个任务规划器。阅读用户请求，输出一个紧凑、可验证的执行计划。"
                "必须返回 JSON，字段为 {\"steps\": [{\"id\": \"s1\", \"goal\": \"...\", "
                "\"expected_tools\": [\"tool_name\"]}], \"success_criteria\": \"...\"}。"
                "要求：2-5 步；success_criteria 必须客观可判断（禁止写‘充分’‘合理’这类模糊词）；"
                "只规划不执行；不要返回其它字段。"
            )
        )
        user_lines = [f"任务简述：{task_brief}", f"可用工具：{', '.join(tool_names) or '(无)'}"]
        if prior_reflection is not None:
            missing = ", ".join(prior_reflection.missing) or prior_reflection.reasoning
            user_lines.append(f"上一轮未满足：{missing}。请修正计划以覆盖这些缺口。")
        user = HumanMessage(content="\n".join(user_lines))

        try:
            response = model_for(selected_model, "").invoke([system, user])
            raw_text = _message_text(response)
            plan = _parse_plan_json(raw_text, created_at_call=state.get("llm_calls", 0), replan_count=replan_count)
        except Exception:  # noqa: BLE001
            plan = None

        if plan is None or not plan.steps:
            meta = {
                **(state.get("plan_meta") or {}),
                "plan_skipped": True,
                "replan_requested": False,
            }
            return {
                "plan": None,
                "current_step_id": "",
                "reflection": None,
                "plan_meta": meta,
                "llm_calls": state.get("llm_calls", 0) + 1,
            }

        meta = {
            **(state.get("plan_meta") or {}),
            "plan_calls": int((state.get("plan_meta") or {}).get("plan_calls", 0)) + 1,
            "replan_requested": False,
        }
        return {
            "plan": plan,
            "current_step_id": plan.steps[0].id,
            "reflection": None,
            "plan_meta": meta,
            "llm_calls": state.get("llm_calls", 0) + 1,
        }

    def reflect_node(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        del runtime
        plan = state.get("plan")
        if not isinstance(plan, Plan) or not plan.steps:
            return {}
        if plan.replan_count >= int(settings.plan_max_replans):
            meta = {**(state.get("plan_meta") or {}), "reflect_forced_done": True}
            return {
                "reflection": ReflectionVerdict(status="done", reasoning="replan budget exhausted"),
                "plan_meta": meta,
            }

        selected_model = str(state.get("selected_model") or settings.model)
        last_ai = _latest_final_ai_text(state.get("messages", []))
        trajectory_tools = _collect_tool_names_since_latest_human(list(state.get("messages", []) or []))

        system = SystemMessage(
            content=(
                "你是一个严格的计划审计员。判断最终答复是否满足 success_criteria。"
                "必须返回 JSON: {\"status\": \"done\"|\"replan\", \"reasoning\": \"...\", \"missing\": [\"...\"]}。"
                "只在确实存在未覆盖的子目标时选 replan，否则选 done。"
            )
        )
        plan_summary = _format_plan_block(plan, state.get("current_step_id", ""))
        user = HumanMessage(
            content=(
                f"success_criteria: {plan.success_criteria}\n"
                f"计划快照:\n{plan_summary}\n"
                f"已调用工具: {', '.join(trajectory_tools) or '(无)'}\n"
                f"最终答复:\n{last_ai}"
            )
        )
        try:
            response = model_for(selected_model, "").invoke([system, user])
            verdict = _parse_reflection_json(_message_text(response))
        except Exception:  # noqa: BLE001
            verdict = None

        if verdict is None:
            verdict = ReflectionVerdict(status="done", reasoning="reflect parse failed; defaulting done")

        meta = {
            **(state.get("plan_meta") or {}),
            "reflect_calls": int((state.get("plan_meta") or {}).get("reflect_calls", 0)) + 1,
        }
        if verdict.status == "replan" and plan.replan_count < int(settings.plan_max_replans):
            meta["replan_requested"] = True
            meta["replanned"] = True
        else:
            verdict = ReflectionVerdict(status="done", reasoning=verdict.reasoning, missing=verdict.missing)
            meta["replan_requested"] = False
        return {
            "reflection": verdict,
            "plan_meta": meta,
            "llm_calls": state.get("llm_calls", 0) + 1,
        }

    def agent_loop(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        del runtime
        messages = _messages_for_model(state)
        fallback_messages = _latest_turn_messages(list(state.get("messages", []) or messages))
        selected_model = str(state.get("selected_model") or settings.model)
        selected_thinking_mode = str(state.get("selected_thinking_mode") or "")
        assembled = state.get("assembled_context", "")
        latest_user = _latest_human_message_text(list(state.get("messages", []) or []))
        if not latest_user:
            latest_user = _latest_human_message_text(messages) or str(state.get("task_brief") or "")
        context_budget = _context_budget_from_state(state)
        tool_policy = _classify_turn_tool_policy(latest_user)
        available_tools = _tools_for_policy(tool_policy, tools, latest_user)
        tool_route_plan = None
        if settings.agent_tool_router_enabled:
            router_role = infer_tool_router_role(state.get("role_route_plan"))
            tool_route_plan = build_tool_route_plan(
                tool_registry=effective_tool_registry,
                role=router_role,
                tool_policy=tool_policy,
                available_tool_names=[str(getattr(tool, "name", "")) for tool in available_tools],
                enforce=bool(settings.agent_tool_router_enforce),
            )
            if settings.agent_tool_router_enforce:
                allowed = set(tool_route_plan.allowed_tools)
                available_tools = [
                    tool
                    for tool in available_tools
                    if str(getattr(tool, "name", "")) in allowed
                ]
        known_names = _known_tool_names(available_tools)
        tool_protocol_repair_count = 0
        tool_protocol_repair_reason = ""
        policy_note = _tool_policy_note(tool_policy)
        plan = state.get("plan")
        if isinstance(plan, Plan) and plan.steps:
            plan_block = _format_plan_block(plan, state.get("current_step_id", ""))
            if plan_block and plan_block not in assembled:
                assembled = f"{assembled}\n\n{plan_block}".strip()
        prompt_messages = [SystemMessage(content=assembled), *messages]
        if policy_note:
            prompt_messages = [prompt_messages[0], SystemMessage(content=policy_note), *prompt_messages[1:]]
        prompt_messages = apply_prompt_budget_guard(prompt_messages, budget=context_budget)
        prompt_messages = _ensure_reasoning_content_for_tool_call_history(
            prompt_messages,
            model_id=selected_model,
            thinking_mode=selected_thinking_mode,
            settings=settings,
        )
        if tool_policy == "live_web_research" and _live_web_research_should_start_with_search(
            latest_user,
            messages,
            available_tools,
        ):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"live-web-search-{state.get('llm_calls', 0) + 1}",
                        "name": "web_search",
                        "args": {"query": latest_user},
                    }
                ],
            )
        elif tool_policy == "workspace_lookup" and _workspace_lookup_should_start_with_search(
            latest_user,
            messages,
            available_tools,
        ):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"workspace-search-{state.get('llm_calls', 0) + 1}",
                        "name": "search_code",
                        "args": {"query": _workspace_search_query(latest_user)},
                    }
                ],
            )
        elif _should_force_tool_free_answer(list(state.get("messages", []) or [])):
            forced_prompt = apply_prompt_budget_guard(
                [
                    prompt_messages[0],
                    SystemMessage(content=_TOOL_EXHAUSTION_NOTE),
                    *prompt_messages[1:],
                ],
                budget=context_budget,
            )
            forced_prompt = _ensure_reasoning_content_for_tool_call_history(
                forced_prompt,
                model_id=selected_model,
                thinking_mode=selected_thinking_mode,
                settings=settings,
            )
            response = _invoke_with_tool_result_fallback(
                model_for(selected_model, selected_thinking_mode),
                forced_prompt,
                fallback_messages=fallback_messages,
                known_tool_names=known_names,
            )
            if _looks_like_textual_tool_call_artifact(response, known_tool_names=known_names):
                tool_protocol_repair_count += 1
                tool_protocol_repair_reason = "textual_tool_marker"
            response = _repair_tool_free_answer_response(
                response=response,
                prompt_messages=prompt_messages,
                fallback_messages=fallback_messages,
                context_budget=context_budget,
                selected_model=selected_model,
                selected_thinking_mode=selected_thinking_mode,
                model_for=model_for,
            )
        elif not available_tools:
            response = _invoke_with_tool_result_fallback(
                model_for(selected_model, selected_thinking_mode),
                prompt_messages,
                fallback_messages=fallback_messages,
                known_tool_names=known_names,
            )
            if _looks_like_textual_tool_call_artifact(response, known_tool_names=known_names):
                tool_protocol_repair_count += 1
                tool_protocol_repair_reason = "textual_tool_marker"
            response = _repair_tool_free_answer_response(
                response=response,
                prompt_messages=prompt_messages,
                fallback_messages=fallback_messages,
                context_budget=context_budget,
                selected_model=selected_model,
                selected_thinking_mode=selected_thinking_mode,
                model_for=model_for,
            )
        else:
            response = _invoke_with_tool_result_fallback(
                model_with_tools_for(selected_model, selected_thinking_mode, available_tools),
                prompt_messages,
                fallback_messages=fallback_messages,
                known_tool_names=known_names,
            )
            if _looks_like_textual_tool_call_artifact(response, known_tool_names=known_names):
                tool_protocol_repair_count += 1
                tool_protocol_repair_reason = "textual_tool_marker"
            response = _repair_textual_tool_call_response(
                response=response,
                prompt_messages=prompt_messages,
                fallback_messages=fallback_messages,
                context_budget=context_budget,
                selected_model=selected_model,
                selected_thinking_mode=selected_thinking_mode,
                available_tools=available_tools,
                model_for=model_for,
                model_with_tools_for=model_with_tools_for,
            )
        updates: dict[str, Any] = {
            "messages": [response],
            "llm_calls": state.get("llm_calls", 0) + 1,
        }
        if tool_route_plan is not None:
            dumped = tool_route_plan.model_dump(mode="json")
            updates["tool_route_plan"] = dumped
            plan_meta = {
                **(state.get("plan_meta") or {}),
                "tool_route_plan": dumped,
            }
            if settings.agent_self_repair_enabled:
                failures = [
                    item.model_dump(mode="json")
                    for item in build_failure_records(
                        delegation_plan=state.get("agent_delegation_plan"),
                        tool_route_plan=dumped,
                        model_route_decision=state.get("model_route_decision"),
                    )
                ]
                updates["agent_failure_records"] = failures
                plan_meta["agent_failure_records"] = failures
            if settings.agent_review_queue_enabled:
                review_items = [
                    item.model_dump(mode="json")
                    for item in build_review_queue(
                        settings=settings,
                        memory_curator_decision=state.get("memory_curator_decision"),
                        tool_route_plan=dumped,
                        model_route_decision=state.get("model_route_decision"),
                        agent_failure_records=updates.get("agent_failure_records") or state.get("agent_failure_records") or [],
                    )
                ]
                updates["agent_review_queue"] = review_items
                plan_meta["agent_review_queue"] = review_items
            updates["plan_meta"] = plan_meta
        if tool_protocol_repair_count:
            plan_meta = {
                **(updates.get("plan_meta") or state.get("plan_meta") or {}),
                "tool_protocol_repair_count": int(
                    (updates.get("plan_meta") or state.get("plan_meta") or {}).get(
                        "tool_protocol_repair_count",
                        0,
                    )
                )
                + tool_protocol_repair_count,
                "tool_protocol_repair_reason": tool_protocol_repair_reason,
            }
            updates["plan_meta"] = plan_meta
        return updates

    def tool_executor(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        last_message = state["messages"][-1]
        context_budget = _context_budget_from_state(state)
        branch_meta = state.get("branch_meta") or {}
        branch_id = None
        if isinstance(branch_meta, dict):
            raw_branch_id = branch_meta.get("branch_id") or branch_meta.get("id")
            branch_id = str(raw_branch_id) if raw_branch_id else None
        root_thread_id = runtime.context.root_thread_id
        if runtime.context.branch_id and not branch_id:
            branch_id = runtime.context.branch_id
        turn_index = sum(1 for message in state.get("messages", []) if isinstance(message, HumanMessage))
        turn_scope_key = build_cache_scope_key(
            scope="turn",
            root_thread_id=root_thread_id,
            branch_id=branch_id,
            turn_id=str(turn_index or 1),
        )
        execution_inputs: list[ToolExecutionInput] = []
        cache_scope_keys: dict[int, str] = {}
        invalidation_scope_keys = [
            turn_scope_key,
            build_cache_scope_key(scope="thread", root_thread_id=root_thread_id, branch_id=branch_id),
            build_cache_scope_key(scope="branch", root_thread_id=root_thread_id, branch_id=branch_id),
        ]
        messages_by_index: dict[int, ToolMessage] = {}
        for index, tool_call in enumerate(getattr(last_message, "tool_calls", []) or []):
            tool_name = str(tool_call["name"])
            route_plan = state.get("tool_route_plan") or {}
            denied_tools = set(route_plan.get("denied_tools") or []) if isinstance(route_plan, dict) else set()
            if tool_name in denied_tools and bool(route_plan.get("enforce", True)):
                messages_by_index[index] = (
                    build_tool_error_message(
                        tool_call_id=str(tool_call["id"]),
                        tool_name=tool_name,
                        args=dict(tool_call.get("args") or {}),
                        error=f"Forbidden tool by Tool Router policy: {tool_name}",
                        runtime_info={"forbidden_by_tool_router": True},
                    )
                )
                continue
            tool = tools_by_name.get(tool_name)
            if tool is None:
                messages_by_index[index] = (
                    build_tool_error_message(
                        tool_call_id=str(tool_call["id"]),
                        tool_name=tool_name,
                        args=dict(tool_call.get("args") or {}),
                        error=f"Unknown tool: {tool_name}",
                    )
                )
                continue
            runtime_meta = tool_runtime_by_name.get(tool_name)
            if runtime_meta is None:
                continue
            execution_inputs.append(
                ToolExecutionInput(
                    index=index,
                    tool_call_id=str(tool_call["id"]),
                    tool_name=tool_name,
                    args=dict(tool_call.get("args") or {}),
                    tool=tool,
                    runtime=runtime_meta,
                )
            )
            cache_scope_keys[index] = build_cache_scope_key(
                scope=runtime_meta.cache_scope,
                root_thread_id=root_thread_id,
                branch_id=branch_id,
                turn_id=str(turn_index or 1),
            )
        for result in execute_tool_calls(
            execution_inputs,
            context_budget=context_budget,
            cache_store=tool_result_cache,
            cache_scope_keys=cache_scope_keys,
            invalidation_scope_keys=invalidation_scope_keys,
        ):
            messages_by_index[result.index] = result.message
        result_messages = [messages_by_index[index] for index in sorted(messages_by_index)]
        return {"messages": result_messages}

    def summarize_turn(state: AgentState) -> dict[str, Any]:
        last_user = _latest_human_message_text(state.get("messages", []))
        last_ai = _latest_final_ai_text(state.get("messages", []))
        previous_summary = state.get("rolling_summary", "")
        candidate_lines = [
            line
            for line in [previous_summary, f"User: {last_user}", f"Assistant: {last_ai}"]
            if line
        ]
        joined = "\n".join(candidate_lines)
        if len(joined) > 4000:
            joined = joined[-4000:]
        return {"rolling_summary": joined}

    def extract_memories(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        if not _should_extract_memories(state):
            return {
                "memory_write_requests": [],
                "memory_write_result": {"prepared": 0, "written": [], "merged": [], "skipped": [], "failed": []},
            }
        extraction = effective_memory_extractor.extract_from_turn(context=runtime.context, state=dict(state))
        return {
            "memory_write_requests": [record.model_dump(mode="json") for record in extraction.records],
            "memory_write_result": {
                "prepared": len(extraction.records),
                "written": [],
                "merged": [],
                "skipped": list(extraction.skipped_reasons),
                "failed": [],
                "summary": extraction.summary,
            },
        }

    def write_memories(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        raw_requests = list(state.get("memory_write_requests", []) or [])
        if not raw_requests:
            return {
                "memory_write_requests": [],
                "memory_write_result": state.get("memory_write_result", {}),
            }
        records = [MemoryWriteRequest.model_validate(item) for item in raw_requests]
        outcome = effective_memory_writer.persist_records(
            records,
            context=runtime.context,
            state=dict(state),
        )
        return {
            "memory_write_requests": [],
            "memory_write_result": outcome,
        }

    def maybe_interrupt_for_merge(state: AgentState) -> dict[str, Any]:
        if state.get("merge_proposal") and not state.get("merge_decision"):
            decision = interrupt(
                {
                    "kind": "merge_review",
                    "proposal": state["merge_proposal"],
                    "message": "Review the branch proposal and choose whether to import it into the parent thread.",
                }
            )
            return {"merge_decision": decision}
        return {}

    def should_continue_after_act(
        state: AgentState,
    ) -> Literal["tool_executor", "reflect", "summarize_turn"]:
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "tool_executor"
        if settings.plan_act_reflect_enabled and isinstance(state.get("plan"), Plan):
            return "reflect"
        return "summarize_turn"

    def should_continue_after_reflect(
        state: AgentState,
    ) -> Literal["plan", "summarize_turn"]:
        meta = state.get("plan_meta") or {}
        if meta.get("replan_requested"):
            return "plan"
        return "summarize_turn"

    builder = StateGraph(AgentState, context_schema=RequestContext)
    builder.add_node("bootstrap_turn", bootstrap_turn)
    builder.add_node("retrieve_memory", retrieve_memory)
    builder.add_node("assemble_context", assemble_context)
    builder.add_node("role_route_dry_run", role_route_dry_run)
    builder.add_node("delegation_governance", delegation_governance)
    builder.add_node("plan", plan_node)
    builder.add_node("agent_loop", agent_loop)
    builder.add_node("tool_executor", tool_executor)
    builder.add_node("reflect", reflect_node)
    builder.add_node("summarize_turn", summarize_turn)
    builder.add_node("extract_memories", extract_memories)
    builder.add_node("write_memories", write_memories)
    builder.add_node("maybe_interrupt_for_merge", maybe_interrupt_for_merge)

    builder.add_edge(START, "bootstrap_turn")
    builder.add_edge("bootstrap_turn", "retrieve_memory")
    builder.add_edge("retrieve_memory", "assemble_context")
    builder.add_edge("assemble_context", "role_route_dry_run")
    builder.add_edge("role_route_dry_run", "delegation_governance")
    builder.add_edge("delegation_governance", "plan")
    builder.add_edge("plan", "agent_loop")
    builder.add_conditional_edges(
        "agent_loop",
        should_continue_after_act,
        ["tool_executor", "reflect", "summarize_turn"],
    )
    builder.add_edge("tool_executor", "agent_loop")
    builder.add_conditional_edges(
        "reflect",
        should_continue_after_reflect,
        ["plan", "summarize_turn"],
    )
    builder.add_edge("summarize_turn", "extract_memories")
    builder.add_edge("extract_memories", "write_memories")
    builder.add_edge("write_memories", "maybe_interrupt_for_merge")
    builder.add_edge("maybe_interrupt_for_merge", END)

    return builder.compile(checkpointer=checkpointer, store=store)


def _should_extract_memories(state: AgentState) -> bool:
    reflection = state.get("reflection")
    reflection_status = getattr(reflection, "status", None) or (
        reflection.get("status") if isinstance(reflection, dict) else None
    )
    if reflection_status == "replan":
        return False
    messages = list(state.get("messages", []) or [])
    if not messages:
        return False
    last_message = messages[-1]
    if isinstance(last_message, AIMessage) and getattr(last_message, "tool_calls", None):
        return False
    return bool(_latest_final_ai_text(messages))
