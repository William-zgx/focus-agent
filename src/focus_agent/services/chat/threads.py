from __future__ import annotations

import json
import logging
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from langchain.messages import SystemMessage
from pydantic import BaseModel, ValidationError

from ...core.branch_messages import branch_fork_message_count, branch_visible_messages
from ...core.branching import BranchMeta, BranchStatus, ThreadResolution
from ...core.repo_call import (
    REPO_METHOD_ERROR,
    REPO_METHOD_MISSING,
    has_repo_method,
    safe_repo_call,
)
from ...core.request_context import RequestContext
from ...core.state import normalize_agent_state
from ...core.token_usage import message_token_usage
from ...core.types import ConversationRecord
from ...model_registry import default_thinking_enabled, supports_thinking_mode
from ...observability.tracing import build_invoke_config
from ...observability.trajectory import build_turn_trajectory_record
from ...transport.stream_events import (
    extract_visible_text_delta,
    sanitize_stream_visible_text,
)
from .branch_actions import (
    normalize_branch_actions,
    serialize_branch_actions,
)

logger = logging.getLogger("focus_agent.chat")


class ThreadStateUnavailableError(RuntimeError):
    """Raised when an interactive thread state read cannot be completed."""


def _message_type_name(message: Any) -> str:
    if isinstance(message, dict):
        raw_type = message.get("type") or message.get("role") or message.get("_type") or ""
        message_type = str(raw_type or "").strip().lower()
        return {
            "assistant": "ai",
            "user": "human",
        }.get(message_type, message_type)
    return (
        str(
            getattr(message, "type", message.__class__.__name__.replace("Message", "").lower())
            or ""
        )
        .strip()
        .lower()
    )


def is_ai_message_type(message_type: Any) -> bool:
    return str(message_type or "").strip().lower() in {"ai", "assistant"}


def is_human_message_type(message_type: Any) -> bool:
    return str(message_type or "").strip().lower() in {"human", "user"}


def is_tool_message_type(message_type: Any) -> bool:
    return str(message_type or "").strip().lower() == "tool"


def _list_content_to_visible_text(content: list[Any]) -> str:
    return extract_visible_text_delta(SimpleNamespace(content=content, type="ai"))


def message_content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, dict):
        for key in ("text", "content"):
            if key in content:
                return message_content_to_text(content.get(key))
        return json.dumps(json_safe(content), ensure_ascii=False)
    if isinstance(content, list):
        return _list_content_to_visible_text(content)
    return str(content)


def confirmed_visible_ai_text(content: Any) -> str:
    return sanitize_stream_visible_text(message_content_to_text(content))


def json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if hasattr(value, "content") or hasattr(value, "tool_calls"):
        message_type = _message_type_name(value)
        tool_calls = json_safe(getattr(value, "tool_calls", None))
        content = message_content_to_text(getattr(value, "content", ""))
        if is_ai_message_type(message_type):
            content = "" if tool_calls else confirmed_visible_ai_text(getattr(value, "content", ""))
        return {
            "type": message_type,
            "content": content,
            "tool_calls": tool_calls,
            "name": getattr(value, "name", None),
            "id": getattr(value, "id", None),
            "usage_metadata": json_safe(message_token_usage(value)),
        }
    return str(value)


def sse_frame(*, event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(json_safe(data), ensure_ascii=False)
    lines = [f"event: {event}"]
    for line in payload.splitlines() or [""]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def serialize_message(message: Any) -> dict[str, Any]:
    message_type = _message_type_name(message)
    if isinstance(message, dict):
        raw_content = message.get("content", "")
        tool_calls = message.get("tool_calls")
        content = message_content_to_text(raw_content)
        if is_ai_message_type(message_type):
            content = "" if tool_calls else confirmed_visible_ai_text(raw_content)
        payload = {
            "type": message_type,
            "content": content,
            "tool_calls": json_safe(tool_calls),
            "name": message.get("name"),
            "id": message.get("id"),
            "usage_metadata": json_safe(message.get("usage_metadata")),
        }
        if is_tool_message_type(message_type):
            payload["tool_call_id"] = message.get("tool_call_id")
            payload["status"] = message.get("status")
        return payload

    tool_calls = getattr(message, "tool_calls", None)
    content = message_content_to_text(getattr(message, "content", ""))
    if is_ai_message_type(message_type):
        content = "" if tool_calls else confirmed_visible_ai_text(getattr(message, "content", ""))
    payload = {
        "type": message_type,
        "content": content,
        "tool_calls": tool_calls,
        "name": getattr(message, "name", None),
        "id": getattr(message, "id", None),
        "usage_metadata": json_safe(message_token_usage(message)),
    }
    if is_tool_message_type(message_type):
        payload["tool_call_id"] = getattr(message, "tool_call_id", None)
        payload["status"] = getattr(message, "status", None)
    return payload


def _thread_state_visible_message(message: Any) -> dict[str, Any] | None:
    payload = serialize_message(message)
    message_type = str(payload.get("type") or "").strip().lower()
    if not is_ai_message_type(message_type):
        return payload

    if payload.get("content"):
        return payload

    return payload if payload.get("tool_calls") else None


def _is_followed_by_tool_activity_before_next_user(
    messages: list[Any],
    *,
    index: int,
) -> bool:
    for later in messages[index + 1 :]:
        message_type = _message_type_name(later)
        if is_human_message_type(message_type):
            return False
        if is_tool_message_type(message_type):
            return True
        if is_ai_message_type(message_type) and getattr(later, "tool_calls", None):
            return True
        if isinstance(later, dict) and is_ai_message_type(message_type) and later.get("tool_calls"):
            return True
    return False


def thread_state_messages(messages: list[Any], *, limit: int) -> list[dict[str, Any]]:
    if not messages:
        return []
    payloads: list[dict[str, Any]] = []
    visible_window = messages[-limit:]
    for index, message in enumerate(visible_window):
        payload = _thread_state_visible_message(message)
        if payload is not None:
            message_type = str(payload.get("type") or "").strip().lower()
            if (
                is_ai_message_type(message_type)
                and payload.get("content")
                and not payload.get("tool_calls")
                and _is_followed_by_tool_activity_before_next_user(visible_window, index=index)
            ):
                continue
            payloads.append(payload)
    return payloads


def _thread_state_branch_actions(
    values: dict[str, Any],
    *,
    thread_id: str,
) -> list[dict[str, Any]]:
    actions = normalize_branch_actions(values.get("branch_actions"))
    if branch_fork_message_count(values) is not None:
        actions = [action for action in actions if action.source_thread_id == thread_id]
    return serialize_branch_actions(actions)


def latest_final_ai_text(
    messages: list[Any], *, message_content_to_text: Callable[[Any], str]
) -> str | None:
    del message_content_to_text
    for message in reversed(messages):
        message_type = getattr(
            message, "type", message.__class__.__name__.replace("Message", "").lower()
        )
        if is_human_message_type(message_type):
            return None
        if is_tool_message_type(message_type):
            return None
        if is_ai_message_type(message_type) and not getattr(message, "tool_calls", None):
            text = confirmed_visible_ai_text(getattr(message, "content", ""))
            if text:
                return text
            continue
        if is_ai_message_type(message_type) and getattr(message, "tool_calls", None):
            return None
    return None


def effective_thinking_mode(*, model_id: str, thinking_mode: Any, settings: Any) -> str:
    if not supports_thinking_mode(model_id, settings=settings):
        return ""
    normalized = str(thinking_mode or "").strip().lower()
    if normalized in {"enabled", "disabled"}:
        return normalized
    return "enabled" if default_thinking_enabled(model_id, settings=settings) else "disabled"


def response_payload(
    *,
    thread_id: str,
    user_id: str,
    context: RequestContext,
    branch_meta: BranchMeta | None,
    interrupts: list[Any],
    values: dict[str, Any],
    settings: Any,
    context_usage: dict[str, Any],
    message_content_to_text: Callable[[Any], str],
    message_limit: int,
    trace_correlation: Any = None,
) -> dict[str, Any]:
    messages = values.get("messages", [])
    thread_messages = branch_visible_messages(list(messages), values=values)
    branch_actions = _thread_state_branch_actions(values, thread_id=thread_id)
    selected_model = str(values.get("selected_model") or settings.model)
    selected_thinking_mode = effective_thinking_mode(
        model_id=selected_model,
        thinking_mode=values.get("selected_thinking_mode"),
        settings=settings,
    )
    assistant_message = latest_final_ai_text(
        thread_messages, message_content_to_text=message_content_to_text
    )
    return {
        "thread_id": thread_id,
        "root_thread_id": context.root_thread_id,
        "assistant_message": assistant_message,
        "rolling_summary": values.get("rolling_summary", ""),
        "selected_model": selected_model,
        "selected_thinking_mode": selected_thinking_mode,
        "branch_meta": branch_meta.model_dump(mode="json") if branch_meta else None,
        "merge_proposal": values.get("merge_proposal"),
        "merge_decision": values.get("merge_decision"),
        "merge_queue": values.get("merge_queue", []),
        "active_skill_ids": values.get("active_skill_ids", []),
        "messages": thread_state_messages(thread_messages, limit=message_limit),
        "interrupts": [getattr(item, "value", item) for item in interrupts],
        "branch_actions": branch_actions,
        "trace": build_invoke_config(
            settings=settings,
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=context.root_thread_id,
            branch_meta=branch_meta,
            trace_correlation=trace_correlation,
        ),
        "context_usage": context_usage,
    }


class ChatThreadAccessMixin:
    def _safe_snapshot(self, thread_id: str, *, strict: bool = False):
        try:
            return self.runtime.graph.get_state({"configurable": {"thread_id": thread_id}})
        except Exception as exc:
            if strict:
                raise ThreadStateUnavailableError(
                    "Thread state is temporarily unavailable. Please retry after the server "
                    "finishes reloading."
                ) from exc
            logger.debug(
                "failed to read thread graph snapshot",
                extra={"thread_id": thread_id},
                exc_info=True,
            )
            return None

    def _safe_get_values(self, thread_id: str, *, strict: bool = False) -> dict[str, Any]:
        snapshot = self._safe_snapshot(thread_id, strict=strict)
        values = normalize_agent_state(
            dict(getattr(snapshot, "values", {}) or {}) if snapshot else normalize_agent_state()
        )
        return self._backfill_import_records(thread_id=thread_id, values=values)

    def _safe_get_interrupts(self, thread_id: str, *, strict: bool = False) -> list[Any]:
        snapshot = self._safe_snapshot(thread_id, strict=strict)
        return list(getattr(snapshot, "interrupts", []) or []) if snapshot else []

    @staticmethod
    def _imported_conclusion_message(imported: dict[str, Any]) -> str:
        summary = str(imported.get("summary") or "").strip()
        if not summary:
            return ""
        branch_name = str(
            imported.get("branch_name") or imported.get("branch_id") or "unknown branch"
        ).strip()
        lines = [f"Imported conclusion from branch '{branch_name}':", summary]
        key_findings = [
            str(item).strip() for item in imported.get("key_findings", []) if str(item).strip()
        ]
        if key_findings:
            lines.append("")
            lines.append("Key findings:")
            lines.extend(f"- {item}" for item in key_findings)
        evidence_refs = [
            str(item).strip() for item in imported.get("evidence_refs", []) if str(item).strip()
        ]
        if evidence_refs:
            lines.append("")
            lines.append(f"Evidence refs: {', '.join(evidence_refs)}")
        return "\n".join(lines).strip()

    @staticmethod
    def _append_imported_summary(existing_summary: Any, imported: dict[str, Any]) -> str:
        previous = str(existing_summary or "").strip()
        summary = str(imported.get("summary") or "").strip()
        if not summary:
            return previous
        branch_name = str(
            imported.get("branch_name") or imported.get("branch_id") or "unknown branch"
        ).strip()
        imported_line = f"Imported from {branch_name}: {summary}"
        if imported_line in previous:
            return previous
        combined = "\n".join(part for part in [previous, imported_line] if part)
        if len(combined) > 4000:
            combined = combined[-4000:]
        return combined

    def _backfill_import_records(self, *, thread_id: str, values: dict[str, Any]) -> dict[str, Any]:
        merge_queue = [item for item in values.get("merge_queue", []) if isinstance(item, dict)]
        if not merge_queue:
            return values

        messages = list(values.get("messages", []))
        existing_contents = {
            self._message_content_to_text(
                message.get("content", "")
                if isinstance(message, dict)
                else getattr(message, "content", "")
            ).strip()
            for message in messages
        }
        appended_messages: list[SystemMessage] = []
        updated_summary = values.get("rolling_summary", "")

        for imported in merge_queue:
            notice = self._imported_conclusion_message(imported)
            if notice and notice not in existing_contents:
                appended_messages.append(SystemMessage(content=notice))
                existing_contents.add(notice)
            updated_summary = self._append_imported_summary(updated_summary, imported)

        payload: dict[str, Any] = {}
        if appended_messages:
            payload["messages"] = appended_messages
            values = {**values, "messages": messages + appended_messages}
        if updated_summary != values.get("rolling_summary", ""):
            payload["rolling_summary"] = updated_summary
            values = {**values, "rolling_summary": updated_summary}

        if payload and hasattr(self.runtime.graph, "update_state"):
            try:
                self.runtime.graph.update_state(
                    {"configurable": {"thread_id": thread_id}},
                    payload,
                    as_node="bootstrap_turn",
                )
            except Exception:
                pass

        return values

    def _branch_meta_from_repo(self, thread_id: str) -> BranchMeta | None:
        record = safe_repo_call(
            self.runtime.repo,
            "get_by_child_thread_id",
            thread_id,
            default_missing=None,
            default_error=None,
        )
        if record is None:
            return None
        return BranchMeta(
            branch_id=record.branch_id,
            root_thread_id=record.root_thread_id,
            parent_thread_id=record.parent_thread_id,
            return_thread_id=record.return_thread_id,
            branch_name=record.branch_name,
            branch_role=record.branch_role,
            branch_depth=record.branch_depth,
            branch_status=record.branch_status,
            is_archived=record.is_archived,
            archived_at=record.archived_at,
            fork_checkpoint_id=record.fork_checkpoint_id,
            fork_strategy=record.fork_strategy,
        )

    def _branch_meta(self, *, thread_id: str, values: dict[str, Any]) -> BranchMeta | None:
        meta = values.get("branch_meta")
        repo_meta = self._branch_meta_from_repo(thread_id)
        if not meta:
            return repo_meta
        try:
            branch_meta = BranchMeta.model_validate(meta)
        except ValidationError:
            return repo_meta
        return repo_meta or branch_meta

    def _thread_resolution(self, *, thread_id: str, user_id: str) -> ThreadResolution:
        resolver = getattr(self.runtime.repo, "resolve_thread_ref", None)
        if callable(resolver):
            resolved = resolver(thread_id=thread_id, owner_user_id=user_id)
            if isinstance(resolved, ThreadResolution):
                return resolved
        return ThreadResolution(
            input_thread_id=thread_id,
            root_thread_id=thread_id,
            source_thread_id=thread_id,
            diagnostic="resolver_unavailable_assumed_root",
        )

    def _context_for_thread(
        self,
        *,
        thread_id: str,
        user_id: str,
        explicit_skill_hints: tuple[str, ...] | None = None,
    ) -> tuple[RequestContext, BranchMeta | None, dict[str, Any]]:
        values = self._safe_get_values(thread_id)
        resolution = self._thread_resolution(thread_id=thread_id, user_id=user_id)
        branch_meta = self._branch_meta(thread_id=thread_id, values=values)
        if (
            resolution.is_root
            and resolution.branch_id is None
            and resolution.diagnostic != "resolver_unavailable_assumed_root"
        ):
            branch_meta = None
        root_thread_id = branch_meta.root_thread_id if branch_meta else resolution.root_thread_id
        stored_skill_hints = tuple(str(item) for item in values.get("active_skill_ids", []) or ())
        context = RequestContext(
            user_id=user_id,
            root_thread_id=root_thread_id,
            branch_id=branch_meta.branch_id if branch_meta else None,
            parent_thread_id=branch_meta.parent_thread_id if branch_meta else None,
            branch_role=branch_meta.branch_role.value if branch_meta else None,
            skill_hints=explicit_skill_hints
            if explicit_skill_hints is not None
            else stored_skill_hints,
        )
        return context, branch_meta, values

    def _preflight_thread_access(
        self,
        *,
        thread_id: str,
        user_id: str,
        explicit_skill_hints: tuple[str, ...] | None = None,
        require_writable: bool = False,
    ) -> tuple[RequestContext, BranchMeta | None, dict[str, Any]]:
        context, branch_meta, values = self._context_for_thread(
            thread_id=thread_id,
            user_id=user_id,
            explicit_skill_hints=explicit_skill_hints,
        )
        self._ensure_access(thread_id=thread_id, user_id=user_id, context=context)
        if require_writable:
            self._ensure_thread_writable(branch_meta)
        return context, branch_meta, values

    def _ensure_access(self, *, thread_id: str, user_id: str, context: RequestContext) -> None:
        owner = self.runtime.repo.get_thread_owner(thread_id=thread_id)
        if owner is None:
            self.runtime.repo.ensure_thread_owner(
                thread_id=thread_id,
                root_thread_id=context.root_thread_id,
                owner_user_id=user_id,
            )
        else:
            self.runtime.repo.assert_thread_owner(thread_id=thread_id, owner_user_id=user_id)
        if context.branch_id is None and thread_id == context.root_thread_id:
            self._ensure_root_conversation_record(
                root_thread_id=context.root_thread_id, user_id=user_id
            )

    def _ensure_root_conversation_record(self, *, root_thread_id: str, user_id: str) -> None:
        repo = self.runtime.repo
        if not has_repo_method(repo, "get_conversation") or not has_repo_method(
            repo, "create_conversation"
        ):
            return
        create_conversation = repo.create_conversation

        conversation = safe_repo_call(
            repo,
            "get_conversation",
            root_thread_id,
            except_errors=(KeyError,),
            default_missing=REPO_METHOD_MISSING,
            default_error=REPO_METHOD_ERROR,
        )
        if conversation is not REPO_METHOD_MISSING and conversation is not REPO_METHOD_ERROR:
            return
        try:
            create_conversation(
                ConversationRecord(
                    root_thread_id=root_thread_id,
                    owner_user_id=user_id,
                    title="New Conversation",
                    title_pending_ai=True,
                )
            )
        except Exception:
            # If concurrent workers race here, another session may have already persisted it.
            # Retry the read path and only fail loudly when the conversation is still missing.
            retry = safe_repo_call(
                repo,
                "get_conversation",
                root_thread_id,
                except_errors=(Exception,),
            )
            if retry is REPO_METHOD_ERROR:
                raise

    @staticmethod
    def _ensure_thread_writable(branch_meta: BranchMeta | None) -> None:
        if branch_meta and branch_meta.branch_status == BranchStatus.MERGED:
            raise PermissionError("Merged branches are read-only.")


def record_turn_trajectory_best_effort(
    *,
    recorder: Any,
    settings: Any,
    thread_id: str,
    user_id: str,
    root_thread_id: str,
    kind: str,
    status: str,
    final_values: dict[str, Any],
    initial_message_count: int,
    initial_llm_calls: int,
    started_at: Any,
    finished_at: Any,
    branch_meta: BranchMeta | None,
    trace_correlation: Any = None,
    input_messages: list[Any] | None = None,
    answer: str | None = None,
    error: str | None = None,
) -> None:
    import logging

    logger = logging.getLogger("focus_agent.chat")
    if recorder is None:
        return
    if not has_repo_method(recorder, "record_turn"):
        return
    try:
        record = build_turn_trajectory_record(
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=root_thread_id,
            kind=kind,
            status=status,
            final_values=final_values,
            initial_message_count=initial_message_count,
            initial_llm_calls=initial_llm_calls,
            started_at=started_at,
            finished_at=finished_at,
            branch_meta=branch_meta,
            trace_correlation=trace_correlation,
            input_messages=input_messages,
            answer=answer,
            error=error,
            observation_max_chars=settings.trajectory_observation_max_chars,
            answer_max_chars=settings.trajectory_answer_max_chars,
            hash_user_id=settings.trajectory_hash_user_id,
        )
        recorder.record_turn(record)
    except Exception:  # noqa: BLE001
        logger.warning("failed to persist turn trajectory", exc_info=True)
