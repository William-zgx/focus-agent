from __future__ import annotations

from typing import Any, AsyncIterator

from langchain.messages import AIMessage, HumanMessage

from ..observability.tracing import build_trace_correlation
from .branch_actions import (
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
    target_parent_thread_id,
)
from .chat_branch_execution import execute_branch_action_navigation
from .chat_serialization import sse_frame


def branch_action_intent(*, values: dict[str, Any], message: str) -> str | None:
    pending = latest_pending_branch_action(values.get("branch_actions"))
    if pending is not None and is_branch_action_confirmation(message):
        return "execute"
    if pending is not None and is_branch_action_dismissal(message):
        return "dismiss"
    if is_branch_action_request(message):
        return "propose"
    return None


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
        mark_branch_action_dismissed(action)
        if action.status.value == "pending"
        else action
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
    thread_state = service.get_thread_state(thread_id=thread_id, user_id=user_id, request_id=request_id)
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

    try:
        branch_record, navigation = execute_branch_action_navigation(
            action=action,
            user_id=user_id,
            branch_service=service.runtime.branch_service,
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
    latest_context, latest_branch_meta, _ = service._context_for_thread(thread_id=thread_id, user_id=user_id)
    del context
    thread_state = service._response_payload(
        thread_id=thread_id,
        user_id=user_id,
        context=latest_context,
        branch_meta=latest_branch_meta,
        interrupts=service._safe_get_interrupts(thread_id),
        trace_correlation=build_trace_correlation(settings=service.runtime.settings, request_id=request_id),
    )
    return {
        "kind": "executed",
        "message": assistant_text,
        "thread_state": thread_state,
        "branch_action": executed.model_dump(mode="json"),
        "branch_record": branch_record.model_dump(mode="json") if branch_record is not None else None,
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
        context, branch_meta, values = service._context_for_thread(thread_id=thread_id, user_id=user_id)
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


async def stream_branch_action_result(
    *,
    service: Any,
    thread_id: str,
    user_id: str,
    message: str,
    request_id: str | None,
) -> AsyncIterator[str]:
    try:
        result = service._handle_branch_action_turn(
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            request_id=request_id,
        )
        if result is None:
            raise RuntimeError("No branch action intent was available.")
        yield sse_frame(
            event="turn.status",
            data={"phase": "accepted", "thread_id": thread_id, "kind": "chat.turn"},
        )
        event_name = f"branch.action.{result['kind']}"
        payload = {
            "thread_id": thread_id,
            "branch_action": result.get("branch_action"),
        }
        if result.get("branch_record") is not None:
            payload["branch_record"] = result["branch_record"]
        if result.get("navigation") is not None:
            payload["navigation"] = result["navigation"]
        yield sse_frame(event=event_name, data=payload)
        if result.get("message"):
            yield sse_frame(
                event="visible_text.completed",
                data={"content": result["message"], "thread_id": thread_id},
            )
            yield sse_frame(
                event="message.completed",
                data={"content": result["message"], "thread_id": thread_id},
            )
        yield sse_frame(event="turn.completed", data={"thread_state": result["thread_state"]})
    except Exception as exc:  # noqa: BLE001
        failed_action = next(
            (
                action
                for action in reversed(normalize_branch_actions(service._safe_get_values(thread_id).get("branch_actions")))
                if action.status.value == "failed"
            ),
            None,
        )
        if failed_action is not None:
            yield sse_frame(
                event="branch.action.failed",
                data={"thread_id": thread_id, "branch_action": failed_action.model_dump(mode="json")},
            )
        yield sse_frame(
            event="turn.failed",
            data={"error": exc.__class__.__name__, "message": str(exc), "thread_id": thread_id},
        )
    finally:
        yield sse_frame(event="turn.closed", data={"status": "ok", "thread_id": thread_id})
