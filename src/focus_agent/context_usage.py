from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from langchain.messages import AnyMessage, HumanMessage, SystemMessage

from .core.context_policy import (
    assemble_context,
)
from .core.context_request import build_context_request
from .core.types import ContextBudget, PromptMode

ContextUsageStatus = Literal["ok", "warm", "hot", "over", "compacting", "error"]


@dataclass(slots=True)
class ContextUsage:
    used_tokens: int
    token_limit: int
    configured_token_limit: int
    input_token_limit: int
    remaining_tokens: int
    used_ratio: float
    status: ContextUsageStatus
    prompt_chars: int
    prompt_budget_chars: int
    tokenizer_mode: str
    counting_backend: str
    tokenizer_id: str | None
    estimated: bool
    drift_risk: str
    last_compacted_at: str | None = None
    pretrim_tokens: int = 0
    posttrim_tokens: int = 0
    tool_schema_tokens: int = 0
    output_reserve_tokens: int = 0
    trimmed: bool = False
    required_overflow: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "used_tokens": self.used_tokens,
            "token_limit": self.token_limit,
            "configured_token_limit": self.configured_token_limit,
            "input_token_limit": self.input_token_limit,
            "remaining_tokens": self.remaining_tokens,
            "used_ratio": self.used_ratio,
            "status": self.status,
            "prompt_chars": self.prompt_chars,
            "prompt_budget_chars": self.prompt_budget_chars,
            "tokenizer_mode": self.tokenizer_mode,
            "counting_backend": self.counting_backend,
            "tokenizer_id": self.tokenizer_id,
            "estimated": self.estimated,
            "drift_risk": self.drift_risk,
            "last_compacted_at": self.last_compacted_at,
            "pretrim_tokens": self.pretrim_tokens,
            "posttrim_tokens": self.posttrim_tokens,
            "tool_schema_tokens": self.tool_schema_tokens,
            "output_reserve_tokens": self.output_reserve_tokens,
            "trimmed": self.trimmed,
            "required_overflow": self.required_overflow,
        }


def context_usage_status(used_ratio: float) -> ContextUsageStatus:
    if used_ratio >= 1:
        return "over"
    if used_ratio >= 0.85:
        return "hot"
    if used_ratio >= 0.70:
        return "warm"
    return "ok"


def build_context_usage(
    state: dict[str, Any],
    *,
    draft_message: str | None = None,
    selected_model: str | None = None,
    available_tools: Iterable[Any] | None = None,
    output_reserve_tokens: int | None = None,
) -> ContextUsage:
    budget = _context_budget_from_state(state, selected_model=selected_model)
    prompt_mode = _prompt_mode_from_state(state)
    context_slice = assemble_context(
        {
            **dict(state),
            "context_budget": budget,
        },
        prompt_mode,
    )
    assembled_context = context_slice.render_prompt()
    prompt_messages: list[AnyMessage] = [
        SystemMessage(content=assembled_context),
        *context_slice.recent_messages,
    ]
    if draft_message and str(draft_message).strip():
        prompt_messages.append(HumanMessage(content=str(draft_message).strip()))

    request = build_context_request(
        prompt_messages,
        budget=budget,
        available_tools=available_tools
        if available_tools is not None
        else state.get("available_tools", ()),
        output_reserve_tokens=(
            output_reserve_tokens
            if output_reserve_tokens is not None
            else state.get("output_token_reserve")
        ),
        preserve_required_messages=True,
    )
    used_tokens = request.posttrim_tokens
    token_limit = request.input_token_limit
    remaining_tokens = request.remaining_tokens
    used_ratio = (
        1.0
        if request.required_overflow
        else min(1.0, used_tokens / token_limit)
        if token_limit
        else 0.0
    )
    prompt_chars = request.prompt_chars
    prompt_budget_chars = max(1, token_limit * max(1, int(budget.chars_per_token)))
    compaction = (
        state.get("context_compaction") if isinstance(state.get("context_compaction"), dict) else {}
    )
    drift_report = (
        compaction.get("context_compaction_drift_report")
        if isinstance(compaction.get("context_compaction_drift_report"), dict)
        else {}
    )
    return ContextUsage(
        used_tokens=used_tokens,
        token_limit=token_limit,
        configured_token_limit=request.configured_token_limit,
        input_token_limit=request.input_token_limit,
        remaining_tokens=remaining_tokens,
        used_ratio=used_ratio,
        status=context_usage_status(used_ratio),
        prompt_chars=prompt_chars,
        prompt_budget_chars=prompt_budget_chars,
        tokenizer_mode=str(budget.token_budget_mode),
        counting_backend=request.counting_backend,
        tokenizer_id=request.tokenizer_id or budget.tokenizer_id,
        estimated=request.estimated,
        drift_risk=_context_drift_risk(
            used_ratio=used_ratio,
            estimated=request.estimated,
            drift_report=drift_report,
        ),
        last_compacted_at=str(compaction.get("last_compacted_at") or "") or None,
        pretrim_tokens=request.pretrim_tokens,
        posttrim_tokens=request.posttrim_tokens,
        tool_schema_tokens=request.tool_schema_tokens,
        output_reserve_tokens=request.output_reserve_tokens,
        trimmed=request.trimmed,
        required_overflow=request.required_overflow,
    )


def _context_budget_from_state(
    state: dict[str, Any], *, selected_model: str | None = None
) -> ContextBudget:
    value = state.get("context_budget")
    if isinstance(value, ContextBudget):
        budget = value
    elif isinstance(value, dict):
        try:
            budget = ContextBudget.model_validate(value)
        except Exception:  # noqa: BLE001
            budget = ContextBudget()
    else:
        budget = ContextBudget()
    model_id = str(selected_model or state.get("selected_model") or "").strip()
    if budget.tokenizer_id or not model_id:
        return budget
    return budget.model_copy(update={"tokenizer_id": model_id})


def _prompt_mode_from_state(state: dict[str, Any]) -> PromptMode:
    value = state.get("prompt_mode")
    if isinstance(value, PromptMode):
        return value
    if isinstance(value, str):
        try:
            return PromptMode(value)
        except ValueError:
            pass
    if state.get("merge_proposal") and not state.get("merge_decision"):
        return PromptMode.BRANCH_REVIEW
    return PromptMode.EXPLORE


def _context_drift_risk(
    *,
    used_ratio: float,
    estimated: bool,
    drift_report: dict[str, Any],
) -> str:
    try:
        overall_drift = float(drift_report.get("overall_drift") or 0.0)
    except (TypeError, ValueError):
        overall_drift = 0.0
    explicit_risk = str(drift_report.get("drift_risk") or "").strip().lower()
    if explicit_risk in {"high", "medium", "low"}:
        return explicit_risk
    if overall_drift >= 0.34 or used_ratio >= 1.0 or (estimated and used_ratio >= 0.85):
        return "high"
    if overall_drift > 0.0 or estimated or used_ratio >= 0.70:
        return "medium"
    return "low"


__all__ = ["ContextUsage", "ContextUsageStatus", "build_context_usage", "context_usage_status"]
