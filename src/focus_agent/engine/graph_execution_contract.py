from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from langchain.messages import AIMessage, ToolMessage

ContractStatus = Literal["not_required", "missing_required_tools", "satisfied", "blocked"]
VerificationStatus = Literal["verified", "unsupported", "contradicted", "not_required", "blocked"]


def build_execution_contract(
    *,
    policy: str,
    temporal_anchor_required: bool = False,
    available_tool_names: Sequence[str] = (),
    preferred_first_tool: str | None = None,
    required_evidence: bool | None = None,
    skill_execution_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a small per-turn execution contract from the current tool policy."""

    normalized_policy = str(policy or "").strip()
    if normalized_policy == "execution" and isinstance(skill_execution_plan, Mapping):
        selected_skill_ids = [
            str(item).strip()
            for item in skill_execution_plan.get("selected_skill_ids") or []
            if str(item).strip()
        ]
        primary_tools = [
            str(item).strip()
            for item in skill_execution_plan.get("primary_tools") or []
            if str(item).strip()
        ]
        if selected_skill_ids and primary_tools:
            available = {str(name) for name in available_tool_names if str(name)}
            if "run_skill_entrypoint" in primary_tools:
                required_tools = ["run_skill_entrypoint"]
            else:
                required_tool = next((name for name in primary_tools if name in available), None)
                required_tools = [required_tool or primary_tools[0]]
            return {
                "policy": "skill_execution",
                "selected_skill_ids": selected_skill_ids,
                "required_tools": required_tools,
                "required_evidence": True if required_evidence is None else bool(required_evidence),
                "temporal_anchor_required": False,
                "status": "missing_required_tools",
                "missing": list(required_tools),
                "blocked_reason": "",
                "skill_execution_plan": dict(skill_execution_plan),
            }

    if normalized_policy != "live_web_research":
        return {
            "policy": normalized_policy or "direct_answer",
            "required_tools": [],
            "required_evidence": False,
            "temporal_anchor_required": False,
            "status": "not_required",
            "missing": [],
            "blocked_reason": "",
        }

    required_tools: list[str] = []
    available = {str(name) for name in available_tool_names if str(name)}
    if temporal_anchor_required and "current_utc_time" in available:
        required_tools.append("current_utc_time")
    if preferred_first_tool == "web_fetch" and "web_fetch" in available:
        required_tools.append("web_fetch")
    elif "web_search" in available:
        required_tools.append("web_search")
    return {
        "policy": normalized_policy,
        "required_tools": required_tools,
        "required_evidence": True if required_evidence is None else bool(required_evidence),
        "temporal_anchor_required": bool(temporal_anchor_required),
        "status": "missing_required_tools",
        "missing": list(required_tools),
        "blocked_reason": "",
    }


def evaluate_execution_contract(
    contract: Mapping[str, Any],
    *,
    tool_results_seen: Iterable[str],
    evidence_ledger: Sequence[Mapping[str, Any]] = (),
    available_tool_names: Sequence[str] = (),
    observed_at: str | None = None,
    user_query: str | None = None,
    skill_evidence_facts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    required_tools = [str(item) for item in contract.get("required_tools") or [] if str(item)]
    seen = {str(item) for item in tool_results_seen if str(item)}
    missing = [name for name in required_tools if name not in seen]
    available = {str(item) for item in available_tool_names if str(item)}
    blocked = [name for name in missing if name not in available]
    required_evidence = bool(contract.get("required_evidence"))
    policy = str(contract.get("policy") or "")
    has_evidence = (
        bool(skill_evidence_facts) if policy == "skill_execution" else bool(evidence_ledger)
    )
    status: ContractStatus
    blocked_reason = ""
    if policy not in {"live_web_research", "skill_execution"}:
        status = "not_required"
    elif blocked:
        status = "blocked"
        blocked_reason = f"Required tool unavailable: {', '.join(blocked)}"
    elif missing or (required_evidence and not has_evidence):
        status = "missing_required_tools"
    else:
        status = "satisfied"
    return {
        **dict(contract),
        "status": status,
        "missing": missing,
        "blocked_reason": blocked_reason,
        "required_evidence": required_evidence,
        "evidence_count": len(evidence_ledger),
        "skill_evidence_facts": [dict(item) for item in skill_evidence_facts],
        "observed_at": observed_at or str(contract.get("observed_at") or ""),
        "user_query": user_query or str(contract.get("user_query") or ""),
    }


def verify_answer_against_evidence(
    *,
    answer: str,
    contract: Mapping[str, Any] | None = None,
    evidence_ledger: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    contract_status = str((contract or {}).get("status") or "not_required")
    policy = str((contract or {}).get("policy") or "")
    if policy not in {"live_web_research", "skill_execution"}:
        return _verification("not_required", required_tools_satisfied=True)
    if contract_status == "blocked":
        return _verification(
            "blocked",
            required_tools_satisfied=False,
            unsupported_claims=[f"{policy} contract is blocked"],
            repair_action="answer_with_uncertainty",
        )
    if contract_status != "satisfied":
        missing = [str(item) for item in (contract or {}).get("missing") or [] if str(item)]
        repair_action = (
            "fallback_to_tool_results"
            if policy == "skill_execution" and not missing
            else "call_missing_tool"
        )
        return _verification(
            "unsupported",
            required_tools_satisfied=False,
            unsupported_claims=[f"{policy} contract is missing required tools or evidence"],
            repair_action=repair_action,
        )
    if policy == "skill_execution":
        facts = [
            dict(item)
            for item in (contract or {}).get("skill_evidence_facts") or []
            if isinstance(item, Mapping)
        ]
        stripped_answer = str(answer or "").strip()
        if facts and stripped_answer and not _answer_mentions_skill_fact(stripped_answer, facts):
            return _verification(
                "unsupported",
                required_tools_satisfied=True,
                unsupported_claims=[
                    "skill_execution answer does not reference the latest skill tool observation"
                ],
                repair_action="fallback_to_tool_results",
            )
        return _verification("verified", required_tools_satisfied=True)
    stale_reason = _stale_evidence_reason(contract or {}, evidence_ledger)
    if stale_reason:
        return _verification(
            "unsupported",
            required_tools_satisfied=True,
            unsupported_claims=[stale_reason],
            repair_action="refresh_stale_evidence",
            stale_evidence=True,
        )
    stripped_answer = str(answer or "").strip()
    if not stripped_answer:
        return _verification("verified", required_tools_satisfied=True)
    if evidence_ledger and _is_low_information_live_answer(stripped_answer):
        return _verification(
            "unsupported",
            required_tools_satisfied=True,
            unsupported_claims=[
                "live_web_research answer is only an acknowledgement despite available evidence"
            ],
            repair_action="fallback_to_tool_results",
        )
    if evidence_ledger and _denies_available_live_evidence(stripped_answer):
        return _verification(
            "unsupported",
            required_tools_satisfied=True,
            unsupported_claims=["live_web_research answer denies available search evidence"],
            repair_action="fallback_to_tool_results",
        )
    contradiction = _detect_simple_event_contradiction(stripped_answer, evidence_ledger)
    if contradiction:
        return _verification(
            "contradicted",
            required_tools_satisfied=True,
            contradictions=[contradiction],
            repair_action="revise_answer_from_evidence",
        )
    return _verification("verified", required_tools_satisfied=True)


def tool_result_names(messages: Sequence[Any]) -> list[str]:
    call_names_by_id: dict[str, str] = {}
    names: list[str] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or ():
            if not isinstance(call, Mapping):
                continue
            call_id = str(call.get("id") or "").strip()
            name = str(call.get("name") or "").strip()
            if call_id and name:
                call_names_by_id[call_id] = name
        if isinstance(message, ToolMessage):
            name = call_names_by_id.get(str(message.tool_call_id or "").strip())
            if name and _tool_message_counts_as_success(message, name):
                names.append(name)
    return names


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


def _facts_from_generic_tool_payload(tool_name: str, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
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
        phrases.extend([f"评分 {compact_value}", f"财务评分 {compact_value}", f"综合得分 {compact_value}"])
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


def _verification(
    status: VerificationStatus,
    *,
    required_tools_satisfied: bool,
    supported_claims: Sequence[str] = (),
    unsupported_claims: Sequence[str] = (),
    contradictions: Sequence[str] = (),
    repair_action: str = "",
    stale_evidence: bool = False,
) -> dict[str, Any]:
    return {
        "status": status,
        "required_tools_satisfied": required_tools_satisfied,
        "supported_claims": list(supported_claims),
        "unsupported_claims": list(unsupported_claims),
        "contradictions": list(contradictions),
        "repair_action": repair_action,
        "stale_evidence": stale_evidence,
    }


def _stale_evidence_reason(
    contract: Mapping[str, Any],
    evidence_ledger: Sequence[Mapping[str, Any]],
) -> str:
    if str(contract.get("policy") or "") != "live_web_research":
        return ""
    query = str(contract.get("user_query") or "").strip()
    if not (bool(contract.get("temporal_anchor_required")) or _query_needs_fresh_evidence(query)):
        return ""
    observed_at = _parse_date(str(contract.get("observed_at") or ""))
    if observed_at is None:
        return ""
    min_fresh_date = _fresh_evidence_min_date(query, observed_at)
    stale_items: list[str] = []
    dated_items = 0
    fresh_items = 0
    for item in evidence_ledger:
        if not isinstance(item, Mapping):
            continue
        item_date = _parse_date(str(item.get("published_at") or item.get("observed_at") or ""))
        if item_date is None:
            continue
        dated_items += 1
        if item_date >= min_fresh_date:
            fresh_items += 1
            continue
        label = str(item.get("title") or item.get("source_name") or item.get("url") or "evidence")
        stale_items.append(f"{label} ({item_date.isoformat()})")
    if dated_items and not fresh_items:
        stale_summary = "; ".join(stale_items[:3])
        return (
            "live_web_research evidence is stale for the requested time window"
            f" (fresh from {min_fresh_date.isoformat()}; stale evidence: {stale_summary})"
        )
    return ""


def _fresh_evidence_min_date(query: str, observed_at: date) -> date:
    lowered = query.lower()
    if _contains_temporal_marker(
        lowered, ("近一周", "最近一周", "过去一周", "last 7 days", "past week")
    ):
        return observed_at - timedelta(days=6)
    if re.search(r"(?<![a-z0-9_])recent(?:ly)?(?![a-z0-9_])", lowered):
        return observed_at - timedelta(days=6)
    if _contains_temporal_marker(lowered, ("本周", "这周", "this week")):
        return observed_at - timedelta(days=observed_at.weekday())
    if _contains_temporal_marker(lowered, ("昨天", "yesterday")):
        return observed_at - timedelta(days=1)
    return observed_at


def _query_needs_fresh_evidence(query: str) -> bool:
    lowered = query.lower()
    return bool(
        _contains_temporal_marker(
            lowered,
            (
                "今天",
                "明天",
                "昨天",
                "本周",
                "这周",
                "近一周",
                "最近",
                "近期",
                "today",
                "tomorrow",
                "yesterday",
                "this week",
                "recent",
                "current",
                "now",
            ),
        )
    )


def _contains_temporal_marker(lowered_text: str, markers: Sequence[str]) -> bool:
    for marker in markers:
        normalized = marker.strip().lower()
        if not normalized:
            continue
        if re.fullmatch(r"[a-z0-9]+(?:\s+[a-z0-9]+)*", normalized):
            pattern = (
                r"(?<![a-z0-9_])"
                + r"\s+".join(re.escape(part) for part in normalized.split())
                + r"(?![a-z0-9_])"
            )
            if re.search(pattern, lowered_text):
                return True
            continue
        if normalized in lowered_text:
            return True
    return False


def _parse_date(value: str) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).date()
    except ValueError:
        match = re.search(r"\d{4}-\d{2}-\d{2}", text)
        if not match:
            return None
        try:
            return date.fromisoformat(match.group(0))
        except ValueError:
            return None


def _detect_simple_event_contradiction(
    answer: str,
    evidence_ledger: Sequence[Mapping[str, Any]],
) -> str:
    answer_text = _normalize_text(answer)
    if not _contains_negative_visit_claim(answer_text):
        return ""
    evidence_text = _normalize_text(
        " ".join(
            str(item.get(key) or "")
            for item in evidence_ledger
            if isinstance(item, Mapping)
            for key in ("title", "snippet", "source_name")
        )
    )
    if not evidence_text:
        return ""
    has_visit_event = re.search(
        r"\b(visit|visits|visited|visiting|welcome|welcomes|met|meeting)\b",
        evidence_text,
    ) or any(token in evidence_text for token in ("访问", "访华", "会见", "欢迎", "到访"))
    has_leader = any(
        token in evidence_text
        for token in (
            "trump",
            "xi",
            "president",
            "leader",
            "习近平",
            "特朗普",
            "总统",
            "领导人",
        )
    )
    if has_visit_event and has_leader:
        return (
            "Answer denies a leader visit, but the evidence contains leader-visit event language."
        )
    return ""


def _is_low_information_live_answer(answer: str) -> bool:
    normalized = re.sub(r"[\s,，.。!！?？;；:：、]+", "", str(answer or "").strip()).lower()
    return normalized in {
        "ok",
        "okay",
        "yes",
        "done",
        "好",
        "好的",
        "可以",
        "收到",
        "明白",
        "嗯",
        "嗯嗯",
        "是",
        "是的",
    }


def _denies_available_live_evidence(answer: str) -> bool:
    normalized = _normalize_text(answer)
    compact = re.sub(r"[\s,，.。!！?？;；:：、]+", "", str(answer or "").strip()).lower()
    chinese_markers = (
        "搜索结果未能提取",
        "检索结果未能提取",
        "搜索结果未返回",
        "检索结果未返回",
        "搜索结果没有提供",
        "检索结果没有提供",
        "未能提取到",
        "无法列出确切",
        "无法列出具体",
        "无法给出确切",
        "无法给出具体",
        "没有具体新闻内容",
        "没有具体内容",
        "证据不足以支撑",
    )
    if any(marker in compact for marker in chinese_markers):
        return True
    english_patterns = (
        r"\b(search|web|retrieval|results?|evidence)\b.{0,80}\b("
        r"could not|couldn't|did not|didn't|failed to|unable to|no|not enough"
        r")\b.{0,80}\b(extract|provide|find|list|confirm|support|content|details?)\b",
        r"\b(unable to|cannot|can't|could not|couldn't)\b.{0,80}\b("
        r"list|provide|confirm|extract"
        r")\b.{0,80}\b(news|events?|details?|content)\b",
    )
    return any(re.search(pattern, normalized) for pattern in english_patterns)


def _contains_negative_visit_claim(text: str) -> bool:
    negative_patterns = (
        r"\b(no|not|none|neither|without)\b.{0,40}\b(visit|visiting|visited|leader|president)\b",
        r"\b(no|not|none|neither|without)\b.{0,40}\b(leaders?|presidents?)\b.{0,40}\b(visit|visiting|visited)\b",
    )
    if any(re.search(pattern, text) for pattern in negative_patterns):
        return True
    return any(
        phrase in text
        for phrase in (
            "没有领导人访问",
            "没有总统访问",
            "无人访问",
            "无领导人访问",
            "没有访华",
            "没有到访",
        )
    )


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").lower().split())


__all__ = [
    "build_execution_contract",
    "evaluate_execution_contract",
    "tool_result_names",
    "verify_answer_against_evidence",
]
