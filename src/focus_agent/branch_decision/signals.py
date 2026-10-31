from __future__ import annotations

import re
from typing import Any

from focus_agent.core.branching import BranchMeta, BranchStatus
from focus_agent.core.governance import BranchDecisionAction, BranchDecisionSignal
from focus_agent.services.branches.actions import latest_pending_branch_action

from .intent import (
    detect_branch_intent,
    merge_back_match,
    topic_drift_match,
    weak_detour_match,
)
from .service_helpers import _message_text, _semantic_recommended_action

_SPLIT_HINTS = (
    "branch",
    "split",
    "fork",
    "parallel",
    "alternative",
    "explore",
    "分支",
    "另开",
    "并行",
    "拆开",
    "子分支",
    "新开",
)
# Conclusion wording must be explicit: "整理" (tidy up) or a bare "summary"/"final"
# is ordinary editing, not evidence that a branch is done.
_CONCLUDE_ZH_RE = re.compile(
    r"总结一下|做(?:个|一个)?总结|总结(?:这个|本)分支|给出(?:最终)?结论|得出(?:最终)?结论"
    r"|下(?:个)?结论|最终结论|收尾|收束"
)
_CONCLUDE_EN_RE = re.compile(
    r"\b(?:conclude|conclusion|wrap(?:ping)?\s+(?:it\s+|this\s+)?up|"
    r"summari[sz]e\s+(?:this|the|our)\s+(?:branch|findings|research|work))\b",
    flags=re.IGNORECASE,
)


def collect_branch_decision_signals(
    *,
    values: dict[str, Any],
    branch_meta: BranchMeta | None,
) -> list[BranchDecisionSignal]:
    messages = list(values.get("messages", []) or [])
    recent_text = "\n".join(_message_text(message) for message in messages[-6:])
    latest_human_text = _latest_human_text(messages)
    explicit_hint = _explicit_hint(
        latest_human_text or recent_text,
        on_branch=branch_meta is not None,
    )
    turn_depth = sum(1 for message in messages if _message_type(message) in {"human", "user"})
    pending_action = latest_pending_branch_action(values.get("branch_actions")) is not None
    branch_status = branch_meta.branch_status if branch_meta is not None else BranchStatus.ACTIVE
    merge_proposal = bool(values.get("merge_proposal"))
    recent_shape = _recent_message_shape(messages=messages, recent_text=recent_text)

    return [
        BranchDecisionSignal(
            name="explicit_hint",
            value=explicit_hint,
            score=1.0 if explicit_hint != "none" else 0.0,
            weight=0.30,
            evidence_refs=_message_refs(messages[-2:]),
            rationale="Latest user wording contains branch, conclusion, or merge intent."
            if explicit_hint != "none"
            else "No direct branch decision wording was detected.",
        ),
        BranchDecisionSignal(
            name="turn_depth",
            value=turn_depth,
            score=min(turn_depth / 8.0, 1.0),
            weight=0.15,
            rationale="Longer threads are more likely to benefit from branching or conclusion review.",
        ),
        BranchDecisionSignal(
            name="pending_branch_action",
            value=pending_action,
            score=1.0 if pending_action else 0.0,
            weight=0.20,
            rationale="A pending branch action blocks additional autonomous suggestions.",
        ),
        BranchDecisionSignal(
            name="branch_status",
            value=branch_status.value,
            score=0.0
            if branch_status in {BranchStatus.MERGED, BranchStatus.DISCARDED, BranchStatus.CLOSED}
            else 1.0,
            weight=0.20,
            rationale="Merged, discarded, and closed branches are read-only for autonomy.",
        ),
        BranchDecisionSignal(
            name="merge_proposal_presence",
            value=merge_proposal,
            score=1.0 if merge_proposal else 0.0,
            weight=0.20,
            rationale="A prepared merge proposal is strong evidence for a merge-candidate decision.",
        ),
        BranchDecisionSignal(
            name="recent_message_shape",
            value=recent_shape,
            score=float(recent_shape.get("score") or 0.0),
            weight=0.25,
            evidence_refs=_message_refs(messages[-4:]),
            rationale="Recent messages are summarized as structural signals, not stored verbatim.",
        ),
    ]


def collect_branch_recommendation_signals(
    *,
    message: str,
    values: dict[str, Any],
    branch_meta: BranchMeta | None,
    semantic_topic_relation: dict[str, Any] | None = None,
) -> list[BranchDecisionSignal]:
    messages = list(values.get("messages", []) or [])
    intent = detect_branch_intent(message, on_branch=branch_meta is not None)
    weak = weak_detour_match(message) if intent.source == "none" else None
    merge_back = (
        merge_back_match(message) if branch_meta is not None and intent.source == "none" else None
    )
    explicit_target = intent.target
    explicit_source = intent.source
    topic_drift = _recommendation_topic_drift(message, branch_meta=branch_meta)
    pending_action = latest_pending_branch_action(values.get("branch_actions")) is not None
    branch_status = branch_meta.branch_status if branch_meta is not None else BranchStatus.ACTIVE
    shape = _pre_turn_message_shape(
        message=message,
        branch_meta=branch_meta,
        messages=messages,
    )
    semantic_relation = _semantic_topic_relation_signal_value(semantic_topic_relation)

    return [
        BranchDecisionSignal(
            name="recommendation_explicit_target",
            value=explicit_target.value,
            score=1.0 if explicit_target != BranchDecisionAction.CONTINUE_CURRENT else 0.65,
            weight=0.40,
            evidence_refs=["incoming_user_message"],
            rationale="Incoming user wording maps to a deterministic branch recommendation target.",
        ),
        BranchDecisionSignal(
            name="recommendation_explicit_source",
            value=explicit_source,
            score=1.0 if explicit_source != "none" else 0.0,
            weight=0.20,
            evidence_refs=["incoming_user_message"],
            rationale="Incoming user wording contains an explicit branch or continue hint."
            if explicit_source != "none"
            else "No explicit branch or continue hint was detected.",
        ),
        BranchDecisionSignal(
            name="recommendation_intent",
            value={
                "strength": intent.strength,
                "route": intent.route,
                "matched": intent.matched,
                "weak_route": weak[0] if weak else None,
                "weak_matched": weak[1] if weak else None,
                "weak_target": _weak_target(weak[0], branch_meta=branch_meta) if weak else None,
                "merge_back": merge_back,
            },
            score=1.0 if intent.source == "branch_hint" else 0.0,
            weight=0.0,
            evidence_refs=["incoming_user_message"],
            rationale="Graded strength of the lexical branch intent (explicit, strong, weak).",
        ),
        BranchDecisionSignal(
            name="recommendation_topic_drift",
            value=topic_drift,
            score=1.0 if bool(topic_drift.get("has_topic_drift")) else 0.0,
            weight=0.35,
            evidence_refs=["incoming_user_message"],
            rationale="Incoming user wording clearly starts a new or unrelated topic."
            if bool(topic_drift.get("has_topic_drift"))
            else "No strong new-topic drift wording was detected.",
        ),
        BranchDecisionSignal(
            name="semantic_topic_relation",
            value=semantic_relation,
            score=float(semantic_relation.get("confidence") or 0.0)
            if bool(semantic_relation.get("topic_shift"))
            and semantic_relation.get("status") in {"ok", "success"}
            else 0.0,
            weight=0.35,
            evidence_refs=["incoming_user_message"],
            rationale=str(
                semantic_relation.get("reason") or "Semantic topic relation was not run."
            ),
        ),
        BranchDecisionSignal(
            name="pending_branch_action",
            value=pending_action,
            score=1.0 if pending_action else 0.0,
            weight=0.20,
            rationale="A pending branch action blocks additional branch-action recommendations.",
        ),
        BranchDecisionSignal(
            name="branch_status",
            value=branch_status.value,
            score=0.0
            if branch_status in {BranchStatus.MERGED, BranchStatus.DISCARDED, BranchStatus.CLOSED}
            else 1.0,
            weight=0.20,
            rationale="Merged, discarded, and closed branches are read-only for recommendations.",
        ),
        BranchDecisionSignal(
            name="pre_turn_message_shape",
            value=shape,
            score=float(shape.get("score") or 0.0),
            weight=0.25,
            evidence_refs=_message_refs(messages[-2:]) or ["incoming_user_message"],
            rationale="Incoming message shape is summarized as deterministic routing evidence.",
        ),
    ]


def _explicit_hint(text: str, *, on_branch: bool = False) -> str:
    normalized = _compact(text)
    if not normalized:
        return "none"
    # Merge-back and conclusion only mean something on a child branch, and they win
    # over split markers ("把这个分支合并回主线" / "总结一下这个分支" mention 分支 but
    # are not splits).
    if on_branch and merge_back_match(text):
        return "merge_candidate"
    if on_branch and (_CONCLUDE_ZH_RE.search(normalized) or _CONCLUDE_EN_RE.search(text)):
        return "conclude"
    if any(_compact(marker) in normalized for marker in _SPLIT_HINTS):
        return "split"
    return "none"


def _weak_target(route: str, *, branch_meta: BranchMeta | None) -> str:
    # An unrelated side question on a branch belongs next to it; comparisons and
    # debugging detours are sub-work of the current thread.
    if route == "side_question" and branch_meta is not None:
        return BranchDecisionAction.FORK_SIBLING_BRANCH.value
    return BranchDecisionAction.FORK_CHILD_BRANCH.value


def _recommendation_topic_drift(
    message: str,
    *,
    branch_meta: BranchMeta | None,
) -> dict[str, Any]:
    matched_hint = topic_drift_match(message)
    target = (
        BranchDecisionAction.FORK_SIBLING_BRANCH
        if branch_meta is not None
        else BranchDecisionAction.FORK_CHILD_BRANCH
    )
    return {
        "has_topic_drift": matched_hint is not None,
        "matched_hint": matched_hint,
        "recommendation_target": target.value if matched_hint is not None else None,
    }


def _pre_turn_message_shape(
    *,
    message: str,
    branch_meta: BranchMeta | None,
    messages: list[Any] | None = None,
) -> dict[str, Any]:
    history_messages = list(messages or [])
    history_human_count = sum(
        1 for item in history_messages if _message_type(item) in {"human", "user"}
    )
    history_answer_count = sum(
        1 for item in history_messages if _message_type(item) in {"ai", "assistant"}
    )
    has_history_context = bool(history_human_count or history_answer_count)
    compact = _compact(message)
    has_question = "?" in message or "？" in message
    has_alternative = any(
        marker in compact for marker in ("option", "alternative", "方案", "路径", "还是")
    )
    has_new_direction = any(
        marker in compact for marker in ("another", "different", "另一个", "换个", "新方向")
    )
    matched_topic_drift = topic_drift_match(message)
    has_branch_context = branch_meta is not None
    score = 0.45
    if has_question:
        score += 0.08
    if has_alternative:
        score += 0.12
    if has_new_direction:
        score += 0.15
    if matched_topic_drift is not None:
        score += 0.18
    if has_branch_context:
        score += 0.05
    recommendation_target = None
    if matched_topic_drift is not None:
        recommendation_target = (
            BranchDecisionAction.FORK_SIBLING_BRANCH.value
            if has_branch_context
            else BranchDecisionAction.FORK_CHILD_BRANCH.value
        )
    return {
        "has_question": has_question,
        "has_alternative": has_alternative,
        "has_new_direction": has_new_direction,
        "has_topic_drift": matched_topic_drift is not None,
        "has_branch_context": has_branch_context,
        "has_history_context": has_history_context,
        "history_human_count": history_human_count,
        "history_answer_count": history_answer_count,
        "recommendation_target": recommendation_target,
        "message_chars": len(str(message or "")),
        "score": min(score, 1.0),
    }


def _semantic_topic_relation_signal_value(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "status": "not_run",
            "topic_shift": False,
            "confidence": 0.0,
            "recommended_action": BranchDecisionAction.CONTINUE_CURRENT.value,
            "relatedness": None,
            "relationship": None,
            "reason": "Semantic classifier was not invoked.",
            "model": None,
        }
    action = _semantic_recommended_action(value.get("recommended_action"))
    try:
        confidence = float(value.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    status = str(value.get("status") or "success").strip().lower()
    if status in {"succeeded", "completed"}:
        status = "success"
    return {
        "status": status or "error",
        "topic_shift": bool(value.get("topic_shift")),
        "confidence": max(0.0, min(confidence, 1.0)),
        "recommended_action": action.value,
        "relatedness": value.get("relatedness"),
        "relationship": value.get("relationship"),
        "reason": str(value.get("reason") or ""),
        "model": value.get("model"),
        "decision_min_confidence": value.get("decision_min_confidence"),
        "diagnostics": value.get("diagnostics") or {},
    }


def _recent_message_shape(*, messages: list[Any], recent_text: str) -> dict[str, Any]:
    compact = _compact(recent_text)
    has_question = "?" in recent_text or "？" in recent_text
    has_alternative = any(
        marker in compact for marker in ("option", "alternative", "方案", "路径", "还是")
    )
    has_tool_activity = any(_message_type(message) == "tool" for message in messages[-8:])
    has_long_context = len(recent_text) >= 1200
    has_final_answer = bool(messages and _message_type(messages[-1]) in {"ai", "assistant"})
    score = 0.0
    if has_question:
        score += 0.15
    if has_alternative:
        score += 0.30
    if has_tool_activity:
        score += 0.15
    if has_long_context:
        score += 0.20
    if has_final_answer:
        score += 0.20
    return {
        "has_question": has_question,
        "has_alternative": has_alternative,
        "has_tool_activity": has_tool_activity,
        "has_long_context": has_long_context,
        "has_final_answer": has_final_answer,
        "score": min(score, 1.0),
    }


def _message_refs(messages: list[Any]) -> list[str]:
    refs: list[str] = []
    for index, message in enumerate(messages):
        message_id = _message_id(message)
        refs.append(message_id or f"recent:{index}")
    return refs


def _latest_human_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if _message_type(message) in {"human", "user"}:
            return _message_text(message)
    return ""


def _message_id(message: Any) -> str | None:
    if isinstance(message, dict):
        raw_id = message.get("id")
    else:
        raw_id = getattr(message, "id", None)
    return str(raw_id) if raw_id else None


def _message_type(message: Any) -> str:
    if isinstance(message, dict):
        raw_type = message.get("type") or message.get("role") or message.get("_type")
    else:
        raw_type = getattr(message, "type", None)
    return str(raw_type or "").strip().lower()


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().lower())


__all__ = ["collect_branch_decision_signals", "collect_branch_recommendation_signals"]
