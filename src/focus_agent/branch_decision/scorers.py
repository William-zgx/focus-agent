from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from focus_agent.core.branching import BranchMeta
from focus_agent.core.governance import (
    BranchDecisionAction,
    BranchDecisionSignal,
)


@dataclass(frozen=True, slots=True)
class BranchDecisionScore:
    action: BranchDecisionAction
    score: float
    threshold: float
    rationale: str


def score_branch_decisions(
    *,
    signals: list[BranchDecisionSignal],
    branch_meta: BranchMeta | None,
    split_threshold: float,
    conclude_threshold: float,
    merge_candidate_threshold: float,
) -> list[BranchDecisionScore]:
    by_name = {signal.name: signal for signal in signals}
    hint = str(_signal_value(by_name, "explicit_hint", "none"))
    turn_depth = float(_signal_value(by_name, "turn_depth", 0) or 0)
    recent_shape = _signal_value(by_name, "recent_message_shape", {})
    shape = recent_shape if isinstance(recent_shape, dict) else {}
    pending_action = bool(_signal_value(by_name, "pending_branch_action", False))
    merge_proposal_presence = bool(_signal_value(by_name, "merge_proposal_presence", False))
    on_branch = branch_meta is not None

    split_score = 0.18
    if hint == BranchDecisionAction.SPLIT.value:
        split_score += 0.38
    if bool(shape.get("has_alternative")):
        split_score += 0.18
    if bool(shape.get("has_question")) and turn_depth >= 2:
        split_score += 0.10
    if turn_depth >= 4:
        split_score += 0.10
    if pending_action:
        split_score -= 0.35

    conclude_score = 0.08
    if hint == BranchDecisionAction.CONCLUDE.value:
        conclude_score += 0.40
    if bool(shape.get("has_final_answer")):
        conclude_score += 0.20
    if on_branch and turn_depth >= 3:
        conclude_score += 0.12
    if bool(shape.get("has_tool_activity")):
        conclude_score += 0.08

    merge_score = 0.05
    if hint == BranchDecisionAction.MERGE_CANDIDATE.value:
        merge_score += 0.35
    if merge_proposal_presence:
        merge_score += 0.35
    if on_branch and bool(shape.get("has_final_answer")):
        merge_score += 0.15
    if pending_action:
        merge_score -= 0.20

    return [
        BranchDecisionScore(
            action=BranchDecisionAction.SPLIT,
            score=_clamp(split_score),
            threshold=split_threshold,
            rationale=_rationale(
                "split",
                hint=hint,
                on_branch=on_branch,
                turn_depth=turn_depth,
                shape=shape,
            ),
        ),
        BranchDecisionScore(
            action=BranchDecisionAction.CONCLUDE,
            score=_clamp(conclude_score),
            threshold=conclude_threshold,
            rationale=_rationale(
                "conclude",
                hint=hint,
                on_branch=on_branch,
                turn_depth=turn_depth,
                shape=shape,
            ),
        ),
        BranchDecisionScore(
            action=BranchDecisionAction.MERGE_CANDIDATE,
            score=_clamp(merge_score),
            threshold=merge_candidate_threshold,
            rationale=_rationale(
                "merge_candidate",
                hint=hint,
                on_branch=on_branch,
                turn_depth=turn_depth,
                shape=shape,
            ),
        ),
    ]


def score_branch_recommendation(
    *,
    signals: list[BranchDecisionSignal],
    min_confidence: float,
) -> BranchDecisionScore:
    by_name = {signal.name: signal for signal in signals}
    target = str(
        _signal_value(
            by_name,
            "recommendation_explicit_target",
            BranchDecisionAction.CONTINUE_CURRENT.value,
        )
    )
    explicit_source = str(_signal_value(by_name, "recommendation_explicit_source", "none"))
    topic_drift_value = _signal_value(by_name, "recommendation_topic_drift", {})
    topic_drift = topic_drift_value if isinstance(topic_drift_value, dict) else {}
    semantic_value = _signal_value(by_name, "semantic_topic_relation", {})
    semantic_topic_relation = semantic_value if isinstance(semantic_value, dict) else {}
    shape_value = _signal_value(by_name, "pre_turn_message_shape", {})
    shape = shape_value if isinstance(shape_value, dict) else {}
    pending_action = bool(_signal_value(by_name, "pending_branch_action", False))
    has_history_context = bool(shape.get("has_history_context"))

    action = _recommendation_action(target)
    routed_by = explicit_source
    if (
        action == BranchDecisionAction.CONTINUE_CURRENT
        and explicit_source == "none"
        and has_history_context
    ):
        drift_target = topic_drift.get("recommendation_target") if topic_drift else None
        shape_target = shape.get("recommendation_target") if shape else None
        if bool(topic_drift.get("has_topic_drift")) and drift_target:
            action = _recommendation_action(str(drift_target))
            routed_by = "topic_drift"
        elif bool(shape.get("has_topic_drift")) and shape_target:
            action = _recommendation_action(str(shape_target))
            routed_by = "shape_topic_drift"
        elif _semantic_topic_shift_confident(
            semantic_topic_relation,
            min_confidence=min_confidence,
        ):
            action = _semantic_recommendation_action_for_context(
                semantic_topic_relation,
                has_branch_context=bool(shape.get("has_branch_context")),
            )
            routed_by = "semantic_topic_relation"

    score = 0.72 if action == BranchDecisionAction.CONTINUE_CURRENT else 0.82
    if bool(shape.get("has_alternative")):
        score += 0.04
    if bool(shape.get("has_new_direction")):
        score += 0.06
    if bool(shape.get("has_topic_drift")):
        score += 0.08
    if bool(topic_drift.get("has_topic_drift")):
        score += 0.08
    if routed_by == "semantic_topic_relation":
        score = max(score, float(semantic_topic_relation.get("confidence") or 0.0))
    if action == BranchDecisionAction.FORK_SIBLING_BRANCH and bool(shape.get("has_branch_context")):
        score += 0.04
    if pending_action and action != BranchDecisionAction.CONTINUE_CURRENT:
        score -= 0.35

    return BranchDecisionScore(
        action=action,
        score=_clamp(score),
        threshold=min_confidence,
        rationale=_recommendation_rationale(action=action, shape=shape, routed_by=routed_by),
    )


def select_best_score(scores: list[BranchDecisionScore]) -> BranchDecisionScore:
    if not scores:
        raise ValueError("at least one branch decision score is required")
    return max(scores, key=lambda score: (score.score, score.action.value))


def _signal_value(signals: dict[str, BranchDecisionSignal], name: str, default: Any) -> Any:
    signal = signals.get(name)
    return default if signal is None else signal.value


def _clamp(value: float) -> float:
    return round(max(0.0, min(float(value), 1.0)), 4)


def _recommendation_action(value: str) -> BranchDecisionAction:
    for action in {
        BranchDecisionAction.CONTINUE_CURRENT,
        BranchDecisionAction.FORK_CHILD_BRANCH,
        BranchDecisionAction.FORK_SIBLING_BRANCH,
    }:
        if value == action.value:
            return action
    return BranchDecisionAction.CONTINUE_CURRENT


def _semantic_topic_shift_confident(
    value: dict[str, Any],
    *,
    min_confidence: float,
) -> bool:
    if str(value.get("status") or "").strip().lower() not in {"ok", "success"}:
        return False
    if not bool(value.get("topic_shift")):
        return False
    try:
        confidence = float(value.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return False
    if confidence < float(min_confidence):
        return False
    return (
        _recommendation_action(str(value.get("recommended_action")))
        != BranchDecisionAction.CONTINUE_CURRENT
    )


def _semantic_recommendation_action_for_context(
    value: dict[str, Any],
    *,
    has_branch_context: bool,
) -> BranchDecisionAction:
    action = _recommendation_action(str(value.get("recommended_action")))
    if action == BranchDecisionAction.CONTINUE_CURRENT:
        return action
    if has_branch_context:
        return BranchDecisionAction.FORK_SIBLING_BRANCH
    return BranchDecisionAction.FORK_CHILD_BRANCH


def _rationale(
    action: str,
    *,
    hint: str,
    on_branch: bool,
    turn_depth: float,
    shape: dict[str, Any],
) -> str:
    shape_flags = [
        key.removeprefix("has_")
        for key, enabled in shape.items()
        if key.startswith("has_") and bool(enabled)
    ]
    flags = ", ".join(shape_flags) if shape_flags else "no strong recent-shape flags"
    branch_text = "branch context" if on_branch else "root context"
    return f"{action} score from hint={hint}, {branch_text}, turn_depth={int(turn_depth)}, {flags}."


def _recommendation_rationale(
    *,
    action: BranchDecisionAction,
    shape: dict[str, Any],
    routed_by: str,
) -> str:
    shape_flags = [
        key.removeprefix("has_")
        for key, enabled in shape.items()
        if key.startswith("has_") and bool(enabled)
    ]
    flags = ", ".join(shape_flags) if shape_flags else "no strong pre-turn flags"
    return f"{action.value} recommendation from incoming message, route={routed_by}, {flags}."


__all__ = [
    "BranchDecisionScore",
    "score_branch_decisions",
    "score_branch_recommendation",
    "select_best_score",
]
