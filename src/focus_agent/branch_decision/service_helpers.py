"""Helper functions for branch decision service orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from focus_agent.core.branching import BranchActionKind, BranchMeta, BranchRole
from focus_agent.core.governance import (
    BranchDecisionAction,
    BranchDecisionMode,
    BranchDecisionRecommendationTarget,
)


def _should_run_semantic_topic_relation(
    *,
    signals: list[Any],
    action: BranchDecisionAction,
) -> bool:
    explicit_source = str(
        _branch_recommendation_signal_value(
            signals,
            "recommendation_explicit_source",
            "none",
        )
    )
    shape = _branch_recommendation_signal_value(signals, "pre_turn_message_shape", {})
    has_history_context = bool(
        shape.get("has_history_context") if isinstance(shape, dict) else False
    )
    return (
        explicit_source == "none"
        and action == BranchDecisionAction.CONTINUE_CURRENT
        and has_history_context
    )

def _branch_recommendation_signal_value(
    signals: list[Any],
    name: str,
    default: Any,
) -> Any:
    for signal in signals:
        if getattr(signal, "name", None) == name:
            return getattr(signal, "value", default)
    return default

def _normalized_message_hash(message: str | None) -> str:
    normalized = " ".join(str(message or "").split())
    return sha256(normalized.encode("utf-8")).hexdigest()[:16]

def _branch_handoff_idempotency_key(*, thread_id: str, message: str | None) -> str:
    return f"branch_handoff:{thread_id}:{_normalized_message_hash(message)}"

def _message_preview(message: str | None, *, limit: int = 240) -> str:
    return " ".join(str(message or "").split())[:limit]

def _semantic_topic_relation_metadata(signals: list[Any]) -> dict[str, Any]:
    relation = _semantic_topic_relation_from_signals(signals)
    return {
        "semantic_relatedness": relation.get("relatedness"),
        "semantic_relationship": relation.get("relationship"),
        "semantic_reason": relation.get("reason"),
        "semantic_model": relation.get("model"),
        "semantic_classifier_status": relation.get("status"),
    }

def _semantic_topic_relation_diagnostic(signals: list[Any]) -> dict[str, Any]:
    relation = _semantic_topic_relation_from_signals(signals)
    return {
        "semantic_topic_shift": bool(relation.get("topic_shift")),
        "semantic_confidence": float(relation.get("confidence") or 0.0),
        "semantic_recommended_action": relation.get("recommended_action"),
        "semantic_classifier_status": relation.get("status"),
        "semantic_reason": relation.get("reason"),
    }

def _semantic_topic_relation_from_signals(signals: list[Any]) -> dict[str, Any]:
    value = _branch_recommendation_signal_value(signals, "semantic_topic_relation", {})
    return value if isinstance(value, dict) else {}

def _call_semantic_topic_relation_classifier(
    classifier: Any,
    *,
    settings: Any,
    message: str,
    values: dict[str, Any],
    branch_meta: BranchMeta | None,
) -> Any:
    callable_classifier = _semantic_topic_relation_callable(classifier)
    messages = list(values.get("messages", []) or [])
    kwargs = {
        "settings": settings,
        "message": message,
        "incoming_message": message,
        "values": values,
        "messages": messages,
        "branch_history": messages,
        "branch_meta": branch_meta,
        "on_branch": branch_meta is not None,
        "selected_model": _selected_model_from_values(values),
    }
    for candidate_kwargs in (
        kwargs,
        {
            "message": message,
            "branch_history": messages,
            "on_branch": branch_meta is not None,
        },
        {
            "settings": settings,
            "message": message,
            "branch_history": messages,
            "on_branch": branch_meta is not None,
            "selected_model": _selected_model_from_values(values),
        },
        {
            "message": message,
            "messages": messages,
            "branch_meta": branch_meta,
        },
        {
            "message": message,
            "values": values,
        },
        {
            "message": message,
        },
    ):
        try:
            return callable_classifier(**candidate_kwargs)
        except TypeError:
            continue
    return callable_classifier(message, messages, branch_meta)

def _semantic_topic_relation_callable(classifier: Any) -> Any:
    for attr in (
        "classify_semantic_topic_relation",
        "classify_topic_relation",
        "classify",
        "evaluate",
    ):
        candidate = getattr(classifier, attr, None)
        if callable(candidate):
            return candidate
    if callable(classifier):
        return classifier
    raise TypeError("semantic topic relation classifier is not callable")

def _normalize_semantic_topic_relation_result(result: Any) -> dict[str, Any]:
    payload = _model_payload(result)
    if not payload or set(payload) == {"raw_response"}:
        return {
            "status": "non_json" if payload else "error",
            "topic_shift": False,
            "confidence": 0.0,
            "recommended_action": BranchDecisionAction.CONTINUE_CURRENT.value,
            "reason": "Semantic classifier returned no structured result.",
        }
    return {
        "status": _semantic_status(payload.get("status")),
        "topic_shift": bool(
            payload.get("topic_shift")
            if "topic_shift" in payload
            else payload.get("is_topic_shift", payload.get("new_topic", False))
        ),
        "confidence": _semantic_confidence(payload),
        "recommended_action": _semantic_recommended_action(
            payload.get("recommended_action")
            or payload.get("action")
            or payload.get("recommendation_target")
        ).value,
        "relatedness": payload.get("relatedness")
        if "relatedness" in payload
        else payload.get("semantic_relatedness", payload.get("relatedness_score")),
        "relationship": payload.get("relationship")
        if "relationship" in payload
        else payload.get("relation", payload.get("semantic_relationship")),
        "reason": str(payload.get("reason") or payload.get("rationale") or ""),
        "model": payload.get("model") or payload.get("model_name"),
    }

def _selected_model_from_values(values: dict[str, Any]) -> str | None:
    for key in ("selected_model", "model", "model_id"):
        text = str(values.get(key) or "").strip()
        if text:
            return text
    return None

def _model_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        dumped = dict_method()
        return dumped if isinstance(dumped, dict) else {}
    raw_dict = getattr(value, "__dict__", None)
    return raw_dict if isinstance(raw_dict, dict) else {}

def _semantic_status(value: Any) -> str:
    status = str(value or "success").strip().lower()
    if status in {"succeeded", "completed"}:
        return "success"
    return status or "error"

def _semantic_confidence(payload: dict[str, Any]) -> float:
    raw = payload.get("confidence")
    if raw is None:
        raw = payload.get("score", payload.get("probability", 0.0))
    try:
        return max(0.0, min(float(raw or 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0

def _semantic_recommended_action(value: Any) -> BranchDecisionAction:
    raw = str(value or "").strip()
    for action in {
        BranchDecisionAction.CONTINUE_CURRENT,
        BranchDecisionAction.FORK_CHILD_BRANCH,
        BranchDecisionAction.FORK_SIBLING_BRANCH,
    }:
        if raw == action.value:
            return action
    return BranchDecisionAction.CONTINUE_CURRENT

def _branch_decision_mode(value: object) -> BranchDecisionMode:
    normalized = str(value or "").strip().lower()
    if normalized == BranchDecisionMode.SUGGEST.value:
        return BranchDecisionMode.SUGGEST
    if normalized == BranchDecisionMode.EXECUTE.value:
        return BranchDecisionMode.EXECUTE
    return BranchDecisionMode.SHADOW

def _branch_action_kind_for_decision(action: BranchDecisionAction) -> BranchActionKind:
    if action == BranchDecisionAction.FORK_SIBLING_BRANCH:
        return BranchActionKind.FORK_SIBLING_BRANCH
    return BranchActionKind.FORK_CHILD_BRANCH

def _decision_action_for_branch_action_kind(kind: BranchActionKind) -> BranchDecisionAction:
    if kind == BranchActionKind.FORK_SIBLING_BRANCH:
        return BranchDecisionAction.FORK_SIBLING_BRANCH
    return BranchDecisionAction.FORK_CHILD_BRANCH

def _recommendation_target_for_decision(
    action: BranchDecisionAction,
) -> BranchDecisionRecommendationTarget:
    if action == BranchDecisionAction.FORK_SIBLING_BRANCH:
        return BranchDecisionRecommendationTarget.FORK_SIBLING_BRANCH
    if action == BranchDecisionAction.FORK_CHILD_BRANCH:
        return BranchDecisionRecommendationTarget.FORK_CHILD_BRANCH
    return BranchDecisionRecommendationTarget.CONTINUE_CURRENT

def _branch_role_for_recommendation(
    target: BranchDecisionRecommendationTarget | None,
) -> BranchRole:
    if target == BranchDecisionRecommendationTarget.FORK_CHILD_BRANCH:
        return BranchRole.DEEP_DIVE
    return BranchRole.EXPLORE_ALTERNATIVES

def _recommendation_user_visible(*, enabled: bool, mode: BranchDecisionMode) -> bool:
    return bool(enabled and mode == BranchDecisionMode.SUGGEST)

def _recommendation_diagnostics(
    *,
    enabled: bool,
    mode: BranchDecisionMode,
    semantic_enabled: bool = False,
    semantic_model: str | None = None,
) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "mode": mode.value,
        "user_visible": _recommendation_user_visible(enabled=enabled, mode=mode),
        "shadow_records_events_only": mode == BranchDecisionMode.SHADOW,
        "pending_action_mode": BranchDecisionMode.SUGGEST.value,
        "semantic_enabled": bool(semantic_enabled),
        "semantic_model": semantic_model,
    }

def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
