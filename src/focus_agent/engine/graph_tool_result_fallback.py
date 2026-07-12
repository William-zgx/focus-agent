from __future__ import annotations

import json
import re
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..core.repo_call import has_repo_method
from ..core.state import AgentState
from ..core.tool_protocol import looks_like_textual_tool_call_artifact
from ..core.types import ContextBudget
from .graph_evidence import (
    evidence_bundle_source_snippets,
    normalize_evidence_bundle,
    relevant_web_tool_call_ids,
)
from .graph_execution_contract import skill_execution_evidence_facts
from .graph_tool_history_repair import _message_text
from .graph_web_result_fallback import (
    _chinese_weather_summary_from_payloads,
    _contains_weather_marker,
    _extract_concise_weather_text,
    _fallback_web_answer_from_tool_results,
    _first_result_text,
    _latest_relevant_web_payloads,
    _looks_like_internal_web_summary,
    _looks_like_live_web_fallback_payload,
    _looks_like_weather_query,
    _looks_like_web_observation_payload,
    _payload_results,
    _prompt_observation_payload,
    _reference_sources,
    _source_domain,
    _web_payload_main_answer,
    _web_payload_sources,
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


_UNFOUND_ANSWER_MARKERS = (
    "未找到",
    "没有找到",
    "找不到",
    "无法确认",
    "不能确认",
    "not found",
    "did not find",
    "cannot confirm",
    "can't confirm",
    "could not confirm",
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
    return _degraded_answer_from_tool_results(prompt_messages)


def _degraded_answer_from_tool_results(prompt_messages: list[Any]) -> str:
    latest_turn = _latest_turn_messages(prompt_messages)
    latest_user = _latest_human_message_text(latest_turn)
    chinese = bool(re.search(r"[\u4e00-\u9fff]", latest_user))
    web_answer = _fallback_web_answer_from_tool_results(latest_turn)
    failure = _latest_failed_tool_summary(latest_turn)

    if web_answer:
        if not failure:
            return web_answer
        if chinese:
            return (
                "Skill 主路径没有拿到可验证的业务结果，我先基于替代证据给出保守结论：\n"
                f"{web_answer}\n\n"
                "需要保留的不确定性："
                f"{failure or '主工具执行失败'}；未被替代来源确认的价格、业绩或时点数字不应视为最终行情。"
            )
        return (
            "The primary Skill path did not return verifiable business data. "
            "Here is a conservative answer from alternative evidence:\n"
            f"{web_answer}\n\n"
            "Uncertainty to keep: "
            f"{failure or 'the primary tool failed'}; prices, performance metrics, or timestamps "
            "not confirmed by the alternative source should not be treated as final."
        )

    snippets = _safe_tool_result_snippets(latest_turn)
    if snippets:
        if chinese:
            return (
                "我先根据当前已拿到的证据做保守整理：\n"
                + "\n".join(snippets[:8])
                + "\n\n需要保留的不确定性："
                f"{failure or '工具路径未能完成充分确认'}；未被证据直接支持的价格、业绩或时点数字不能补全。"
            )
        return (
            "Here is a conservative synthesis from the evidence currently available:\n"
            + "\n".join(snippets[:8])
            + "\n\nUncertainty to keep: "
            f"{failure or 'the tool path did not fully verify the answer'}; prices, performance metrics, "
            "or timestamps not directly supported by evidence should not be filled in."
        )

    if chinese:
        return (
            "目前不能给出完整结论。已尝试执行工具或 Skill，但没有拿到可验证的业务数据"
            f"{f'：{failure}' if failure else '。'}\n"
            "基于当前证据，只能保守判断：关键价格波动、业绩信息或来源仍缺失，不能编造完整行情数字。"
        )
    return (
        "I cannot provide a complete conclusion yet. The tool or Skill path did not return "
        f"verifiable business data{f': {failure}' if failure else '.'}\n"
        "Based on the current evidence, the missing price movement, performance details, or "
        "sources remain unconfirmed, so I should not invent complete market figures."
    )


def _fallback_skill_answer_from_tool_results(prompt_messages: list[Any]) -> str:
    latest_turn = _latest_turn_messages(prompt_messages)
    facts = skill_execution_evidence_facts(
        latest_turn,
        required_tools=("run_skill_entrypoint", "run_workspace_command"),
    )
    if not facts:
        return ""
    by_key = {str(fact.get("key") or ""): str(fact.get("value") or "") for fact in facts}
    labels_by_key = {
        str(fact.get("key") or ""): str(fact.get("label") or fact.get("key") or "")
        for fact in facts
    }
    lines: list[str] = []
    chinese = bool(re.search(r"[\u4e00-\u9fff]", _latest_human_message_text(latest_turn)))
    if chinese:
        lines.append("我根据刚刚的 Skill 沙箱执行结果整理如下：")
        code = by_key.get("code")
        name = by_key.get("name")
        if code or name:
            lines.append(f"- 标的：{name or ''}（{code or '未知代码'}）。")
        score = by_key.get("score")
        if score:
            lines.append(f"- 财务评分：{score}。")
        for key, label in (
            ("profitability.assessment", "盈利能力"),
            ("solvency.assessment", "偿债能力"),
            ("growth.assessment", "成长性"),
            ("operation.assessment", "运营效率"),
            ("anomalies.risk_level", "风险等级"),
        ):
            value = by_key.get(key)
            if value:
                lines.append(f"- {label}：{value}。")
        valuation_parts = []
        for key, label in (
            ("valuation.平均内在价值", "平均内在价值"),
            ("valuation.当前价格", "当前价格"),
            ("valuation.建议买入价", "建议买入价"),
            ("valuation.投资结论", "投资结论"),
        ):
            value = by_key.get(key)
            if value:
                valuation_parts.append(f"{label} {value}")
        if valuation_parts:
            lines.append(f"- 估值：{'；'.join(valuation_parts)}。")
        for key, value in _generic_skill_fact_lines(by_key).items():
            label = labels_by_key.get(key) or key
            lines.append(f"- {label}：{value}。")
        return "\n".join(lines) if len(lines) > 1 else ""

    lines.append("Based on the latest Skill sandbox result:")
    for key in (
        "code",
        "name",
        "score",
        "profitability.assessment",
        "solvency.assessment",
        "growth.assessment",
        "anomalies.risk_level",
        "valuation.平均内在价值",
        "valuation.当前价格",
        "valuation.投资结论",
    ):
        value = by_key.get(key)
        if value:
            lines.append(f"- {key}: {value}")
    for key, value in _generic_skill_fact_lines(by_key).items():
        lines.append(f"- {labels_by_key.get(key) or key}: {value}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _latest_failed_tool_summary(messages: list[Any]) -> str:
    pending_calls: dict[str, str] = {}
    failures: list[str] = []
    for message in _latest_turn_messages(messages):
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", None) or []:
                if not isinstance(call, dict):
                    continue
                call_id = str(call.get("id") or "").strip()
                if call_id:
                    pending_calls[call_id] = str(call.get("name") or "tool").strip() or "tool"
            continue
        if not isinstance(message, ToolMessage):
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "")
        tool_name = pending_calls.get(call_id, "tool")
        status = str(getattr(message, "status", "success") or "success").lower()
        payload = None
        raw = _message_text(message)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            pass
        failure = _payload_failure_summary(payload)
        if status == "error" or failure:
            failures.append(f"{tool_name} {failure or 'returned an error'}")
    return _truncate_inline("; ".join(failures[-2:]), max_chars=260)


def _payload_failure_summary(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in ("error", "message", "stderr"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _truncate_inline(value, max_chars=180)
    status = str(payload.get("status") or "").strip().lower()
    if status in {"error", "failed", "failure"}:
        return f"returned status {status}"
    stdout = payload.get("stdout")
    if isinstance(stdout, str) and stdout.strip():
        try:
            stdout_payload = json.loads(stdout)
        except json.JSONDecodeError:
            return ""
        if isinstance(stdout_payload, dict):
            return _payload_failure_summary(stdout_payload)
    return ""


def _generic_skill_fact_lines(facts_by_key: dict[str, str]) -> dict[str, str]:
    handled = {
        "status",
        "run_id",
        "generated_date",
        "generated_at",
        "code",
        "name",
        "score",
        "profitability.assessment",
        "solvency.assessment",
        "growth.assessment",
        "operation.assessment",
        "anomalies.risk_level",
        "valuation.平均内在价值",
        "valuation.当前价格",
        "valuation.建议买入价",
        "valuation.投资结论",
    }
    generic: dict[str, str] = {}
    for key, value in facts_by_key.items():
        if key in handled or key.startswith("step:"):
            continue
        if not value:
            continue
        generic[key] = value
        if len(generic) >= 6:
            break
    return generic


def _skill_step_lines(facts_by_key: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for key, value in facts_by_key.items():
        if not key.startswith("step:"):
            continue
        step = key.split(":", 1)[1]
        lines.append(f"{step} exit_code {value}")
    return lines


def _safe_tool_result_snippets(prompt_messages: list[Any]) -> list[str]:
    forbidden_markers = (
        "run_id",
        "command",
        "stdout_truncated",
        "stderr_truncated",
        "outputs_truncated",
        "sandbox",
        "exit_code",
        "cwd",
        "duration_ms",
        "工具 ",
    )
    safe: list[str] = []
    for snippet in _tool_result_snippets(prompt_messages):
        normalized = str(snippet or "").strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if any(marker in lowered for marker in forbidden_markers):
            continue
        safe.append(normalized)
    return list(dict.fromkeys(safe))


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
    latest_turn = _latest_turn_messages(prompt_messages)
    latest_user = _latest_human_message_text(latest_turn)
    relevant_web_call_ids = relevant_web_tool_call_ids(latest_turn, user_query=latest_user)
    snippets.extend(
        evidence_bundle_source_snippets(
            normalize_evidence_bundle(latest_turn, user_query=latest_user)
        )
    )
    pending_calls: dict[str, dict[str, Any]] = {}
    for message in latest_turn:
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
        prompt_payload = _prompt_observation_payload(message)

        call_id = str(getattr(message, "tool_call_id", "") or "")
        call = pending_calls.pop(call_id, None)
        if (
            relevant_web_call_ids is not None
            and call_id not in relevant_web_call_ids
            and (
                (call is not None and str(call.get("name") or "") in {"web_search", "web_fetch"})
                or (
                    call is None
                    and (
                        _looks_like_web_observation_payload(payload)
                        or _looks_like_web_observation_payload(prompt_payload)
                    )
                )
            )
        ):
            continue
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
                    context = result.get("context")
                    if path and line_number:
                        snippets.append(f"- {path}:{line_number} {_truncate_inline(line)}")
                        if context:
                            snippets.append(
                                f"- {path}:{line_number} context: {_truncate_inline(context, max_chars=360)}"
                            )
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
        if isinstance(prompt_payload, dict):
            refs = prompt_payload.get("refs")
            if isinstance(refs, list):
                for ref in refs[:8]:
                    if ref:
                        snippets.append(f"- 来源：{_truncate_inline(ref)}")
            results = prompt_payload.get("results")
            if isinstance(results, list):
                for result in results[:8]:
                    if not isinstance(result, dict):
                        continue
                    ref = str(result.get("ref") or "").strip()
                    if ref:
                        snippets.append(f"- 来源：{_truncate_inline(ref)}")
                        continue
                    path = result.get("path")
                    line_number = result.get("line_number")
                    if path and line_number:
                        snippets.append(f"- {path}:{line_number}")
                    elif path:
                        snippets.append(f"- {path}")
        elif not isinstance(payload, dict) and raw:
            snippets.append(f"- {_truncate_inline(raw)}")

    return list(dict.fromkeys(snippets))


def _should_replace_unfound_workspace_answer(answer: str, source_messages: list[Any]) -> bool:
    answer_text = " ".join(str(answer or "").lower().split())
    if not answer_text or not any(marker in answer_text for marker in _UNFOUND_ANSWER_MARKERS):
        return False

    latest_turn = _latest_turn_messages(source_messages)
    positive_result_seen = False
    requested_terms = _workspace_lookup_terms(_latest_human_message_text(latest_turn))
    for message in latest_turn:
        if not isinstance(message, ToolMessage):
            continue
        raw = _message_text(message)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        if not isinstance(payload, dict):
            continue
        results = payload.get("results")
        if isinstance(results, list) and results:
            return True
        content = str(payload.get("content") or "")
        if content and requested_terms and any(term in content for term in requested_terms):
            positive_result_seen = True
    return positive_result_seen


def _workspace_lookup_terms(text: str) -> set[str]:
    terms = {
        token
        for token in re.findall(r"(?<![\w.])\.?[A-Za-z_][A-Za-z0-9_]{2,}(?![\w.])", text)
        if "/" not in token and token not in {"src", "py"}
    }
    return terms


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
    return AIMessage(content=_degraded_answer_from_tool_results(prompt_messages))


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
    "_degraded_answer_from_tool_results",
    "_fallback_web_answer_from_tool_results",
    "_latest_relevant_web_payloads",
    "_looks_like_live_web_fallback_payload",
    "_web_payload_main_answer",
    "_looks_like_internal_web_summary",
    "_looks_like_weather_query",
    "_contains_weather_marker",
    "_chinese_weather_summary_from_payloads",
    "_extract_concise_weather_text",
    "_first_result_text",
    "_web_payload_sources",
    "_reference_sources",
    "_payload_results",
    "_source_domain",
    "_tool_call_args_summary",
    "_tool_runtime_summary",
    "_tool_observation_summary",
    "_tool_result_snippets",
    "_looks_like_web_observation_payload",
    "_prompt_observation_payload",
    "_tool_result_synthesis_prompt",
    "_should_replace_unfound_workspace_answer",
    "_has_tool_result_messages",
    "_tool_result_fallback_message",
    "_invoke_tool_result_synthesis",
    "_invoke_with_tool_result_fallback",
]
