from __future__ import annotations

from typing import Any

from .branch_actions import dismissal_message, normalize_branch_actions, serialize_branch_actions
from .chat_branch_actions import (
    branch_action_intent,
    build_branch_action_proposal_result,
    dismiss_branch_action_locked,
    execute_branch_action_locked,
    handle_branch_action_turn,
)


class ChatBranchActionFacadeMixin:
    @staticmethod
    def _is_chinese_text(text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in str(text or ""))

    def _branch_action_intent(self, *, values: dict[str, Any], branch_meta: Any | None, message: str) -> str | None:
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
        update: dict[str, Any] = {"branch_actions": serialize_branch_actions(normalize_branch_actions(actions))}
        if audit_event is not None:
            values = self._safe_get_values(thread_id)
            audit = [item for item in list(values.get("branch_action_audit") or []) if isinstance(item, dict)]
            update["branch_action_audit"] = [*audit, audit_event]
        if messages:
            update["messages"] = messages
        update_state = getattr(self.runtime.graph, "update_state", None)
        if not callable(update_state):
            raise RuntimeError("Conversation graph does not support branch action state updates.")
        update_state(
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
