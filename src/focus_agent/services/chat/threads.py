from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langchain.messages import SystemMessage
from pydantic import ValidationError

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
from ...core.tool_call_protocol import repair_dangling_tool_call_messages
from ...core.types import ConversationRecord
from ...model_registry import default_thinking_enabled, supports_thinking_mode
from ...observability.tracing import build_invoke_config
from .branch_actions import (
    normalize_branch_actions,
    serialize_branch_actions,
)
from .serialization import (
    _turn_metadata_from_plan_meta,
    latest_final_ai_text,
    thread_state_messages,
)
from .trajectory_recording import (
    record_turn_trajectory_best_effort as record_turn_trajectory_best_effort,
)

logger = logging.getLogger("focus_agent.chat")


class ThreadStateUnavailableError(RuntimeError):
    """Raised when an interactive thread state read cannot be completed."""


def _thread_state_branch_actions(
    values: dict[str, Any],
    *,
    thread_id: str,
) -> list[dict[str, Any]]:
    actions = normalize_branch_actions(values.get("branch_actions"))
    if branch_fork_message_count(values) is not None:
        actions = [action for action in actions if action.source_thread_id == thread_id]
    return serialize_branch_actions(actions)


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
    thread_messages = repair_dangling_tool_call_messages(
        thread_messages,
        repair_trailing=not bool(interrupts),
    )
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
        "tool_outcomes": values.get("tool_outcomes", []),
        "task_outcome": values.get("task_outcome"),
        "messages": thread_state_messages(
            thread_messages,
            limit=message_limit,
            turn_metadata=_turn_metadata_from_plan_meta(values.get("plan_meta")),
        ),
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

    def _safe_get_values(
        self,
        thread_id: str,
        *,
        strict: bool = False,
        backfill: bool = False,
    ) -> dict[str, Any]:
        snapshot = self._safe_snapshot(thread_id, strict=strict)
        values = normalize_agent_state(
            dict(getattr(snapshot, "values", {}) or {}) if snapshot else normalize_agent_state()
        )
        if not backfill:
            return values
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

        original_values = values
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

        if not payload:
            return values

        update_state = getattr(self.runtime.graph, "update_state", None)
        if not callable(update_state):
            logger.warning(
                "cannot persist imported thread records; returning persisted state",
                extra={"thread_id": thread_id},
            )
            return original_values

        try:
            update_state(
                {"configurable": {"thread_id": thread_id}},
                payload,
                as_node="bootstrap_turn",
            )
        except Exception:
            logger.warning(
                "failed to persist imported thread records; re-reading persisted state",
                extra={"thread_id": thread_id},
                exc_info=True,
            )
            return self._safe_get_values(thread_id, strict=True)

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
        if repo_meta is None:
            return branch_meta
        # The repository is canonical for identity/status; the fork brief only
        # lives in graph state, so carry it over.
        if branch_meta.fork_brief and not repo_meta.fork_brief:
            return repo_meta.model_copy(update={"fork_brief": branch_meta.fork_brief})
        return repo_meta

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
        backfill: bool = True,
    ) -> tuple[RequestContext, BranchMeta | None, dict[str, Any]]:
        values = self._safe_get_values(thread_id, backfill=False)
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
        self._ensure_access(thread_id=thread_id, user_id=user_id, context=context)
        if backfill:
            values = self._backfill_import_records(thread_id=thread_id, values=values)
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
            backfill=False,
        )
        if require_writable:
            self._ensure_thread_writable(branch_meta)
        values = self._backfill_import_records(thread_id=thread_id, values=values)
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
