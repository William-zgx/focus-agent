from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from langchain.messages import HumanMessage
from langgraph.types import Command

from focus_agent.services.branches.actions import branch_handoff_message_from_text
from focus_agent.services.chat import ChatService

from .replay_models import HarnessResumeRequest, HarnessRunRequest


def _prepare_run_payload(
    *,
    thread_id: str,
    user_id: str,
    payload: HarnessRunRequest,
    chat: ChatService,
) -> tuple[dict[str, Any], Any, Any, dict[str, Any]]:
    message = _run_message_from_payload(payload)
    selection = chat._select_skills_for_message(
        message=message,
        explicit_skill_hints=tuple(payload.skill_hints),
    )
    context, branch_meta, initial_values = chat._preflight_thread_access(
        thread_id=thread_id,
        user_id=user_id,
        require_writable=True,
    )
    active_skill_ids = _merged_skill_ids(
        selection.skill_ids,
        initial_values.get("active_skill_ids", []),
    )
    if active_skill_ids:
        context, branch_meta, initial_values = chat._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            explicit_skill_hints=active_skill_ids,
            require_writable=True,
        )
    selected_model = payload.model
    if selected_model is None:
        selected_model = getattr(getattr(chat, "runtime", None), "settings", None)
        if selected_model is not None:
            selected_model = getattr(selected_model, "model", None)
    input_messages = _run_input_messages_for_state(
        message=message,
        payload=payload,
        initial_values=initial_values,
    )
    graph_payload: dict[str, Any] = {
        "messages": input_messages,
        "task_brief": selection.stripped_message or message,
        "active_skill_ids": list(active_skill_ids),
        "selected_model": selected_model,
        "selected_thinking_mode": chat._effective_thinking_mode(
            model_id=selected_model,
            thinking_mode=payload.thinking_mode,
        ),
    }
    if payload.input:
        graph_payload.update(
            {key: value for key, value in payload.input.items() if key != "messages"}
        )
    if selection.prompt_mode is not None:
        graph_payload["prompt_mode"] = selection.prompt_mode
    return graph_payload, context, branch_meta, initial_values


def _merged_skill_ids(*skill_id_groups: Any) -> tuple[str, ...]:
    skill_ids: list[str] = []
    seen: set[str] = set()
    for group in skill_id_groups:
        raw_items = [group] if isinstance(group, str) else list(group or [])
        for raw_item in raw_items:
            skill_id = str(raw_item or "").strip()
            if not skill_id or skill_id in seen:
                continue
            seen.add(skill_id)
            skill_ids.append(skill_id)
    return tuple(skill_ids)


def _run_input_messages_for_state(
    *,
    message: str,
    payload: HarnessRunRequest,
    initial_values: dict[str, Any],
) -> list[HumanMessage]:
    if _is_branch_handoff_auto_run(payload) and _latest_human_message_matches(
        initial_values.get("messages"),
        message,
    ):
        return []
    return [HumanMessage(content=message)]


def _latest_human_message_matches(messages: Any, text: str) -> bool:
    normalized = _normalized_message_text(text)
    if not normalized:
        return False
    for message in reversed(list(messages or [])):
        if isinstance(message, HumanMessage):
            return _normalized_message_text(message.content) == normalized
        if isinstance(message, dict):
            message_type = str(message.get("type") or message.get("role") or "").lower()
            if message_type in {"human", "user"}:
                return _normalized_message_text(message.get("content")) == normalized
            if message_type in {"ai", "assistant", "tool"}:
                return False
            continue
        message_type = str(
            getattr(message, "type", message.__class__.__name__.replace("Message", "").lower())
            or ""
        ).lower()
        if message_type == "human":
            return _normalized_message_text(getattr(message, "content", "")) == normalized
        if message_type in {"ai", "assistant", "tool"}:
            return False
    return False


def _normalized_message_text(value: Any) -> str:
    if isinstance(value, list):
        text = " ".join(
            str(item.get("text") or item.get("content") or item)
            if isinstance(item, dict)
            else str(item)
            for item in value
            if item is not None
        )
    elif isinstance(value, dict):
        text = str(value.get("text") or value.get("content") or "")
    else:
        text = str(value or "")
    return " ".join(text.split())


def _prepare_resume_payload(
    *,
    thread_id: str,
    user_id: str,
    payload: HarnessResumeRequest,
    chat: ChatService,
) -> tuple[Command, Any, Any, dict[str, Any]]:
    context, branch_meta, initial_values = chat._preflight_thread_access(
        thread_id=thread_id,
        user_id=user_id,
        explicit_skill_hints=(),
        require_writable=True,
    )
    return Command(resume=payload.resume), context, branch_meta, initial_values


def _message_from_payload(payload: HarnessRunRequest) -> str:
    if payload.message is not None:
        return payload.message
    if payload.input and payload.input.get("message") is not None:
        return str(payload.input["message"])
    raise HTTPException(status_code=400, detail="Harness run requires a message.")


def _run_message_from_payload(payload: HarnessRunRequest) -> str:
    message = _message_from_payload(payload)
    if not _is_branch_handoff_auto_run(payload):
        return message
    return branch_handoff_message_from_text(message) or message


def _is_branch_handoff_auto_run(payload: HarnessRunRequest) -> bool:
    return bool((payload.metadata or {}).get("branch_handoff_auto_run"))


def _message_text_from_graph_payload(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    messages = list(payload.get("messages") or [])
    if not messages:
        return ""
    first = messages[0]
    content = first.get("content") if isinstance(first, dict) else getattr(first, "content", "")
    if isinstance(content, list):
        return " ".join(
            str(item.get("text") or item.get("content") or item)
            for item in content
            if item is not None
        ).strip()
    return str(content or "").strip()


__all__ = [
    "_is_branch_handoff_auto_run",
    "_latest_human_message_matches",
    "_message_from_payload",
    "_message_text_from_graph_payload",
    "_normalized_message_text",
    "_prepare_resume_payload",
    "_prepare_run_payload",
    "_run_input_messages_for_state",
    "_run_message_from_payload",
]
