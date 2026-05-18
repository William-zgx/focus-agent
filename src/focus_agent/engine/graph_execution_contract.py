from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from langchain.messages import ToolMessage

ContractStatus = Literal["not_required", "missing_required_tools", "satisfied", "blocked"]
VerificationStatus = Literal["verified", "unsupported", "contradicted", "not_required", "blocked"]


def build_execution_contract(
    *,
    policy: str,
    temporal_anchor_required: bool = False,
    available_tool_names: Sequence[str] = (),
    required_evidence: bool | None = None,
) -> dict[str, Any]:
    """Build a small per-turn execution contract from the current tool policy."""

    normalized_policy = str(policy or "").strip()
    if normalized_policy != "live_web_research":
        return {
            "policy": normalized_policy or "direct_answer",
            "required_tools": [],
            "required_evidence": False,
            "status": "not_required",
            "missing": [],
            "blocked_reason": "",
        }

    required_tools: list[str] = []
    available = {str(name) for name in available_tool_names if str(name)}
    if temporal_anchor_required and "current_utc_time" in available:
        required_tools.append("current_utc_time")
    if "web_search" in available:
        required_tools.append("web_search")
    return {
        "policy": normalized_policy,
        "required_tools": required_tools,
        "required_evidence": True if required_evidence is None else bool(required_evidence),
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
) -> dict[str, Any]:
    required_tools = [str(item) for item in contract.get("required_tools") or [] if str(item)]
    seen = {str(item) for item in tool_results_seen if str(item)}
    missing = [name for name in required_tools if name not in seen]
    available = {str(item) for item in available_tool_names if str(item)}
    blocked = [name for name in missing if name not in available]
    required_evidence = bool(contract.get("required_evidence"))
    has_evidence = bool(evidence_ledger)
    status: ContractStatus
    blocked_reason = ""
    if str(contract.get("policy") or "") != "live_web_research":
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
    }


def verify_answer_against_evidence(
    *,
    answer: str,
    contract: Mapping[str, Any] | None = None,
    evidence_ledger: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    contract_status = str((contract or {}).get("status") or "not_required")
    policy = str((contract or {}).get("policy") or "")
    if policy != "live_web_research":
        return _verification("not_required", required_tools_satisfied=True)
    if contract_status == "blocked":
        return _verification(
            "blocked",
            required_tools_satisfied=False,
            unsupported_claims=["live_web_research contract is blocked"],
            repair_action="answer_with_uncertainty",
        )
    if contract_status != "satisfied":
        return _verification(
            "unsupported",
            required_tools_satisfied=False,
            unsupported_claims=["live_web_research contract is missing required tools or evidence"],
            repair_action="call_missing_tool",
        )
    stripped_answer = str(answer or "").strip()
    if not stripped_answer:
        return _verification("verified", required_tools_satisfied=True)
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
            if name:
                names.append(name)
    return names


def _verification(
    status: VerificationStatus,
    *,
    required_tools_satisfied: bool,
    supported_claims: Sequence[str] = (),
    unsupported_claims: Sequence[str] = (),
    contradictions: Sequence[str] = (),
    repair_action: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "required_tools_satisfied": required_tools_satisfied,
        "supported_claims": list(supported_claims),
        "unsupported_claims": list(unsupported_claims),
        "contradictions": list(contradictions),
        "repair_action": repair_action,
    }


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
        return "Answer denies a leader visit, but the evidence contains leader-visit event language."
    return ""


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
