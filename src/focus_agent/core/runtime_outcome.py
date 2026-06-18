from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from langchain.messages import AIMessage, ToolMessage

ToolOutcomeStatus = Literal["succeeded", "failed", "recovered", "blocked", "skipped"]
TaskOutcomeStatus = Literal["answered", "degraded_answer", "blocked", "failed"]

TOOL_OUTCOME_STATUSES: tuple[ToolOutcomeStatus, ...] = (
    "succeeded",
    "failed",
    "recovered",
    "blocked",
    "skipped",
)
TASK_OUTCOME_STATUSES: tuple[TaskOutcomeStatus, ...] = (
    "answered",
    "degraded_answer",
    "blocked",
    "failed",
)

_RETRYABLE_ERROR_CATEGORIES = frozenset({"timeout", "network", "execution_error"})
_BLOCKED_RUNTIME_FLAGS = frozenset(
    {
        "tool_approval_pending",
        "tool_approval_denied",
        "tool_approval_invalid",
        "forbidden_by_tool_router",
        "memory_context_authorization_failed",
        "parameter_validation_error",
        "validation_failed",
        "missing_tool_runtime_metadata",
        "malformed_tool_call",
        "max_calls_per_turn_exceeded",
    }
)
_SKIPPED_RUNTIME_FLAGS = frozenset({"duplicate_tool_call_suppressed"})
_NETWORK_MARKERS = (
    "failed to fetch",
    "connection",
    "network",
    "dns",
    "temporar",
    "timed out",
    "timeout",
    "http 5",
    "502",
    "503",
    "504",
)
_BUSINESS_FAILURE_STATUSES = frozenset({"error", "failed", "failure", "cancelled", "canceled"})


def build_tool_outcomes_from_messages(
    messages: Sequence[Any],
    *,
    prior_outcomes: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Derive authoritative ToolOutcome records from AI tool calls and ToolMessages."""

    call_names_by_id: dict[str, str] = {}
    outcomes: list[dict[str, Any]] = []
    for message in messages or ():
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
        outcome = tool_outcome_from_message(
            message,
            call_names_by_id=call_names_by_id,
            prior_outcomes=[*prior_outcomes, *outcomes],
        )
        outcomes.append(outcome)
    return outcomes


def tool_outcome_from_message(
    message: ToolMessage,
    *,
    call_names_by_id: Mapping[str, str] | None = None,
    prior_outcomes: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    tool_call_id = str(getattr(message, "tool_call_id", "") or "").strip()
    artifact = getattr(message, "artifact", None)
    artifact_mapping = artifact if isinstance(artifact, Mapping) else {}
    runtime = artifact_mapping.get("runtime")
    runtime_info = dict(runtime or {}) if isinstance(runtime, Mapping) else {}
    tool_name = (
        str(artifact_mapping.get("tool_name") or "").strip()
        or str(getattr(message, "name", "") or "").strip()
        or str((call_names_by_id or {}).get(tool_call_id) or "").strip()
        or "unknown_tool"
    )
    payload = _message_payload(message)
    status, error_category, error_message = _classify_tool_message(
        message=message,
        payload=payload,
        runtime_info=runtime_info,
    )
    fallback_group = _string_or_none(runtime_info.get("fallback_group"))
    fallback_used = bool(runtime_info.get("fallback_used") or fallback_group)
    recovery_of_tool_call_id = ""
    prior_failed = _latest_prior_failure(
        prior_outcomes,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        same_call_only=bool(tool_call_id and not fallback_used),
    )
    if status == "succeeded" and (fallback_used or prior_failed):
        status = "recovered"
        recovery_of_tool_call_id = str(prior_failed.get("tool_call_id") or "") if prior_failed else ""
    retryable = _is_retryable(error_category=error_category, message=error_message)
    attempt_index = _attempt_index(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        runtime_info=runtime_info,
        prior_outcomes=prior_outcomes,
    )
    max_attempts = 2 if retryable or status in {"failed", "recovered"} else max(1, attempt_index)
    outcome_id = f"{tool_call_id or tool_name}:{attempt_index}"
    return {
        "outcome_id": outcome_id,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "status": status,
        "attempt_index": attempt_index,
        "max_attempts": max_attempts,
        "retryable": retryable,
        "fallback_used": fallback_used,
        "fallback_group": fallback_group,
        "recovery_of_tool_call_id": recovery_of_tool_call_id,
        "error_category": error_category,
        "error_message": error_message,
        "evidence_role": _evidence_role(tool_name=tool_name, status=status),
        "duration_ms": _float_or_none(runtime_info.get("duration_ms")),
        "cache_hit": bool(runtime_info.get("cache_hit", False)),
    }


def build_task_outcome(
    *,
    user_goal: str,
    execution_contract: Mapping[str, Any] | None,
    answer_verification: Mapping[str, Any] | None,
    evidence_ledger: Sequence[Mapping[str, Any]] = (),
    tool_outcomes: Sequence[Mapping[str, Any]] = (),
    final_answer: str = "",
    repair_action_taken: str = "",
) -> dict[str, Any]:
    contract = dict(execution_contract or {})
    verification = dict(answer_verification or {})
    policy = str(contract.get("policy") or "direct_answer").strip() or "direct_answer"
    contract_status = str(contract.get("status") or "not_required")
    verification_status = str(verification.get("status") or "not_required")
    failed_outcomes = _unresolved_failed_outcomes(tool_outcomes)
    evidence_count = _evidence_count(contract=contract, evidence_ledger=evidence_ledger)
    final_answer_text = str(final_answer or "").strip()
    repair_action = repair_action_taken or str(verification.get("repair_action_taken") or "")
    warnings = _task_warnings(
        verification=verification,
        contract=contract,
        failed_outcomes=failed_outcomes,
    )

    if contract_status == "blocked" or verification_status == "blocked":
        status: TaskOutcomeStatus = "blocked"
        answer_basis = "blocked"
    elif not final_answer_text:
        status = "failed"
        answer_basis = "no_final_answer"
    elif _is_degraded_task(
        contract_status=contract_status,
        verification_status=verification_status,
        repair_action=repair_action,
        failed_outcomes=failed_outcomes,
        evidence_count=evidence_count,
    ):
        status = "degraded_answer"
        answer_basis = "partial_or_alternative_evidence" if evidence_count else "tool_failure"
    else:
        status = "answered"
        answer_basis = "verified_evidence" if evidence_count else "direct_answer"

    return {
        "status": status,
        "user_goal": str(user_goal or contract.get("user_query") or "").strip(),
        "policy": policy,
        "answer_basis": answer_basis,
        "repair_action_taken": repair_action,
        "degradation_reason": _degradation_reason(
            status=status,
            verification=verification,
            contract=contract,
            failed_outcomes=failed_outcomes,
        ),
        "evidence_count": evidence_count,
        "tool_outcome_ids": [
            str(item.get("outcome_id") or item.get("tool_call_id") or "")
            for item in tool_outcomes
            if str(item.get("outcome_id") or item.get("tool_call_id") or "")
        ],
        "warnings": warnings,
    }


def _classify_tool_message(
    *,
    message: ToolMessage,
    payload: Any,
    runtime_info: Mapping[str, Any],
) -> tuple[ToolOutcomeStatus, str, str]:
    runtime_flags = {key for key, value in runtime_info.items() if bool(value)}
    if runtime_flags & _SKIPPED_RUNTIME_FLAGS:
        return "skipped", "skipped", _first_runtime_reason(runtime_info)
    if runtime_flags & _BLOCKED_RUNTIME_FLAGS:
        return "blocked", _blocked_error_category(runtime_flags), _first_runtime_reason(runtime_info)

    message_status = str(getattr(message, "status", "success") or "success").strip().lower()
    if message_status in {"error", "failed"}:
        raw_message = _error_message(payload) or str(getattr(message, "content", "") or "")
        return "failed", _error_category(raw_message, runtime_info=runtime_info), raw_message

    failure = _payload_failure(payload)
    if failure is not None:
        category, error_message = failure
        return "failed", category, error_message
    return "succeeded", "none", ""


def _payload_failure(payload: Any) -> tuple[str, str] | None:
    if not isinstance(payload, Mapping):
        return None
    if payload.get("timed_out") is True:
        return "timeout", _error_message(payload) or "tool execution timed out"
    status = str(payload.get("status") or "").strip().lower()
    if status in _BUSINESS_FAILURE_STATUSES:
        return "business_error", _error_message(payload) or f"tool returned status {status}"
    if "exit_code" in payload:
        try:
            if int(payload.get("exit_code")) != 0:
                return "execution_error", _error_message(payload) or "tool command exited non-zero"
        except (TypeError, ValueError):
            return "execution_error", _error_message(payload) or "tool command exit_code invalid"
    for key in ("ok", "success"):
        if payload.get(key) is False:
            return "business_error", _error_message(payload) or f"tool returned {key}=false"
    if payload.get("error"):
        return _error_category(str(payload.get("error"))), _error_message(payload)
    for key in ("stdout", "stderr", "output"):
        embedded = _embedded_payload_failure(payload.get(key))
        if embedded is not None:
            return embedded
    return None


def _embedded_payload_failure(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        lowered = text.lower()
        if "error" in lowered and any(marker in lowered for marker in _NETWORK_MARKERS):
            return "network", _truncate_error(text)
        return None
    if not isinstance(payload, Mapping):
        return None
    failure = _payload_failure(payload)
    if failure is None:
        return None
    category, message = failure
    if category == "business_error" and any(marker in message.lower() for marker in _NETWORK_MARKERS):
        category = "network"
    return category, message


def _message_payload(message: ToolMessage) -> Any:
    content = getattr(message, "content", "")
    if not isinstance(content, str):
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def _error_message(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    for key in ("error", "message", "stderr", "stdout"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return _truncate_error(value)
    return ""


def _error_category(message: str, *, runtime_info: Mapping[str, Any] | None = None) -> str:
    runtime = runtime_info or {}
    if runtime.get("timed_out"):
        return "timeout"
    lowered = str(message or "").lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if any(marker in lowered for marker in _NETWORK_MARKERS):
        return "network"
    if "validat" in lowered or "parameter" in lowered:
        return "validation"
    if "approval" in lowered or "denied" in lowered:
        return "approval"
    return "execution_error"


def _blocked_error_category(runtime_flags: set[str]) -> str:
    if any("approval" in flag for flag in runtime_flags):
        return "approval"
    if any("validation" in flag or "parameter" in flag for flag in runtime_flags):
        return "validation"
    if any("forbidden" in flag or "authorization" in flag for flag in runtime_flags):
        return "policy"
    return "blocked"


def _first_runtime_reason(runtime_info: Mapping[str, Any]) -> str:
    for key in (
        "validation_error",
        "tool_approval_error",
        "error",
        "reason",
        "risk_level",
    ):
        value = runtime_info.get(key)
        if value:
            return _truncate_error(value)
    return ""


def _latest_prior_failure(
    prior_outcomes: Sequence[Mapping[str, Any]],
    *,
    tool_call_id: str,
    tool_name: str,
    same_call_only: bool = False,
) -> Mapping[str, Any]:
    if tool_call_id:
        for outcome in reversed(prior_outcomes or ()):
            if str(outcome.get("tool_call_id") or "") != tool_call_id:
                continue
            if str(outcome.get("status") or "") in {"failed", "blocked"}:
                return outcome
    if same_call_only:
        return {}
    for outcome in reversed(prior_outcomes or ()):
        if str(outcome.get("tool_name") or "") != tool_name:
            continue
        if str(outcome.get("status") or "") in {"failed", "blocked"}:
            return outcome
    return {}


def _attempt_index(
    *,
    tool_call_id: str,
    tool_name: str,
    runtime_info: Mapping[str, Any],
    prior_outcomes: Sequence[Mapping[str, Any]],
) -> int:
    explicit = runtime_info.get("attempt_index")
    try:
        if explicit is not None:
            return max(1, int(explicit))
    except (TypeError, ValueError):
        pass
    if tool_call_id:
        attempts = [
            int(item.get("attempt_index") or 1)
            for item in prior_outcomes or ()
            if str(item.get("tool_call_id") or "") == tool_call_id
        ]
        return max(attempts, default=0) + 1
    attempts = [
        int(item.get("attempt_index") or 1)
        for item in prior_outcomes or ()
        if str(item.get("tool_name") or "") == tool_name
    ]
    return max(attempts, default=0) + 1


def _is_retryable(*, error_category: str, message: str) -> bool:
    if error_category in _RETRYABLE_ERROR_CATEGORIES:
        return True
    lowered = str(message or "").lower()
    return any(marker in lowered for marker in _NETWORK_MARKERS)


def _evidence_role(*, tool_name: str, status: str) -> str:
    if status in {"failed", "blocked", "skipped"}:
        return "none"
    if tool_name in {"web_search", "web_fetch"}:
        return "alternative"
    if tool_name in {"run_skill_entrypoint", "run_workspace_command"}:
        return "primary"
    return "supporting"


def _evidence_count(
    *,
    contract: Mapping[str, Any],
    evidence_ledger: Sequence[Mapping[str, Any]],
) -> int:
    skill_facts = contract.get("skill_evidence_facts")
    if isinstance(skill_facts, Sequence) and not isinstance(skill_facts, (str, bytes)):
        return len(skill_facts)
    return len(evidence_ledger or ())


def _is_degraded_task(
    *,
    contract_status: str,
    verification_status: str,
    repair_action: str,
    failed_outcomes: Sequence[Mapping[str, Any]],
    evidence_count: int,
) -> bool:
    if repair_action in {"fallback_to_tool_results", "answer_with_uncertainty"}:
        return True
    if contract_status not in {"satisfied", "not_required"}:
        return True
    if verification_status not in {"verified", "not_required"}:
        return True
    return bool(failed_outcomes and evidence_count == 0)


def _unresolved_failed_outcomes(
    tool_outcomes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    recovered_ids = {
        str(item.get("recovery_of_tool_call_id") or "")
        for item in tool_outcomes
        if str(item.get("status") or "") == "recovered"
    }
    recovered_ids.discard("")
    return [
        dict(item)
        for item in tool_outcomes
        if str(item.get("status") or "") in {"failed", "blocked"}
        and str(item.get("tool_call_id") or "") not in recovered_ids
    ]


def _degradation_reason(
    *,
    status: TaskOutcomeStatus,
    verification: Mapping[str, Any],
    contract: Mapping[str, Any],
    failed_outcomes: Sequence[Mapping[str, Any]],
) -> str:
    if status == "answered":
        return ""
    blocked_reason = str(contract.get("blocked_reason") or "").strip()
    if blocked_reason:
        return blocked_reason
    for key in ("unsupported_claims", "contradictions"):
        values = verification.get(key)
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            text = "; ".join(str(item) for item in values if str(item))
            if text:
                return text
    for outcome in failed_outcomes:
        message = str(outcome.get("error_message") or "").strip()
        if message:
            return message
    return "insufficient evidence"


def _task_warnings(
    *,
    verification: Mapping[str, Any],
    contract: Mapping[str, Any],
    failed_outcomes: Sequence[Mapping[str, Any]],
) -> list[str]:
    warnings: list[str] = []
    for key in ("unsupported_claims", "contradictions"):
        values = verification.get(key)
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            warnings.extend(str(item) for item in values if str(item))
    blocked_reason = str(contract.get("blocked_reason") or "").strip()
    if blocked_reason:
        warnings.append(blocked_reason)
    warnings.extend(
        f"{item.get('tool_name')}: {item.get('error_message')}"
        for item in failed_outcomes
        if item.get("error_message")
    )
    return list(dict.fromkeys(warnings))[:8]


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _truncate_error(value: Any, max_chars: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1]}…"


__all__ = [
    "TASK_OUTCOME_STATUSES",
    "TOOL_OUTCOME_STATUSES",
    "TaskOutcomeStatus",
    "ToolOutcomeStatus",
    "build_task_outcome",
    "build_tool_outcomes_from_messages",
    "tool_outcome_from_message",
]
