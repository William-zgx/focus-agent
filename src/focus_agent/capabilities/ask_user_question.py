"""Interrupt contract for the ask_user_question human-input tool."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

ASK_USER_QUESTION_KIND = "ask_user_question"
ASK_USER_QUESTION_POLICY_VERSION = "ask_user_question.v1"
ASK_USER_QUESTION_TOOL_NAME = "ask_user_question"
_MAX_QUESTIONS = 4
_MIN_OPTIONS = 2
_MAX_OPTIONS = 4
_OTHER_LABEL = "Other"


def normalize_ask_user_questions(raw_questions: Any) -> list[dict[str, Any]]:
    """Validate and normalize model-provided questions into interrupt form."""
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ValueError("questions must be a non-empty array.")
    if len(raw_questions) > _MAX_QUESTIONS:
        raise ValueError(f"questions must contain at most {_MAX_QUESTIONS} items.")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_questions):
        if not isinstance(item, dict):
            raise ValueError(f"questions[{index}] must be an object.")
        question = str(item.get("question") or "").strip()
        if not question:
            raise ValueError(f"questions[{index}].question is required.")
        header = str(item.get("header") or f"Q{index + 1}").strip()
        if len(header) > 32:
            header = header[:32]
        multi_select = bool(item.get("multi_select", False))
        raw_options = item.get("options")
        if not isinstance(raw_options, list):
            raise ValueError(f"questions[{index}].options must be an array.")
        if not (_MIN_OPTIONS <= len(raw_options) <= _MAX_OPTIONS):
            raise ValueError(
                f"questions[{index}].options must have between {_MIN_OPTIONS} and {_MAX_OPTIONS} items."
            )
        options: list[dict[str, Any]] = []
        seen_labels: set[str] = set()
        for option_index, option in enumerate(raw_options):
            if not isinstance(option, dict):
                raise ValueError(f"questions[{index}].options[{option_index}] must be an object.")
            label = str(option.get("label") or "").strip()
            if not label:
                raise ValueError(
                    f"questions[{index}].options[{option_index}].label is required."
                )
            label_key = label.casefold()
            if label_key in seen_labels:
                raise ValueError(f"questions[{index}].options has duplicate label {label!r}.")
            seen_labels.add(label_key)
            description = str(option.get("description") or "").strip()
            option_payload: dict[str, Any] = {
                "label": label,
                "description": description,
            }
            preview = option.get("preview")
            if isinstance(preview, str) and preview.strip():
                option_payload["preview"] = preview.strip()
            options.append(option_payload)
        question_id = str(item.get("id") or f"q{index}").strip() or f"q{index}"
        normalized.append(
            {
                "id": question_id,
                "question": question,
                "header": header,
                "options": options,
                "multi_select": multi_select,
            }
        )
    return normalized


def build_ask_user_question_interrupt_id(
    *,
    tool_call_id: str,
    questions: list[dict[str, Any]],
) -> str:
    fingerprint = json.dumps(
        {
            "tool_call_id": tool_call_id,
            "questions": questions,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"ask-user-question:{tool_call_id}:{digest}"


def build_ask_user_question_interrupt_payload(
    *,
    tool_call_id: str,
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = normalize_ask_user_questions(questions)
    interrupt_id = build_ask_user_question_interrupt_id(
        tool_call_id=tool_call_id,
        questions=normalized,
    )
    return {
        "kind": ASK_USER_QUESTION_KIND,
        "interrupt_id": interrupt_id,
        "tool_name": ASK_USER_QUESTION_TOOL_NAME,
        "tool_call_id": tool_call_id,
        "questions": normalized,
        "policy_version": ASK_USER_QUESTION_POLICY_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
    }


def ask_user_question_response_error(
    response: Any,
    *,
    interrupt_id: str,
    tool_call_id: str,
    questions: list[dict[str, Any]],
) -> str | None:
    if not isinstance(response, dict):
        return "ask_user_question response must be an object."
    if response.get("kind") != ASK_USER_QUESTION_KIND:
        return "ask_user_question response kind is invalid."
    if response.get("interrupt_id") != interrupt_id:
        return "ask_user_question response interrupt_id does not match."
    if response.get("tool_call_id") != tool_call_id:
        return "ask_user_question response tool_call_id does not match."
    answers = response.get("answers")
    if not isinstance(answers, list) or not answers:
        return "ask_user_question response answers must be a non-empty array."
    question_by_id = {str(item["id"]): item for item in questions}
    if len(answers) != len(questions):
        return "ask_user_question response must answer every question exactly once."
    seen_ids: set[str] = set()
    for index, answer in enumerate(answers):
        if not isinstance(answer, dict):
            return f"answers[{index}] must be an object."
        question_id = str(answer.get("question_id") or "").strip()
        if not question_id or question_id not in question_by_id:
            return f"answers[{index}].question_id is invalid."
        if question_id in seen_ids:
            return f"answers[{index}].question_id is duplicated."
        seen_ids.add(question_id)
        question = question_by_id[question_id]
        selected = answer.get("selected_labels")
        if not isinstance(selected, list):
            return f"answers[{index}].selected_labels must be an array."
        labels = [str(item).strip() for item in selected if str(item).strip()]
        other_text = answer.get("other_text")
        other_text_value = (
            str(other_text).strip() if isinstance(other_text, str) and other_text.strip() else None
        )
        option_labels = {str(option["label"]) for option in question["options"]}
        option_labels_cf = {label.casefold(): label for label in option_labels}
        resolved: list[str] = []
        for label in labels:
            if label.casefold() == _OTHER_LABEL.casefold():
                if not other_text_value:
                    return f"answers[{index}] selected Other but other_text is empty."
                continue
            canonical = option_labels_cf.get(label.casefold())
            if canonical is None:
                return f"answers[{index}] selected unknown option {label!r}."
            resolved.append(canonical)
        if question.get("multi_select"):
            if not resolved and not other_text_value:
                return f"answers[{index}] must select at least one option."
        else:
            selection_count = len(resolved) + (1 if other_text_value else 0)
            if selection_count != 1:
                return f"answers[{index}] must select exactly one option."
    return None


def parse_ask_user_question_answers(
    response: Any,
    *,
    questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return normalized answer rows for tool observation content."""
    answers_raw = response.get("answers") if isinstance(response, dict) else None
    if not isinstance(answers_raw, list):
        return []
    question_by_id = {str(item["id"]): item for item in questions}
    parsed: list[dict[str, Any]] = []
    for answer in answers_raw:
        if not isinstance(answer, dict):
            continue
        question_id = str(answer.get("question_id") or "").strip()
        question = question_by_id.get(question_id)
        if question is None:
            continue
        selected = [
            str(item).strip()
            for item in (answer.get("selected_labels") or [])
            if str(item).strip()
        ]
        option_labels_cf = {
            str(option["label"]).casefold(): str(option["label"])
            for option in question["options"]
        }
        resolved_labels: list[str] = []
        selected_other = False
        for label in selected:
            if label.casefold() == _OTHER_LABEL.casefold():
                selected_other = True
                continue
            canonical = option_labels_cf.get(label.casefold())
            if canonical is not None:
                resolved_labels.append(canonical)
        other_text = answer.get("other_text")
        other_text_value = (
            str(other_text).strip() if isinstance(other_text, str) and other_text.strip() else None
        )
        if other_text_value:
            selected_other = True
        parsed.append(
            {
                "question_id": question_id,
                "header": question.get("header"),
                "question": question.get("question"),
                "multi_select": bool(question.get("multi_select")),
                "selected_labels": resolved_labels,
                "selected_other": selected_other,
                "other_text": other_text_value,
            }
        )
    return parsed


def format_ask_user_question_tool_result(
    *,
    questions: list[dict[str, Any]],
    answers: list[dict[str, Any]],
) -> str:
    return json.dumps(
        {
            "status": "answered",
            "tool": ASK_USER_QUESTION_TOOL_NAME,
            "questions": questions,
            "answers": answers,
        },
        ensure_ascii=False,
    )


__all__ = [
    "ASK_USER_QUESTION_KIND",
    "ASK_USER_QUESTION_POLICY_VERSION",
    "ASK_USER_QUESTION_TOOL_NAME",
    "ask_user_question_response_error",
    "build_ask_user_question_interrupt_id",
    "build_ask_user_question_interrupt_payload",
    "format_ask_user_question_tool_result",
    "normalize_ask_user_questions",
    "parse_ask_user_question_answers",
]
