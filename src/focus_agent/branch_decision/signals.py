from __future__ import annotations

import re
from typing import Any

from focus_agent.core.branching import BranchMeta, BranchStatus
from focus_agent.core.governance import BranchDecisionAction, BranchDecisionSignal
from focus_agent.services.branch_actions import latest_pending_branch_action

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
_CONCLUDE_HINTS = (
    "conclude",
    "summary",
    "summarize",
    "wrap up",
    "final",
    "结论",
    "总结",
    "收束",
    "整理",
)
_MERGE_HINTS = (
    "merge",
    "promote",
    "bring back",
    "return to main",
    "合并",
    "带回",
    "回主线",
    "导入",
)
_RECOMMEND_CHILD_HINTS = (
    "child branch",
    "sub-branch",
    "sub branch",
    "deep dive",
    "drill down",
    "deepen",
    "子分支",
    "子话题",
    "深入",
    "细化",
    "深挖",
    "展开",
)
_RECOMMEND_SIBLING_HINTS = (
    "sibling branch",
    "sibling",
    "parallel",
    "parallel branch",
    "alternative",
    "same level",
    "同级",
    "平级",
    "并行",
    "平行",
    "并列",
    "替代方案",
    "备选方案",
    "另一个方向",
    "换个方向",
)
_RECOMMEND_FORK_HINTS = (
    "branch",
    "fork",
    "split",
    "parallel",
    "alternative",
    "explore separately",
    "分支",
    "另开",
    "新开",
    "新建",
    "并行",
    "拆开",
    "单独研究",
)
_RECOMMEND_CONTINUE_HINTS = (
    "continue here",
    "current thread",
    "same thread",
    "no branch",
    "don't branch",
    "do not branch",
    "继续当前",
    "当前线程",
    "在这里",
    "不用分支",
    "不要分支",
    "别开分支",
)


def collect_branch_decision_signals(
    *,
    values: dict[str, Any],
    branch_meta: BranchMeta | None,
) -> list[BranchDecisionSignal]:
    messages = list(values.get("messages", []) or [])
    recent_text = "\n".join(_message_text(message) for message in messages[-6:])
    latest_human_text = _latest_human_text(messages)
    explicit_hint = _explicit_hint(latest_human_text or recent_text)
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
) -> list[BranchDecisionSignal]:
    messages = list(values.get("messages", []) or [])
    normalized = _compact(message)
    explicit_target = _recommendation_explicit_target(normalized, branch_meta=branch_meta)
    pending_action = latest_pending_branch_action(values.get("branch_actions")) is not None
    branch_status = branch_meta.branch_status if branch_meta is not None else BranchStatus.ACTIVE
    shape = _pre_turn_message_shape(message=message, branch_meta=branch_meta)

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


def _explicit_hint(text: str) -> str:
    normalized = _compact(text)
    if not normalized:
        return "none"
    if any(_compact(marker) in normalized for marker in _SPLIT_HINTS):
        return "split"
    if any(_compact(marker) in normalized for marker in _MERGE_HINTS):
        return "merge_candidate"
    if any(_compact(marker) in normalized for marker in _CONCLUDE_HINTS):
        return "conclude"
    return "none"


def _recommendation_explicit_target(
    normalized_message: str,
    *,
    branch_meta: BranchMeta | None,
) -> BranchDecisionAction:
    if not normalized_message:
        return BranchDecisionAction.CONTINUE_CURRENT
    if any(_compact(marker) in normalized_message for marker in _RECOMMEND_CONTINUE_HINTS):
        return BranchDecisionAction.CONTINUE_CURRENT
    if any(_compact(marker) in normalized_message for marker in _RECOMMEND_CHILD_HINTS):
        return BranchDecisionAction.FORK_CHILD_BRANCH
    if any(_compact(marker) in normalized_message for marker in _RECOMMEND_SIBLING_HINTS):
        if branch_meta is not None:
            return BranchDecisionAction.FORK_SIBLING_BRANCH
        return BranchDecisionAction.FORK_CHILD_BRANCH
    if any(_compact(marker) in normalized_message for marker in _RECOMMEND_FORK_HINTS):
        return BranchDecisionAction.FORK_CHILD_BRANCH
    return BranchDecisionAction.CONTINUE_CURRENT


def _pre_turn_message_shape(
    *,
    message: str,
    branch_meta: BranchMeta | None,
) -> dict[str, Any]:
    compact = _compact(message)
    has_question = "?" in message or "？" in message
    has_alternative = any(
        marker in compact for marker in ("option", "alternative", "方案", "路径", "还是")
    )
    has_new_direction = any(
        marker in compact for marker in ("another", "different", "另一个", "换个", "新方向")
    )
    has_branch_context = branch_meta is not None
    score = 0.45
    if has_question:
        score += 0.08
    if has_alternative:
        score += 0.12
    if has_new_direction:
        score += 0.15
    if has_branch_context:
        score += 0.05
    return {
        "has_question": has_question,
        "has_alternative": has_alternative,
        "has_new_direction": has_new_direction,
        "has_branch_context": has_branch_context,
        "message_chars": len(str(message or "")),
        "score": min(score, 1.0),
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


def _message_text(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content")
    else:
        content = getattr(message, "content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            elif item is not None:
                parts.append(str(item))
        return " ".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return str(content or "")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().lower())


__all__ = ["collect_branch_decision_signals", "collect_branch_recommendation_signals"]
