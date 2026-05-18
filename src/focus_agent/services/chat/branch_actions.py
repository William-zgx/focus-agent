from __future__ import annotations

import logging
from typing import Any

from langchain.messages import AIMessage, HumanMessage

from ...core.repo_call import has_repo_method
from ...observability.tracing import build_trace_correlation
from ..branch_actions import (
    branch_handoff_message_from_text,
    branch_action_audit_event,
    build_branch_action_proposal,
    dismissal_message,
    execution_message,
    infer_suggested_branch_name,
    is_branch_action_confirmation,
    is_branch_action_dismissal,
    is_branch_action_request,
    latest_pending_branch_action,
    mark_branch_action_dismissed,
    mark_branch_action_executed,
    mark_branch_action_failed,
    normalize_branch_actions,
    proposal_message,
    replace_branch_action,
    requested_branch_action_kind,
    serialize_branch_actions,
    target_parent_thread_id,
)

logger = logging.getLogger("focus_agent.branches")


def branch_action_intent(*, values: dict[str, Any], message: str) -> str | None:
    pending = latest_pending_branch_action(values.get("branch_actions"))
    if pending is not None and is_branch_action_confirmation(message):
        return "execute"
    if pending is not None and is_branch_action_dismissal(message):
        return "dismiss"
    if is_branch_action_request(message):
        return "propose"
    return None


def _message_text(message: Any) -> str:
    content = (
        message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
    )
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text))
            elif item is not None:
                parts.append(str(item))
        return " ".join(parts).strip()
    return str(content or "").strip()


def _is_human_message(message: Any) -> bool:
    if isinstance(message, HumanMessage):
        return True
    if isinstance(message, dict):
        return str(message.get("type") or message.get("role") or "").lower() in {"human", "user"}
    return False


def _branch_handoff_text_from_message(message: str | None) -> str | None:
    return branch_handoff_message_from_text(message)


def _latest_branch_handoff_text(messages: list[Any]) -> str | None:
    for message in reversed(messages):
        if not _is_human_message(message):
            continue
        text = _message_text(message)
        if not text:
            continue
        handoff_text = _branch_handoff_text_from_message(text)
        if handoff_text:
            return handoff_text
        if (
            is_branch_action_request(text)
            or is_branch_action_confirmation(text)
            or is_branch_action_dismissal(text)
        ):
            continue
        return text
    return None


def _contains_human_message(messages: list[Any], text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    for message in messages:
        if not _is_human_message(message):
            continue
        if " ".join(_message_text(message).split()) == normalized:
            return True
    return False


def _carry_handoff_text_to_branch(
    *,
    service: Any,
    child_thread_id: str,
    handoff_text: str | None,
) -> None:
    text = str(handoff_text or "").strip()
    if not text or not has_repo_method(service.runtime.graph, "update_state"):
        return
    try:
        child_values = service._safe_get_values(child_thread_id)
        if _contains_human_message(list(child_values.get("messages") or []), text):
            return
        service.runtime.graph.update_state(
            {"configurable": {"thread_id": child_thread_id}},
            {"messages": [HumanMessage(content=text)]},
            as_node="bootstrap_turn",
        )
    except Exception:
        logger.warning(
            "failed to carry branch handoff message",
            extra={"child_thread_id": child_thread_id},
            exc_info=True,
        )


def _carry_branch_action_handoff_if_needed(
    *,
    service: Any,
    action: Any,
    branch_record: Any | None,
    source_values: dict[str, Any],
    user_message: str | None,
) -> None:
    if branch_record is None:
        return
    child_thread_id = str(getattr(branch_record, "child_thread_id", "") or "")
    if not child_thread_id:
        return
    handoff_text = (
        branch_handoff_message_from_text(getattr(action, "handoff_message", None))
        or _branch_handoff_text_from_message(user_message)
        or _latest_branch_handoff_text(list(source_values.get("messages") or []))
    )
    _carry_handoff_text_to_branch(
        service=service,
        child_thread_id=child_thread_id,
        handoff_text=handoff_text,
    )


def _sync_executed_branch_action_to_child(
    *,
    service: Any,
    branch_record: Any | None,
    executed_action: Any,
) -> None:
    child_thread_id = str(getattr(branch_record, "child_thread_id", "") or "")
    if not child_thread_id:
        return
    try:
        child_values = service._safe_get_values(child_thread_id)
        child_actions = normalize_branch_actions(child_values.get("branch_actions"))
        if not any(action.action_id == executed_action.action_id for action in child_actions):
            return
        service._update_branch_action_state(
            thread_id=child_thread_id,
            actions=replace_branch_action(child_actions, executed_action),
        )
    except Exception:
        logger.warning(
            "failed to sync executed branch action to child thread",
            extra={"child_thread_id": child_thread_id, "action_id": executed_action.action_id},
            exc_info=True,
        )


def build_branch_action_proposal_result(
    *,
    service: Any,
    thread_id: str,
    user_id: str,
    message: str,
    request_id: str | None,
) -> dict[str, Any]:
    context, branch_meta, values = service._preflight_thread_access(
        thread_id=thread_id,
        user_id=user_id,
        require_writable=True,
    )
    kind = requested_branch_action_kind(message, branch_meta)
    kind, target_parent = target_parent_thread_id(
        source_thread_id=thread_id,
        branch_meta=branch_meta,
        kind=kind,
    )
    previous_actions = normalize_branch_actions(values.get("branch_actions"))
    actions = [
        mark_branch_action_dismissed(action) if action.status.value == "pending" else action
        for action in previous_actions
    ]
    recent_messages = list(values.get("messages", []) or [])
    action = build_branch_action_proposal(
        kind=kind,
        root_thread_id=context.root_thread_id,
        source_thread_id=thread_id,
        target_parent_thread_id=target_parent,
        suggested_branch_name=infer_suggested_branch_name(message, recent_messages),
        reason="User requested a branch switch from chat.",
        handoff_message=_branch_handoff_text_from_message(message)
        or _latest_branch_handoff_text(recent_messages),
    )
    actions.append(action)
    is_chinese = service._is_chinese_text(message)
    assistant_text = proposal_message(action, is_chinese=is_chinese)
    audit = branch_action_audit_event(
        user_id=user_id,
        thread_id=thread_id,
        action=action,
        decision="proposed",
        reason="chat_branch_action_request",
        request_id=request_id,
    )
    service._update_branch_action_state(
        thread_id=thread_id,
        actions=actions,
        audit_event=audit,
        messages=[HumanMessage(content=message), AIMessage(content=assistant_text)],
    )
    thread_state = service.get_thread_state(
        thread_id=thread_id, user_id=user_id, request_id=request_id
    )
    return {
        "kind": "proposed",
        "message": assistant_text,
        "thread_state": thread_state,
        "branch_action": action.model_dump(mode="json"),
    }


def execute_branch_action_locked(
    *,
    service: Any,
    thread_id: str,
    action_id: str,
    user_id: str,
    request_id: str | None = None,
    user_message: str | None = None,
) -> dict[str, Any]:
    context, branch_meta, values = service._preflight_thread_access(
        thread_id=thread_id,
        user_id=user_id,
        require_writable=True,
    )
    del branch_meta
    actions = normalize_branch_actions(values.get("branch_actions"))
    action = next((item for item in actions if item.action_id == action_id), None)
    if action is None:
        raise KeyError(action_id)
    if action.status.value != "pending":
        raise ValueError(f"Branch action {action_id} is not pending.")

    from .service import execute_branch_action_navigation

    try:
        branch_record, navigation = execute_branch_action_navigation(
            action=action,
            user_id=user_id,
            branch_service=service.runtime.branch_service,
        )
        _carry_branch_action_handoff_if_needed(
            service=service,
            action=action,
            branch_record=branch_record,
            source_values=values,
            user_message=user_message,
        )
    except Exception as exc:
        failed = mark_branch_action_failed(action, str(exc))
        service._update_branch_action_state(
            thread_id=thread_id,
            actions=replace_branch_action(actions, failed),
            audit_event=branch_action_audit_event(
                user_id=user_id,
                thread_id=thread_id,
                action=failed,
                decision="failed",
                reason=str(exc),
                request_id=request_id,
            ),
        )
        raise

    executed = mark_branch_action_executed(action, navigation=navigation)
    is_chinese = service._is_chinese_text(user_message or action.reason or "")
    assistant_text = execution_message(
        executed,
        branch_name=getattr(branch_record, "branch_name", None),
        is_chinese=is_chinese,
    )
    messages: list[Any] = []
    if user_message is not None:
        messages.append(HumanMessage(content=user_message))
    messages.append(AIMessage(content=assistant_text))
    service._update_branch_action_state(
        thread_id=thread_id,
        actions=replace_branch_action(actions, executed),
        audit_event=branch_action_audit_event(
            user_id=user_id,
            thread_id=thread_id,
            action=executed,
            decision="executed",
            reason="user_confirmed",
            request_id=request_id,
        ),
        messages=messages,
    )
    _sync_executed_branch_action_to_child(
        service=service,
        branch_record=branch_record,
        executed_action=executed,
    )
    latest_context, latest_branch_meta, _ = service._context_for_thread(
        thread_id=thread_id, user_id=user_id
    )
    del context
    thread_state = service._response_payload(
        thread_id=thread_id,
        user_id=user_id,
        context=latest_context,
        branch_meta=latest_branch_meta,
        interrupts=service._safe_get_interrupts(thread_id),
        trace_correlation=build_trace_correlation(
            settings=service.runtime.settings, request_id=request_id
        ),
    )
    return {
        "kind": "executed",
        "message": assistant_text,
        "thread_state": thread_state,
        "branch_action": executed.model_dump(mode="json"),
        "branch_record": branch_record.model_dump(mode="json")
        if branch_record is not None
        else None,
        "navigation": navigation.model_dump(mode="json") if navigation is not None else None,
    }


def dismiss_branch_action_locked(
    *,
    service: Any,
    thread_id: str,
    action_id: str,
    user_id: str,
    request_id: str | None = None,
    user_message: str | None = None,
) -> dict[str, Any]:
    service._preflight_thread_access(
        thread_id=thread_id,
        user_id=user_id,
        require_writable=True,
    )
    values = service._safe_get_values(thread_id)
    actions = normalize_branch_actions(values.get("branch_actions"))
    action = next((item for item in actions if item.action_id == action_id), None)
    if action is None:
        raise KeyError(action_id)
    if action.status.value != "pending":
        raise ValueError(f"Branch action {action_id} is not pending.")
    dismissed = mark_branch_action_dismissed(action)
    is_chinese = service._is_chinese_text(user_message or action.reason or "")
    assistant_text = dismissal_message(is_chinese=is_chinese)
    messages: list[Any] = []
    if user_message is not None:
        messages.append(HumanMessage(content=user_message))
    messages.append(AIMessage(content=assistant_text))
    service._update_branch_action_state(
        thread_id=thread_id,
        actions=replace_branch_action(actions, dismissed),
        audit_event=branch_action_audit_event(
            user_id=user_id,
            thread_id=thread_id,
            action=dismissed,
            decision="dismissed",
            reason="user_dismissed",
            request_id=request_id,
        ),
        messages=messages,
    )
    return service.get_thread_state(thread_id=thread_id, user_id=user_id, request_id=request_id)


def handle_branch_action_turn(
    *,
    service: Any,
    thread_id: str,
    user_id: str,
    message: str,
    request_id: str | None = None,
) -> dict[str, Any] | None:
    context, branch_meta, values = service._context_for_thread(thread_id=thread_id, user_id=user_id)
    service._ensure_access(thread_id=thread_id, user_id=user_id, context=context)
    intent = branch_action_intent(values=values, message=message)
    if intent is None:
        return None
    with service._thread_turn_lease(thread_id=thread_id) as turn_lease:
        context, branch_meta, values = service._context_for_thread(
            thread_id=thread_id, user_id=user_id
        )
        service._ensure_access(thread_id=thread_id, user_id=user_id, context=context)
        intent = branch_action_intent(values=values, message=message)
        if intent is None:
            return None
        if intent == "propose":
            result = service._build_branch_action_proposal(
                thread_id=thread_id,
                user_id=user_id,
                message=message,
                request_id=request_id,
            )
            turn_lease.raise_if_lost()
            return result
        pending = latest_pending_branch_action(values.get("branch_actions"))
        if pending is None:
            return None
        if intent == "execute":
            result = service._execute_branch_action_locked(
                thread_id=thread_id,
                action_id=pending.action_id,
                user_id=user_id,
                request_id=request_id,
                user_message=message,
            )
            turn_lease.raise_if_lost()
            return result
        if intent == "dismiss":
            thread_state = service._dismiss_branch_action_locked(
                thread_id=thread_id,
                action_id=pending.action_id,
                user_id=user_id,
                request_id=request_id,
                user_message=message,
            )
            result = {
                "kind": "dismissed",
                "message": service._branch_action_dismissal_message(message),
                "thread_state": thread_state,
                "branch_action": next(
                    (
                        item
                        for item in thread_state.get("branch_actions", [])
                        if isinstance(item, dict) and item.get("action_id") == pending.action_id
                    ),
                    None,
                ),
            }
            turn_lease.raise_if_lost()
            return result
        return None


class ChatBranchActionFacadeMixin:
    @staticmethod
    def _is_chinese_text(text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in str(text or ""))

    def _branch_action_intent(
        self, *, values: dict[str, Any], branch_meta: Any | None, message: str
    ) -> str | None:
        del branch_meta
        return branch_action_intent(values=values, message=message)

    def _update_branch_action_state(
        self,
        *,
        thread_id: str,
        actions: list[Any],
        audit_event: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
    ) -> None:
        update: dict[str, Any] = {
            "branch_actions": serialize_branch_actions(normalize_branch_actions(actions))
        }
        if audit_event is not None:
            values = self._safe_get_values(thread_id)
            audit = [
                item
                for item in list(values.get("branch_action_audit") or [])
                if isinstance(item, dict)
            ]
            update["branch_action_audit"] = [*audit, audit_event]
        if messages:
            update["messages"] = messages
        if not has_repo_method(self.runtime.graph, "update_state"):
            raise RuntimeError("Conversation graph does not support branch action state updates.")
        self.runtime.graph.update_state(
            {"configurable": {"thread_id": thread_id}},
            update,
            as_node="bootstrap_turn",
        )

    def _build_branch_action_proposal(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        request_id: str | None,
    ) -> dict[str, Any]:
        return build_branch_action_proposal_result(
            service=self,
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            request_id=request_id,
        )

    def _execute_branch_action_locked(
        self,
        *,
        thread_id: str,
        action_id: str,
        user_id: str,
        request_id: str | None = None,
        user_message: str | None = None,
    ) -> dict[str, Any]:
        return execute_branch_action_locked(
            service=self,
            thread_id=thread_id,
            action_id=action_id,
            user_id=user_id,
            request_id=request_id,
            user_message=user_message,
        )

    def execute_branch_action(
        self,
        *,
        thread_id: str,
        action_id: str,
        user_id: str,
        request_id: str | None = None,
        user_message: str | None = None,
    ) -> dict[str, Any]:
        with self._thread_turn_lease(thread_id=thread_id) as turn_lease:
            result = self._execute_branch_action_locked(
                thread_id=thread_id,
                action_id=action_id,
                user_id=user_id,
                request_id=request_id,
                user_message=user_message,
            )
            turn_lease.raise_if_lost()
            return result

    def _dismiss_branch_action_locked(
        self,
        *,
        thread_id: str,
        action_id: str,
        user_id: str,
        request_id: str | None = None,
        user_message: str | None = None,
    ) -> dict[str, Any]:
        return dismiss_branch_action_locked(
            service=self,
            thread_id=thread_id,
            action_id=action_id,
            user_id=user_id,
            request_id=request_id,
            user_message=user_message,
        )

    def dismiss_branch_action(
        self,
        *,
        thread_id: str,
        action_id: str,
        user_id: str,
        request_id: str | None = None,
        user_message: str | None = None,
    ) -> dict[str, Any]:
        with self._thread_turn_lease(thread_id=thread_id) as turn_lease:
            result = self._dismiss_branch_action_locked(
                thread_id=thread_id,
                action_id=action_id,
                user_id=user_id,
                request_id=request_id,
                user_message=user_message,
            )
            turn_lease.raise_if_lost()
            return result

    def _branch_action_dismissal_message(self, message: str) -> str:
        return dismissal_message(is_chinese=self._is_chinese_text(message))

    def _handle_branch_action_turn(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        request_id: str | None = None,
    ) -> dict[str, Any] | None:
        return handle_branch_action_turn(
            service=self,
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            request_id=request_id,
        )
