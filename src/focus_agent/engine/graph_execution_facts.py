from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from langchain.messages import AIMessage, ToolMessage


def skill_execution_evidence_facts(
    messages: Sequence[Any],
    *,
    required_tools: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Extract high-signal facts from skill execution tool observations."""

    required = {str(item) for item in required_tools if str(item)}
    call_names_by_id: dict[str, str] = {}
    facts: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, AIMessage):
            for call in getattr(message, "tool_calls", None) or ():
                if not isinstance(call, Mapping):
                    continue
                call_id = str(call.get("id") or "").strip()
                name = str(call.get("name") or "").strip()
                if call_id and name:
                    call_names_by_id[call_id] = name
            continue
        if not isinstance(message, ToolMessage):
            continue
        tool_name = call_names_by_id.get(str(message.tool_call_id or "").strip(), "")
        if required and tool_name not in required and tool_name != "read_file":
            continue
        if tool_name and not _tool_message_counts_as_success(message, tool_name):
            continue
        payload = _json_message_payload(message)
        if not isinstance(payload, Mapping):
            continue
        if tool_name == "run_skill_entrypoint" or payload.get("skill_id") or payload.get("run_id"):
            facts.extend(_facts_from_skill_entrypoint_payload(payload))
        if tool_name == "read_file" or payload.get("path"):
            facts.extend(_facts_from_read_file_payload(payload))
        if tool_name in required:
            facts.extend(_facts_from_generic_tool_payload(tool_name, payload))
    return _dedupe_facts(facts)


def _tool_message_counts_as_success(message: ToolMessage, tool_name: str) -> bool:
    status = str(getattr(message, "status", "success") or "success").strip().lower()
    if status != "success":
        return False
    if tool_name == "run_workspace_command":
        return _run_workspace_command_payload_succeeded(message)
    if tool_name == "run_skill_entrypoint":
        return _run_skill_entrypoint_payload_succeeded(message)
    return True


def _run_workspace_command_payload_succeeded(message: ToolMessage) -> bool:
    content = getattr(message, "content", "")
    if not isinstance(content, str):
        return True
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return True
    if not isinstance(payload, Mapping):
        return True
    if payload.get("fallback_used") is True:
        return False
    sandbox_backend = str(payload.get("sandbox_backend") or "").strip().lower()
    if sandbox_backend.startswith("local"):
        return False
    if payload.get("timed_out") is True:
        return False
    status = str(payload.get("status") or "").strip().lower()
    if status in {"error", "failed", "failure"}:
        return False
    if payload.get("error"):
        return False
    for key in ("ok", "success"):
        if payload.get(key) is False:
            return False
    for key in ("stdout", "stderr", "output"):
        if _embedded_command_payload_failed(payload.get(key)):
            return False
    if "exit_code" not in payload:
        return True
    try:
        return int(payload.get("exit_code")) == 0
    except (TypeError, ValueError):
        return False


def _embedded_command_payload_failed(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, Mapping):
        return False
    status = str(payload.get("status") or "").strip().lower()
    if status in {"error", "failed", "failure"}:
        return True
    if payload.get("error"):
        return True
    for key in ("ok", "success"):
        if payload.get(key) is False:
            return True
    return False


def _run_skill_entrypoint_payload_succeeded(message: ToolMessage) -> bool:
    content = getattr(message, "content", "")
    if not isinstance(content, str):
        return False
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, Mapping):
        return False
    if payload.get("timed_out") is not False:
        return False
    if payload.get("fallback_used") is True:
        return False
    sandbox_backend = str(payload.get("sandbox_backend") or "").strip().lower()
    if sandbox_backend.startswith("local"):
        return False
    status = str(payload.get("status") or "").strip().lower()
    if status != "completed":
        return False
    try:
        return int(payload.get("exit_code")) == 0
    except (TypeError, ValueError):
        return False


def _json_message_payload(message: ToolMessage) -> Any:
    content = getattr(message, "content", "")
    if not isinstance(content, str):
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def _facts_from_skill_entrypoint_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for key in ("run_id", "skill_id", "entrypoint", "status"):
        value = _clean_fact_value(payload.get(key))
        if value:
            facts.append(_fact(key, value))
    stdout = payload.get("stdout")
    if isinstance(stdout, str):
        try:
            stdout_payload = json.loads(stdout)
        except json.JSONDecodeError:
            stdout_payload = None
        if isinstance(stdout_payload, Mapping):
            facts.extend(_facts_from_skill_summary(stdout_payload))
    return facts


def _facts_from_read_file_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    path = _clean_fact_value(payload.get("path"))
    content = payload.get("content")
    if not isinstance(content, str):
        return []
    parsed = _parse_line_numbered_json(content)
    if not isinstance(parsed, Mapping):
        return []
    if path.endswith("summary.json"):
        return _facts_from_skill_summary(parsed)
    if path.endswith("financial_analysis.json"):
        return _facts_from_financial_analysis(parsed)
    if path.endswith("valuation.json"):
        return _facts_from_valuation(parsed)
    return []


def _facts_from_generic_tool_payload(
    tool_name: str, payload: Mapping[str, Any]
) -> list[dict[str, Any]]:
    payload_facts: list[dict[str, Any]] = []
    for key, value in payload.items():
        normalized_key = _clean_fact_value(key)
        if not normalized_key or normalized_key in {"stdout", "stderr"}:
            continue
        normalized_value = _clean_fact_value(value)
        if not normalized_value:
            continue
        if len(normalized_value) > 240:
            normalized_value = f"{normalized_value[:239]}…"
        payload_facts.append(_fact(normalized_key, normalized_value))
        if len(payload_facts) >= 10:
            break
    stdout = payload.get("stdout")
    if isinstance(stdout, str):
        stdout_fact = _clean_fact_value(stdout)
        if stdout_fact:
            if len(stdout_fact) > 240:
                stdout_fact = f"{stdout_fact[:239]}…"
            payload_facts.append(_fact("stdout", stdout_fact))
    normalized_tool = _clean_fact_value(tool_name)
    if normalized_tool and payload_facts:
        return [_fact("tool", normalized_tool, label="tool"), *payload_facts]
    return payload_facts


def _facts_from_skill_summary(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for key in ("status", "code", "years", "generated_at"):
        value = _clean_fact_value(payload.get(key))
        if value:
            facts.append(_fact(key, value))
            if key == "generated_at" and "T" in value:
                facts.append(_fact("generated_date", value.split("T", 1)[0]))
    for step in payload.get("steps") or []:
        if not isinstance(step, Mapping):
            continue
        name = _clean_fact_value(step.get("name"))
        exit_code = _clean_fact_value(step.get("exit_code"))
        if name and exit_code:
            facts.append(_fact(f"step:{name}", exit_code, label=f"{name} exit_code"))
    return facts


def _facts_from_financial_analysis(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for key in ("code", "name", "analysis_date", "score"):
        value = _clean_fact_value(payload.get(key))
        if value:
            facts.append(_fact(key, value))
            if key == "analysis_date" and "T" in value:
                facts.append(_fact("analysis_date", value.split("T", 1)[0]))
    sections = {
        "profitability": ("assessment", "盈利能力"),
        "solvency": ("assessment", "偿债能力"),
        "growth": ("assessment", "成长性"),
        "operation": ("assessment", "运营效率"),
        "anomalies": ("risk_level", "风险等级"),
    }
    for section_key, (field, label) in sections.items():
        section = payload.get(section_key)
        if isinstance(section, Mapping):
            value = _clean_fact_value(section.get(field))
            if value:
                facts.append(_fact(f"{section_key}.{field}", value, label=label))
    profitability = payload.get("profitability")
    if isinstance(profitability, Mapping):
        metrics = profitability.get("metrics")
        if isinstance(metrics, Mapping):
            for key in ("当前ROE", "当前ROA", "当前毛利率", "当前净利率"):
                value = _clean_fact_value(metrics.get(key))
                if value:
                    facts.append(_fact(f"profitability.metrics.{key}", value, label=key))
    return facts


def _facts_from_valuation(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    summary = payload.get("summary") or payload.get("估值汇总")
    if not isinstance(summary, Mapping):
        return []
    facts: list[dict[str, Any]] = []
    for key in ("平均内在价值", "当前价格", "建议买入价", "投资结论", "估值方法数"):
        value = _clean_fact_value(summary.get(key))
        if value:
            facts.append(_fact(f"valuation.{key}", value, label=key))
    safety = summary.get("安全边际分析")
    if isinstance(safety, Mapping):
        conclusion = _clean_fact_value(safety.get("conclusion"))
        if conclusion:
            facts.append(_fact("valuation.safety_conclusion", conclusion, label="安全边际"))
    return facts


def _parse_line_numbered_json(content: str) -> Any:
    lines: list[str] = []
    for raw_line in content.splitlines():
        line = re.sub(r"^\s*\d+\s*\|\s?", "", raw_line)
        lines.append(line)
    text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _fact(key: str, value: str, *, label: str | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "label": label or key,
        "value": value,
        "phrases": _fact_phrases(label or key, value),
    }


def _fact_phrases(label: str, value: str) -> list[str]:
    compact_label = str(label or "").strip()
    compact_value = str(value or "").strip()
    phrases: list[str] = []
    if _value_is_strong_standalone(compact_label, compact_value):
        phrases.append(compact_value)
    if compact_label and compact_value:
        phrases.extend(
            [
                f"{compact_label} {compact_value}",
                f"{compact_label}: {compact_value}",
                f"{compact_label}：{compact_value}",
            ]
        )
    if compact_label == "score":
        phrases.extend(
            [f"评分 {compact_value}", f"财务评分 {compact_value}", f"综合得分 {compact_value}"]
        )
    return list(dict.fromkeys(phrase for phrase in phrases if phrase))


def _value_is_strong_standalone(label: str, value: str) -> bool:
    if label in {"run_id", "generated_date", "analysis_date"}:
        return True
    if not value:
        return False
    if re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return False
    return len(value) >= 6


def _clean_fact_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return " ".join(str(value).strip().split())


def _dedupe_facts(facts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for fact in facts:
        key = str(fact.get("key") or "").strip()
        value = str(fact.get("value") or "").strip()
        if not key or not value:
            continue
        marker = (key, value)
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(dict(fact))
    return deduped[:40]


def _answer_mentions_skill_fact(answer: str, facts: Sequence[Mapping[str, Any]]) -> bool:
    normalized_answer = _normalize_fact_text(answer)
    for fact in facts:
        for raw_phrase in fact.get("phrases") or ():
            phrase = str(raw_phrase or "").strip()
            if not phrase:
                continue
            normalized_phrase = _normalize_fact_text(phrase)
            if normalized_phrase and normalized_phrase in normalized_answer:
                return True
    return False


def _normalize_fact_text(value: str) -> str:
    return re.sub(r"[\s:：,，。；;、()（）\\[\\]【】\"'`]+", "", str(value or "").lower())


__all__ = ["skill_execution_evidence_facts"]
