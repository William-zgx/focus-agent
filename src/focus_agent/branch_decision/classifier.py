from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from typing import Any, Literal

from langchain.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError, field_validator

from focus_agent.config import Settings

SemanticBranchAction = Literal[
    "continue_current",
    "fork_child_branch",
    "fork_sibling_branch",
]
SemanticClassifierStatus = Literal["ok", "disabled", "semantic_classifier_failed", "error"]


class SemanticTopicRelationResult(BaseModel):
    relatedness: float = Field(default=1.0, ge=0.0, le=1.0)
    topic_shift: bool = False
    relationship: str = "unknown"
    recommended_action: SemanticBranchAction = "continue_current"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    model: str | None = None
    status: SemanticClassifierStatus = "ok"

    @field_validator("relationship", "reason", mode="before")
    @classmethod
    def _stringify_text(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("relatedness", mode="before")
    @classmethod
    def _coerce_relatedness(cls, value: object) -> float:
        if isinstance(value, str):
            normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
            label_scores = {
                "unrelated": 0.0,
                "none": 0.0,
                "very_low": 0.1,
                "low": 0.25,
                "weak": 0.25,
                "medium": 0.5,
                "moderate": 0.5,
                "partial": 0.55,
                "high": 0.85,
                "strong": 0.9,
                "related": 1.0,
                "same": 1.0,
                "same_topic": 1.0,
            }
            if normalized in label_scores:
                return label_scores[normalized]
        return float(value)

    @field_validator("topic_shift", mode="before")
    @classmethod
    def _coerce_topic_shift(cls, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
            if normalized in {
                "true",
                "yes",
                "y",
                "1",
                "shift",
                "topic_shift",
                "new",
                "new_topic",
                "different",
                "unrelated",
                "off_topic",
                "major",
                "major_shift",
                "separate",
                "separate_topic",
            }:
                return True
            if normalized in {
                "false",
                "no",
                "n",
                "0",
                "same",
                "same_topic",
                "related",
                "minor",
                "no_shift",
                "continue",
                "continue_current",
            }:
                return False
        return bool(value)


ModelFactory = Callable[[str], Any]


class SemanticTopicRelationClassifier:
    """Classify whether an incoming user message remains on the current branch topic."""

    def __init__(
        self,
        *,
        settings: Settings,
        model_factory: ModelFactory | None = None,
    ) -> None:
        self.settings = settings
        self._model_factory = model_factory

    def classify(
        self,
        *,
        message: str,
        branch_history: Sequence[Any] | str,
        selected_model: str | None = None,
        on_branch: bool = False,
    ) -> SemanticTopicRelationResult:
        if not bool(getattr(self.settings, "agent_branch_recommendation_semantic_enabled", False)):
            return self.fail_closed(
                reason="Semantic branch recommendation classifier is disabled.",
                status="disabled",
            )

        model_id = self.resolve_model_id(selected_model=selected_model)
        if not model_id:
            return self.fail_closed(
                reason="No semantic branch recommendation model is configured.",
                status="semantic_classifier_failed",
            )

        try:
            model = self._create_model(model_id)
            response = model.invoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(
                        content=_user_prompt(
                            message=message,
                            branch_history=_branch_history_text(branch_history),
                            on_branch=on_branch,
                        )
                    ),
                ]
            )
            payload = _parse_json_payload(_response_text(response))
            result = SemanticTopicRelationResult.model_validate(payload)
            return result.model_copy(update={"model": model_id, "status": "ok"})
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            return self.fail_closed(
                reason=f"Semantic classifier returned invalid output: {exc}",
                model=model_id,
                status="semantic_classifier_failed",
            )
        except Exception as exc:  # noqa: BLE001 - classifier failures must fail closed.
            return self.fail_closed(
                reason=f"Semantic classifier failed: {exc}",
                model=model_id,
                status="error",
            )

    def resolve_model_id(self, *, selected_model: str | None = None) -> str | None:
        override = getattr(self.settings, "agent_branch_recommendation_semantic_model", None)
        model_id = override or selected_model or getattr(self.settings, "model", None)
        normalized = str(model_id or "").strip()
        return normalized or None

    def fail_closed(
        self,
        *,
        reason: str,
        model: str | None = None,
        status: SemanticClassifierStatus = "semantic_classifier_failed",
    ) -> SemanticTopicRelationResult:
        return SemanticTopicRelationResult(
            relatedness=1.0,
            topic_shift=False,
            relationship="unknown",
            recommended_action="continue_current",
            confidence=0.0,
            reason=reason,
            model=model,
            status=status,
        )

    def _create_model(self, model_id: str) -> Any:
        if self._model_factory is not None:
            return self._model_factory(model_id)
        from focus_agent.model_registry import create_chat_model

        return create_chat_model(model_id, temperature=0.0, settings=self.settings)


def classify_topic_relation(
    *args: Any,
    settings: Settings | None = None,
    message: str | None = None,
    branch_history: Sequence[Any] | str | None = None,
    messages: Sequence[Any] | None = None,
    values: dict[str, Any] | None = None,
    branch_meta: Any | None = None,
    selected_model: str | None = None,
    on_branch: bool | None = None,
    model_factory: ModelFactory | None = None,
    **_kwargs: Any,
) -> SemanticTopicRelationResult | dict[str, Any] | None:
    if args:
        message = str(args[0] if len(args) >= 1 else message or "")
        if len(args) >= 2 and branch_history is None and messages is None:
            messages = args[1]
        if len(args) >= 3 and branch_meta is None:
            branch_meta = args[2]

    if settings is None:
        legacy = _legacy_semantic_classifier_hook()
        if legacy is not None:
            return legacy(
                message=message or "",
                messages=list(messages or (values or {}).get("messages", []) or []),
                values=values,
                branch_meta=branch_meta,
            )
        settings = Settings.from_env()

    resolved_history: Sequence[Any] | str = branch_history if branch_history is not None else ""
    if not resolved_history:
        resolved_history = messages if messages is not None else list((values or {}).get("messages", []) or [])
    if selected_model is None and isinstance(values, dict):
        selected_model = _selected_model_from_values(values)

    classifier = SemanticTopicRelationClassifier(
        settings=settings,
        model_factory=model_factory,
    )
    return classifier.classify(
        message=message or "",
        branch_history=resolved_history,
        selected_model=selected_model,
        on_branch=bool(branch_meta is not None if on_branch is None else on_branch),
    )


classify_semantic_topic_relation = classify_topic_relation


def _branch_history_text(branch_history: Sequence[Any] | str) -> str:
    if isinstance(branch_history, str):
        return branch_history.strip()
    lines: list[str] = []
    for item in list(branch_history)[-12:]:
        text = _message_text(item)
        if not text:
            continue
        role = _message_role(item) or "message"
        lines.append(f"{role}: {text}")
    return "\n".join(lines)[-6000:]


def _legacy_semantic_classifier_hook() -> Callable[..., Any] | None:
    for module_name in (
        "focus_agent.branch_decision.service",
        "focus_agent.branch_decision.signals",
    ):
        try:
            module = __import__(module_name, fromlist=["_"])
        except ImportError:
            continue
        for attr in (
            "classify_branch_recommendation_semantic",
            "semantic_branch_recommendation_classifier",
        ):
            candidate = getattr(module, attr, None)
            if callable(candidate):
                return candidate
    return None


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        value = message.get("role") or message.get("type") or message.get("_type")
    else:
        value = getattr(message, "type", None) or getattr(message, "role", None)
    return str(value or "").strip().lower()


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
        return str(content.get("text") or content.get("content") or "").strip()
    return str(content or "").strip()


def _response_text(response: Any) -> str:
    content = (
        response.get("content")
        if isinstance(response, dict)
        else getattr(response, "content", response)
    )
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            elif item is not None:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    return str(content or "").strip()


def _selected_model_from_values(values: dict[str, Any]) -> str | None:
    for key in ("selected_model", "model", "model_id"):
        value = values.get(key)
        text = str(value or "").strip()
        if text:
            return text
    return None


def _parse_json_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty response")
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if match is None:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise TypeError("semantic classifier response must be a JSON object")
    return payload


def _user_prompt(*, message: str, branch_history: str, on_branch: bool) -> str:
    location = "a child branch" if on_branch else "the root/current thread"
    return (
        "Classify only the semantic relationship between the incoming user message and "
        "the current branch history. Do not answer the user request.\n\n"
        f"Current location: {location}\n\n"
        "Current branch history:\n"
        f"{branch_history or '(no prior branch history)'}\n\n"
        "Incoming user message:\n"
        f"{str(message or '').strip()}\n\n"
        "Return JSON with keys: relatedness, topic_shift, relationship, "
        "recommended_action, confidence, reason. recommended_action must be one of "
        "continue_current, fork_child_branch, fork_sibling_branch. Use continue_current "
        "when the message continues, clarifies, corrects, or asks a follow-up on the "
        "same topic. Use fork_child_branch for a related subtopic that should be explored "
        "separately. Use fork_sibling_branch for an unrelated or parallel topic when "
        "already inside a branch; otherwise prefer fork_child_branch for unrelated root "
        "topic shifts."
    )


_SYSTEM_PROMPT = (
    "You are a conservative semantic topic relation classifier for branch recommendations. "
    "You do not generate assistant answers. You only decide whether the incoming message "
    "is semantically related to the current branch history and emit strict JSON."
)


__all__ = [
    "SemanticBranchAction",
    "SemanticClassifierStatus",
    "SemanticTopicRelationClassifier",
    "SemanticTopicRelationResult",
    "classify_semantic_topic_relation",
    "classify_topic_relation",
]
