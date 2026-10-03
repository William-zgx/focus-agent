"""Small HTTP client for typed System One decision models."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from .model_registry import model_protocol, parse_model_id, resolve_model_config
from .runtime.http_client import shared_sync_http_client

DecisionQuestionType = Literal["choice", "noul", "score"]


class DecisionModelError(RuntimeError):
    """Base class for decision model failures."""


class DecisionModelConfigurationError(ValueError, DecisionModelError):
    """Raised when a model or request cannot be configured safely."""


class DecisionModelResponseError(ValueError, DecisionModelError):
    """Raised when a decision model response violates its typed contract."""


class DecisionModelTransportError(DecisionModelError):
    """Raised when the decision model cannot be reached."""


class DecisionModelHTTPError(DecisionModelTransportError):
    """Raised for an HTTP error while preserving its status for fallback policy."""

    def __init__(self, status_code: int) -> None:
        self.status_code = int(status_code)
        super().__init__(f"Decision model request failed with HTTP status {self.status_code}.")


@dataclass(frozen=True, slots=True)
class DecisionModelAnswer:
    question_id: str
    type: DecisionQuestionType
    choice: str | None = None
    noul: float | None = None
    score: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class DecisionModelResult:
    model: str
    answers: dict[str, DecisionModelAnswer]
    usage: dict[str, Any] = field(default_factory=dict)


def evaluate_decision_model(
    *,
    settings: Any,
    model_id: str,
    state: Any,
    questions: Mapping[str, Mapping[str, Any]],
    timeout_seconds: float,
) -> DecisionModelResult:
    """Evaluate one typed decision request against a configured System One model."""

    resolved = resolve_model_config(model_id, settings=settings)
    _, remote_model_name = parse_model_id(model_id, settings=settings)
    protocol = str(model_protocol(model_id, settings=settings) or "chat")
    protocol = protocol.strip().lower().replace("-", "_")
    if protocol != "system_one":
        raise DecisionModelConfigurationError(
            f"Model {resolved.model_id!r} is not configured for the system_one protocol."
        )

    endpoint = str(resolved.client_kwargs.get("base_url") or "").strip().rstrip("/")
    if not endpoint:
        raise DecisionModelConfigurationError("System One base URL is not configured.")
    api_key = str(resolved.client_kwargs.get("api_key") or "").strip()
    if not api_key:
        raise DecisionModelConfigurationError("System One API key is not configured.")

    timeout = _validate_timeout(timeout_seconds)
    normalized_questions = _validate_questions(questions)
    request_payload = {
        "model": remote_model_name,
        "state": state,
        "questions": normalized_questions,
    }
    _validate_json_request(request_payload)

    try:
        response = shared_sync_http_client().post(
            f"{endpoint}/systemone",
            json=request_payload,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
    except httpx.TimeoutException as exc:
        raise DecisionModelTransportError("Decision model request timed out.") from exc
    except httpx.RequestError as exc:
        raise DecisionModelTransportError(
            "Decision model request failed to reach the service."
        ) from exc

    if response.status_code >= 400:
        raise DecisionModelHTTPError(response.status_code)
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise DecisionModelResponseError("Decision model response was not valid JSON.") from exc
    return _parse_response(payload, normalized_questions)


def _validate_timeout(value: float) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise DecisionModelConfigurationError(
            "timeout_seconds must be a positive finite number."
        ) from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise DecisionModelConfigurationError("timeout_seconds must be a positive finite number.")
    return timeout


def _validate_questions(
    questions: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not isinstance(questions, Mapping) or not questions:
        raise DecisionModelConfigurationError("questions must be a non-empty object.")
    normalized: dict[str, dict[str, Any]] = {}
    for raw_question_id, raw_definition in questions.items():
        if not isinstance(raw_question_id, str) or not raw_question_id.strip():
            raise DecisionModelConfigurationError("Question ids must be non-empty strings.")
        if not isinstance(raw_definition, Mapping):
            raise DecisionModelConfigurationError("Each question must be an object.")
        question_id = raw_question_id.strip()
        if (
            question_id != raw_question_id
            or len(question_id) > 128
            or any(char.isspace() for char in question_id)
        ):
            raise DecisionModelConfigurationError("Question ids must be non-whitespace names.")
        definition = dict(raw_definition)
        question_type = definition.get("type")
        if question_type not in {"choice", "noul", "score"}:
            raise DecisionModelConfigurationError(
                "Each question type must be choice, noul, or score."
            )
        criteria = definition.get("criteria")
        if question_type == "choice":
            if not isinstance(criteria, Mapping) or not criteria or len(criteria) > 255:
                raise DecisionModelConfigurationError(
                    "Choice criteria must contain between 1 and 255 options."
                )
            if any(
                not isinstance(option, str) or not option.strip() or option != option.strip()
                for option in criteria
            ):
                raise DecisionModelConfigurationError(
                    "Choice criteria names must be non-empty strings."
                )
        elif question_type == "score":
            if not isinstance(criteria, list) or not 2 <= len(criteria) <= 10:
                raise DecisionModelConfigurationError(
                    "Score criteria must contain between 2 and 10 levels."
                )
        elif criteria is not None and not isinstance(criteria, Mapping):
            raise DecisionModelConfigurationError("Noul criteria must be an object or null.")
        normalized[question_id] = definition
    return normalized


def _validate_json_request(payload: Mapping[str, Any]) -> None:
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise DecisionModelConfigurationError(
            "Decision model request must be JSON serializable."
        ) from exc


def _parse_response(
    payload: Any,
    questions: Mapping[str, Mapping[str, Any]],
) -> DecisionModelResult:
    if not isinstance(payload, Mapping):
        raise DecisionModelResponseError("Decision model response must be an object.")
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise DecisionModelResponseError("Decision model response is missing model.")
    answers_payload = payload.get("answers")
    if not isinstance(answers_payload, Mapping):
        raise DecisionModelResponseError("Decision model response is missing answers.")
    if set(answers_payload) != set(questions):
        raise DecisionModelResponseError("Decision model response answers do not match questions.")
    answers: dict[str, DecisionModelAnswer] = {}
    for question_id, definition in questions.items():
        answer = answers_payload.get(question_id)
        if not isinstance(answer, Mapping):
            raise DecisionModelResponseError("Each decision answer must be an object.")
        answers[question_id] = _parse_answer(question_id, definition, answer)
    usage = payload.get("usage")
    if usage is None:
        normalized_usage: dict[str, Any] = {}
    elif isinstance(usage, Mapping):
        normalized_usage = dict(usage)
    else:
        raise DecisionModelResponseError("Decision model usage must be an object.")
    return DecisionModelResult(model=model.strip(), answers=answers, usage=normalized_usage)


def _parse_answer(
    question_id: str,
    definition: Mapping[str, Any],
    answer: Mapping[str, Any],
) -> DecisionModelAnswer:
    question_type = definition["type"]
    if answer.get("type") != question_type:
        raise DecisionModelResponseError("Decision answer type does not match its question.")
    if question_type == "choice":
        criteria = definition["criteria"]
        choice = answer.get("choice")
        if not isinstance(choice, str) or choice not in criteria:
            raise DecisionModelResponseError("Decision choice is outside its declared criteria.")
        probabilities = _probabilities(answer.get("probabilities"), criteria)
        confidence = _probability(answer.get("confidence"), "confidence")
        return DecisionModelAnswer(
            question_id=question_id,
            type="choice",
            choice=choice,
            probabilities=probabilities,
            confidence=confidence,
        )
    if question_type == "score":
        criteria = definition["criteria"]
        score = _number(answer.get("score"), "score")
        if score < 0 or score > len(criteria) - 1:
            raise DecisionModelResponseError("Decision score is outside its declared criteria.")
        probabilities = _probabilities(
            answer.get("probabilities"),
            {str(index): value for index, value in enumerate(criteria)},
        )
        confidence = _probability(answer.get("confidence"), "confidence")
        return DecisionModelAnswer(
            question_id=question_id,
            type="score",
            score=score,
            probabilities=probabilities,
            confidence=confidence,
        )
    noul = _probability(answer.get("noul"), "noul")
    return DecisionModelAnswer(question_id=question_id, type="noul", noul=noul)


def _probabilities(raw: Any, criteria: Mapping[str, Any]) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        raise DecisionModelResponseError("Decision probabilities must be an object.")
    normalized = {str(key): value for key, value in raw.items()}
    expected = {str(key) for key in criteria}
    if set(normalized) != expected:
        raise DecisionModelResponseError("Decision probabilities do not match criteria.")
    probabilities = {key: _probability(value, "probability") for key, value in normalized.items()}
    if not math.isclose(sum(probabilities.values()), 1.0, rel_tol=1e-3, abs_tol=1e-3):
        raise DecisionModelResponseError("Decision probabilities must sum to one.")
    return probabilities


def _probability(raw: Any, field_name: str) -> float:
    value = _number(raw, field_name)
    if value < 0 or value > 1:
        raise DecisionModelResponseError(f"Decision {field_name} must be between zero and one.")
    return value


def _number(raw: Any, field_name: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise DecisionModelResponseError(f"Decision {field_name} must be a finite number.")
    value = float(raw)
    if not math.isfinite(value):
        raise DecisionModelResponseError(f"Decision {field_name} must be a finite number.")
    return value


__all__ = [
    "DecisionModelAnswer",
    "DecisionModelConfigurationError",
    "DecisionModelError",
    "DecisionModelHTTPError",
    "DecisionModelResponseError",
    "DecisionModelResult",
    "DecisionModelTransportError",
    "DecisionQuestionType",
    "evaluate_decision_model",
]
