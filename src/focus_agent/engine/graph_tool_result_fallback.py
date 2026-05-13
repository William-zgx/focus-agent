from __future__ import annotations

import json
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..core.repo_call import has_repo_method
from ..core.state import AgentState
from ..core.tool_protocol import looks_like_textual_tool_call_artifact
from ..core.types import ContextBudget
from .graph_tool_history_repair import _message_text


_TOOL_CALL_REPAIR_FALLBACK_TEXT = (
    "我已经拿到工具结果，但还没有足够可用的信息形成完整结论。请稍后重试，或换一个更稳定的模型。"
)


_TOOL_RESULT_SYNTHESIS_NOTE = (
    "You are writing the final user-facing answer after tool use. Do not call tools. "
    "Use only the tool observations provided below. If the user wrote Chinese, answer in Chinese. "
    "Do not mention formatting failures or internal retries. State uncertainty plainly, and include "
    "dates, numbers, and source names when available."
)


def _latest_human_message_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return _message_text(message)
    return ""


def _latest_final_ai_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            text = _message_text(message)
            if looks_like_textual_tool_call_artifact(text):
                continue
            return text
    return ""


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
                content = str(
                    result.get("content") or result.get("snippet") or result.get("line") or ""
                ).strip()
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
                        result_summary = " ".join(
                            part for part in [title, url or ref, content] if part
                        )
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
        HumanMessage(
            content=f"用户问题：{latest_user}\n\n本轮工具轨迹与工具结果：\n{digest}\n\n请直接给出最终答复。"
        ),
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
    from .graph_textual_tool_call_repair import _looks_like_textual_tool_call_artifact

    if not has_repo_method(model, "invoke"):
        return None
    try:
        response = model.invoke(_tool_result_synthesis_prompt(source_messages))
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


__all__ = [
    "_TOOL_CALL_REPAIR_FALLBACK_TEXT",
    "_TOOL_RESULT_SYNTHESIS_NOTE",
    "_latest_human_message_text",
    "_latest_final_ai_text",
    "_context_budget_from_state",
    "_truncate_inline",
    "_latest_turn_messages",
    "_fallback_answer_from_tool_results",
    "_tool_call_args_summary",
    "_tool_runtime_summary",
    "_tool_observation_summary",
    "_tool_result_snippets",
    "_tool_result_synthesis_prompt",
    "_has_tool_result_messages",
    "_tool_result_fallback_message",
    "_invoke_tool_result_synthesis",
    "_invoke_with_tool_result_fallback",
]
