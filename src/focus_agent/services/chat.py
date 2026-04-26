from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
import json
import logging
import threading
from typing import Any, AsyncIterator

from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from pydantic import BaseModel
from pydantic import ValidationError

from ..context_usage import build_context_usage
from ..core.branching import BranchActionKind, BranchActionNavigation, BranchMeta, BranchStatus
from ..core.request_context import RequestContext
from ..core.state import normalize_agent_state
from ..engine.runtime import AppRuntime
from ..model_registry import default_thinking_enabled, supports_thinking_mode
from ..observability.tracing import (
    TraceCorrelation,
    build_invoke_config,
    build_trace_correlation,
    start_trace_span,
)
from ..observability.trajectory import build_turn_trajectory_record, utc_now
from ..skills.models import SkillSelection
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
    serialize_branch_actions,
    target_parent_thread_id,
)
from ..transport.stream_events import (
    extract_reasoning_delta,
    extract_visible_text_delta,
    extract_tool_call_chunks,
    extract_tool_requests_from_updates,
    extract_tool_results_from_updates,
    map_custom_payload_to_event,
    sanitize_stream_metadata,
)

logger = logging.getLogger("focus_agent.chat")


_STREAM_END = object()
_INTERNAL_MESSAGE_STREAM_NODES = frozenset({"plan", "reflect"})
_TOOL_RESULT_FALLBACK_VISIBLE_PREFIX = "我先根据已拿到的工具结果给出一个保守整理："


class ChatService:
    _THREAD_STATE_MESSAGE_LIMIT = 200
    _CONTEXT_COMPACTION_SUMMARY_CHARS = 2600
    _CONTEXT_COMPACTION_RECENT_MESSAGES = 8

    def __init__(self, runtime: AppRuntime):
        self.runtime = runtime
        self._active_turns: set[str] = set()
        self._active_turns_lock = threading.Lock()

    def _acquire_thread_turn(self, *, thread_id: str) -> None:
        with self._active_turns_lock:
            if thread_id in self._active_turns:
                raise ConcurrentTurnError(
                    "This thread is still processing the previous turn. "
                    "Please wait for it to finish before sending another message."
                )
            self._active_turns.add(thread_id)

    def _release_thread_turn(self, *, thread_id: str) -> None:
        with self._active_turns_lock:
            self._active_turns.discard(thread_id)

    @staticmethod
    def _message_content_to_text(content: Any) -> str:
        if isinstance(content, list):
            return json.dumps(content, ensure_ascii=False)
        return str(content)

    def _latest_final_ai_text(self, messages: list[Any]) -> str | None:
        for message in reversed(messages):
            if isinstance(message, AIMessage) and not getattr(message, 'tool_calls', None):
                return self._message_content_to_text(message.content)
        return None

    def _serialize_message(self, message: Any) -> dict[str, Any]:
        return {
            'type': getattr(message, 'type', message.__class__.__name__.replace('Message', '').lower()),
            'content': self._message_content_to_text(getattr(message, 'content', '')),
            'tool_calls': getattr(message, 'tool_calls', None),
            'name': getattr(message, 'name', None),
            'id': getattr(message, 'id', None),
            'usage_metadata': self._json_safe(getattr(message, 'usage_metadata', None)),
        }

    def _thread_state_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        if not messages:
            return []
        window = messages[-self._THREAD_STATE_MESSAGE_LIMIT :]
        return [self._serialize_message(message) for message in window]

    def _safe_snapshot(self, thread_id: str):
        try:
            return self.runtime.graph.get_state({'configurable': {'thread_id': thread_id}})
        except Exception:
            return None

    def _safe_get_values(self, thread_id: str) -> dict[str, Any]:
        snapshot = self._safe_snapshot(thread_id)
        values = normalize_agent_state(dict(getattr(snapshot, 'values', {}) or {})) if snapshot else normalize_agent_state()
        return self._backfill_import_records(thread_id=thread_id, values=values)

    def _safe_get_interrupts(self, thread_id: str) -> list[Any]:
        snapshot = self._safe_snapshot(thread_id)
        return list(getattr(snapshot, 'interrupts', []) or []) if snapshot else []

    @staticmethod
    def _imported_conclusion_message(imported: dict[str, Any]) -> str:
        summary = str(imported.get('summary') or '').strip()
        if not summary:
            return ''
        branch_name = str(imported.get('branch_name') or imported.get('branch_id') or 'unknown branch').strip()
        lines = [f"Imported conclusion from branch '{branch_name}':", summary]
        key_findings = [str(item).strip() for item in imported.get('key_findings', []) if str(item).strip()]
        if key_findings:
            lines.append('')
            lines.append('Key findings:')
            lines.extend(f"- {item}" for item in key_findings)
        evidence_refs = [str(item).strip() for item in imported.get('evidence_refs', []) if str(item).strip()]
        if evidence_refs:
            lines.append('')
            lines.append(f"Evidence refs: {', '.join(evidence_refs)}")
        return '\n'.join(lines).strip()

    @staticmethod
    def _append_imported_summary(existing_summary: Any, imported: dict[str, Any]) -> str:
        previous = str(existing_summary or '').strip()
        summary = str(imported.get('summary') or '').strip()
        if not summary:
            return previous
        branch_name = str(imported.get('branch_name') or imported.get('branch_id') or 'unknown branch').strip()
        imported_line = f"Imported from {branch_name}: {summary}"
        if imported_line in previous:
            return previous
        combined = '\n'.join(part for part in [previous, imported_line] if part)
        if len(combined) > 4000:
            combined = combined[-4000:]
        return combined

    def _backfill_import_records(self, *, thread_id: str, values: dict[str, Any]) -> dict[str, Any]:
        merge_queue = [item for item in values.get('merge_queue', []) if isinstance(item, dict)]
        if not merge_queue:
            return values

        messages = list(values.get('messages', []))
        existing_contents = {
            self._message_content_to_text(getattr(message, 'content', '')).strip()
            for message in messages
        }
        appended_messages: list[SystemMessage] = []
        updated_summary = values.get('rolling_summary', '')

        for imported in merge_queue:
            notice = self._imported_conclusion_message(imported)
            if notice and notice not in existing_contents:
                appended_messages.append(SystemMessage(content=notice))
                existing_contents.add(notice)
            updated_summary = self._append_imported_summary(updated_summary, imported)

        payload: dict[str, Any] = {}
        if appended_messages:
            payload['messages'] = appended_messages
            values = {**values, 'messages': messages + appended_messages}
        if updated_summary != values.get('rolling_summary', ''):
            payload['rolling_summary'] = updated_summary
            values = {**values, 'rolling_summary': updated_summary}

        if payload and hasattr(self.runtime.graph, 'update_state'):
            try:
                self.runtime.graph.update_state(
                    {'configurable': {'thread_id': thread_id}},
                    payload,
                    as_node='bootstrap_turn',
                )
            except Exception:
                pass

        return values

    def _branch_meta_from_repo(self, thread_id: str) -> BranchMeta | None:
        try:
            record = self.runtime.repo.get_by_child_thread_id(thread_id)
        except Exception:
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
        meta = values.get('branch_meta')
        repo_meta = self._branch_meta_from_repo(thread_id)
        if not meta:
            return repo_meta
        try:
            branch_meta = BranchMeta.model_validate(meta)
        except ValidationError:
            return repo_meta
        return repo_meta or branch_meta

    def _context_for_thread(
        self,
        *,
        thread_id: str,
        user_id: str,
        explicit_skill_hints: tuple[str, ...] | None = None,
    ) -> tuple[RequestContext, BranchMeta | None, dict[str, Any]]:
        values = self._safe_get_values(thread_id)
        branch_meta = self._branch_meta(thread_id=thread_id, values=values)
        root_thread_id = branch_meta.root_thread_id if branch_meta else thread_id
        stored_skill_hints = tuple(str(item) for item in values.get('active_skill_ids', []) or ())
        context = RequestContext(
            user_id=user_id,
            root_thread_id=root_thread_id,
            branch_id=branch_meta.branch_id if branch_meta else None,
            parent_thread_id=branch_meta.parent_thread_id if branch_meta else None,
            branch_role=branch_meta.branch_role.value if branch_meta else None,
            skill_hints=explicit_skill_hints if explicit_skill_hints is not None else stored_skill_hints,
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

    @staticmethod
    def _ensure_thread_writable(branch_meta: BranchMeta | None) -> None:
        if branch_meta and branch_meta.branch_status == BranchStatus.MERGED:
            raise PermissionError('Merged branches are read-only.')

    def _context_usage_payload(self, values: dict[str, Any], *, draft_message: str | None = None) -> dict[str, Any]:
        try:
            selected_model = str(values.get("selected_model") or self.runtime.settings.model)
            return build_context_usage(
                values,
                draft_message=draft_message,
                selected_model=selected_model,
            ).to_dict()
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to calculate context usage", exc_info=True)
            return {
                "used_tokens": 0,
                "token_limit": 0,
                "remaining_tokens": 0,
                "used_ratio": 0.0,
                "status": "error",
                "prompt_chars": 0,
                "prompt_budget_chars": 0,
                "tokenizer_mode": "chars_fallback",
                "last_compacted_at": None,
                "error": str(exc),
            }

    def preview_thread_context(self, *, thread_id: str, user_id: str, draft_message: str | None = None) -> dict[str, Any]:
        context, _branch_meta, values = self._context_for_thread(thread_id=thread_id, user_id=user_id)
        self._ensure_access(thread_id=thread_id, user_id=user_id, context=context)
        return {"context_usage": self._context_usage_payload(values, draft_message=draft_message)}

    def compact_thread_context(
        self,
        *,
        thread_id: str,
        user_id: str,
        trigger: str = "manual",
        draft_message: str | None = None,
        force: bool = True,
    ) -> dict[str, Any]:
        context, branch_meta, values = self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            require_writable=True,
        )
        self._acquire_thread_turn(thread_id=thread_id)
        try:
            self._compact_thread_context_locked(
                thread_id=thread_id,
                values=values,
                trigger=trigger,
                draft_message=draft_message,
                force=force,
            )
            latest_context, latest_branch_meta, _ = self._context_for_thread(thread_id=thread_id, user_id=user_id)
            return self._response_payload(
                thread_id=thread_id,
                user_id=user_id,
                context=latest_context,
                branch_meta=latest_branch_meta or branch_meta,
                interrupts=self._safe_get_interrupts(thread_id),
                trace_correlation=None,
            )
        finally:
            del context
            self._release_thread_turn(thread_id=thread_id)

    def _compact_thread_context_locked(
        self,
        *,
        thread_id: str,
        values: dict[str, Any],
        trigger: str,
        draft_message: str | None = None,
        force: bool = False,
    ) -> dict[str, Any] | None:
        usage = self._context_usage_payload(values, draft_message=draft_message)
        threshold = self._context_compaction_threshold(trigger)
        if not force and float(usage.get("used_ratio") or 0) < threshold:
            return None

        messages = list(values.get("messages", []) or [])
        previous_meta = values.get("context_compaction") if isinstance(values.get("context_compaction"), dict) else {}
        if not force and int(previous_meta.get("source_message_count") or -1) == len(messages):
            return None

        now = datetime.now(timezone.utc).isoformat()
        summary = self._build_compacted_summary(values)
        compact_meta = {
            **previous_meta,
            "last_compacted_at": now,
            "trigger": trigger,
            "source_message_count": len(messages),
            "source_prompt_tokens": int(usage.get("used_tokens") or 0),
            "source_prompt_chars": int(usage.get("prompt_chars") or 0),
            "non_destructive": True,
        }
        update = {
            "rolling_summary": summary,
            "context_compaction": compact_meta,
        }
        self.runtime.graph.update_state(
            {"configurable": {"thread_id": thread_id}},
            update,
            as_node="context_compaction",
        )
        return update

    def _context_compaction_threshold(self, trigger: str) -> float:
        if trigger == "auto_post_turn":
            return float(getattr(self.runtime.settings, "context_auto_compaction_post_turn_ratio", 0.85))
        return float(getattr(self.runtime.settings, "context_auto_compaction_pre_send_ratio", 0.92))

    def _auto_compact_context_before_turn(
        self,
        *,
        thread_id: str,
        values: dict[str, Any],
        draft_message: str | None,
    ) -> dict[str, Any] | None:
        if not bool(getattr(self.runtime.settings, "context_auto_compaction_enabled", True)):
            return None
        try:
            return self._compact_thread_context_locked(
                thread_id=thread_id,
                values=values,
                trigger="auto_pre_send",
                draft_message=draft_message,
                force=False,
            )
        except Exception:  # noqa: BLE001
            logger.warning("failed to auto-compact context before turn", exc_info=True)
            return None

    def _schedule_post_turn_context_compaction(self, *, thread_id: str, user_id: str, kind: str) -> None:
        if kind != "chat.turn":
            return
        if not bool(getattr(self.runtime.settings, "context_auto_compaction_enabled", True)):
            return

        def schedule_compact_later(*, delay: float, attempt: int) -> None:
            timer = threading.Timer(delay, compact_later, kwargs={"attempt": attempt})
            timer.daemon = True
            timer.start()

        def compact_later(*, attempt: int) -> None:
            try:
                self.compact_thread_context(
                    thread_id=thread_id,
                    user_id=user_id,
                    trigger="auto_post_turn",
                    force=False,
                )
            except ConcurrentTurnError:
                if attempt < 2:
                    schedule_compact_later(delay=0.2, attempt=attempt + 1)
                    return
                logger.debug("post-turn context compaction skipped because the thread stayed busy")
            except Exception:  # noqa: BLE001
                logger.debug("post-turn context compaction skipped", exc_info=True)

        schedule_compact_later(delay=0.05, attempt=0)

    def _build_compacted_summary(self, values: dict[str, Any]) -> str:
        lines = ["Context compaction snapshot:"]
        branch_meta = values.get("branch_meta") if isinstance(values.get("branch_meta"), dict) else {}
        if branch_meta:
            lines.append(
                "Branch: "
                + ", ".join(
                    item
                    for item in [
                        str(branch_meta.get("branch_name") or "").strip(),
                        str(branch_meta.get("branch_role") or "").strip(),
                    ]
                    if item
                )
            )
        active_goal = str(values.get("active_goal") or "").strip()
        if active_goal:
            lines.append(f"Active goal: {active_goal}")
        constraints = self._compact_state_items(values.get("user_constraints"), key="constraint", limit=6)
        if constraints:
            lines.append("Constraints: " + "; ".join(constraints))
        pinned = self._compact_state_items(values.get("pinned_facts"), key="fact", limit=6)
        if pinned:
            lines.append("Pinned facts: " + "; ".join(pinned))
        findings = [
            *self._compact_state_items(values.get("imported_findings"), key="finding", limit=4),
            *self._compact_state_items(values.get("branch_local_findings"), key="finding", limit=4),
        ]
        if findings:
            lines.append("Findings: " + "; ".join(findings[:8]))

        previous = " ".join(str(values.get("rolling_summary") or "").split())
        if previous:
            lines.append("Previous summary: " + self._truncate_inline(previous, 900))

        recent_lines = []
        for message in list(values.get("messages", []) or [])[-self._CONTEXT_COMPACTION_RECENT_MESSAGES :]:
            role = getattr(message, "type", message.__class__.__name__.replace("Message", "").lower())
            content = self._message_content_to_text(getattr(message, "content", ""))
            if content.strip():
                recent_lines.append(f"{role}: {self._truncate_inline(content, 240)}")
        if recent_lines:
            lines.append("Recent conversation:")
            lines.extend(f"- {line}" for line in recent_lines)

        summary = "\n".join(line for line in lines if line.strip())
        return self._truncate_inline(summary, self._CONTEXT_COMPACTION_SUMMARY_CHARS)

    @staticmethod
    def _compact_state_items(items: Any, *, key: str, limit: int) -> list[str]:
        values: list[str] = []
        for item in list(items or [])[:limit]:
            if isinstance(item, dict):
                text = str(item.get(key) or item.get("summary") or item.get("content") or "").strip()
            else:
                text = str(getattr(item, key, "") or getattr(item, "summary", "") or item).strip()
            if text:
                values.append(ChatService._truncate_inline(text, 220))
        return values

    @staticmethod
    def _truncate_inline(text: str, max_chars: int) -> str:
        compact = " ".join(str(text or "").split())
        if len(compact) <= max_chars:
            return compact
        return f"{compact[: max(0, max_chars - 15)].rstrip()} ...[trimmed]"

    @staticmethod
    def _draft_message_from_payload(payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        for message in reversed(list(payload.get("messages", []) or [])):
            if isinstance(message, HumanMessage):
                return ChatService._message_content_to_text(getattr(message, "content", ""))
        return None

    def _normalize_result(self, result: Any) -> tuple[dict[str, Any], list[Any]]:
        if hasattr(result, 'value') and hasattr(result, 'interrupts'):
            return dict(result.value or {}), list(result.interrupts or [])
        if isinstance(result, dict):
            return result, []
        return {'result': result}, []

    def _response_payload(
        self,
        *,
        thread_id: str,
        user_id: str,
        context: RequestContext,
        branch_meta: BranchMeta | None,
        interrupts: list[Any],
        trace_correlation: TraceCorrelation | None = None,
    ) -> dict[str, Any]:
        values = self._safe_get_values(thread_id)
        messages = values.get('messages', [])
        branch_actions = serialize_branch_actions(normalize_branch_actions(values.get('branch_actions')))
        selected_model = str(values.get('selected_model') or self.runtime.settings.model)
        selected_thinking_mode = self._effective_thinking_mode(
            model_id=selected_model,
            thinking_mode=values.get('selected_thinking_mode'),
        )
        assistant_message = self._latest_final_ai_text(list(messages))
        return {
            'thread_id': thread_id,
            'root_thread_id': context.root_thread_id,
            'assistant_message': assistant_message,
            'rolling_summary': values.get('rolling_summary', ''),
            'selected_model': selected_model,
            'selected_thinking_mode': selected_thinking_mode,
            'branch_meta': branch_meta.model_dump(mode='json') if branch_meta else None,
            'merge_proposal': values.get('merge_proposal'),
            'merge_decision': values.get('merge_decision'),
            'merge_queue': values.get('merge_queue', []),
            'active_skill_ids': values.get('active_skill_ids', []),
            'messages': self._thread_state_messages(list(messages)),
            'interrupts': [getattr(item, 'value', item) for item in interrupts],
            'branch_actions': branch_actions,
            'trace': build_invoke_config(
                settings=self.runtime.settings,
                thread_id=thread_id,
                user_id=user_id,
                root_thread_id=context.root_thread_id,
                branch_meta=branch_meta,
                trace_correlation=trace_correlation,
            ),
            'context_usage': self._context_usage_payload(values),
        }

    def _effective_thinking_mode(self, *, model_id: str, thinking_mode: Any) -> str:
        settings = getattr(self.runtime, 'settings', None)
        if not supports_thinking_mode(model_id, settings=settings):
            return ''
        normalized = str(thinking_mode or '').strip().lower()
        if normalized in {'enabled', 'disabled'}:
            return normalized
        return 'enabled' if default_thinking_enabled(model_id, settings=settings) else 'disabled'

    def _turn_span_attributes(
        self,
        *,
        thread_id: str,
        user_id: str,
        root_thread_id: str,
        kind: str,
        branch_meta: BranchMeta | None,
    ) -> dict[str, Any]:
        attributes: dict[str, Any] = {
            "focus_agent.turn.kind": kind,
            "focus_agent.thread_id": thread_id,
            "focus_agent.root_thread_id": root_thread_id,
            "focus_agent.user_id": user_id,
            "service.name": getattr(self.runtime.settings, "tracing_service_name", "focus-agent"),
        }
        if branch_meta is not None:
            attributes.update(
                {
                    "focus_agent.branch_id": branch_meta.branch_id,
                    "focus_agent.branch_role": branch_meta.branch_role.value,
                    "focus_agent.branch_status": branch_meta.branch_status.value,
                }
            )
        return attributes

    def _run_invoke(
        self,
        *,
        thread_id: str,
        user_id: str,
        payload: Any,
        run_name: str,
        request_id: str | None = None,
        context_skill_hints: tuple[str, ...] | None = None,
        kind: str = 'chat.turn',
    ) -> dict[str, Any]:
        context, branch_meta, initial_values = self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            explicit_skill_hints=context_skill_hints,
            require_writable=True,
        )
        initial_message_count = len(list(initial_values.get('messages', []) or []))
        initial_llm_calls = int(initial_values.get('llm_calls') or 0)
        started_at = utc_now()
        trace_correlation: TraceCorrelation | None = None
        self._acquire_thread_turn(thread_id=thread_id)
        try:
            draft_message = self._draft_message_from_payload(payload)
            self._auto_compact_context_before_turn(
                thread_id=thread_id,
                values=initial_values,
                draft_message=draft_message,
            )
            trace_correlation = build_trace_correlation(
                settings=self.runtime.settings,
                request_id=request_id,
            )
            with start_trace_span(
                name=run_name,
                settings=self.runtime.settings,
                trace_correlation=trace_correlation,
                span_id=trace_correlation.root_span_id,
                attributes=self._turn_span_attributes(
                    thread_id=thread_id,
                    user_id=user_id,
                    root_thread_id=context.root_thread_id,
                    kind=kind,
                    branch_meta=branch_meta,
                ),
            ):
                config = build_invoke_config(
                    settings=self.runtime.settings,
                    thread_id=thread_id,
                    user_id=user_id,
                    root_thread_id=context.root_thread_id,
                    branch_meta=branch_meta,
                    trace_correlation=trace_correlation,
                    run_name=run_name,
                )
                result = self.runtime.graph.invoke(
                    payload,
                    config=config,
                    context=context,
                    version='v2',
                )
            _, interrupts = self._normalize_result(result)
            latest_context, latest_branch_meta, final_values = self._context_for_thread(thread_id=thread_id, user_id=user_id)
            response = self._response_payload(
                thread_id=thread_id,
                user_id=user_id,
                context=latest_context,
                branch_meta=latest_branch_meta,
                interrupts=interrupts,
                trace_correlation=trace_correlation,
            )
            self._record_turn_trajectory_best_effort(
                thread_id=thread_id,
                user_id=user_id,
                root_thread_id=latest_context.root_thread_id,
                kind=kind,
                status='succeeded',
                final_values=final_values,
                initial_message_count=initial_message_count,
                initial_llm_calls=initial_llm_calls,
                started_at=started_at,
                finished_at=utc_now(),
                branch_meta=latest_branch_meta,
                trace_correlation=trace_correlation,
                input_messages=list(payload.get('messages', []) if isinstance(payload, dict) else []),
                answer=response.get('assistant_message'),
            )
            self._schedule_post_turn_context_compaction(
                thread_id=thread_id,
                user_id=user_id,
                kind=kind,
            )
            self._schedule_branch_name_refresh_after_first_turn(
                thread_id=thread_id,
                user_id=user_id,
                branch_meta=latest_branch_meta,
                kind=kind,
            )
            return response
        except Exception as exc:
            self._record_turn_trajectory_best_effort(
                thread_id=thread_id,
                user_id=user_id,
                root_thread_id=context.root_thread_id,
                kind=kind,
                status='failed',
                final_values=self._safe_get_values(thread_id),
                initial_message_count=initial_message_count,
                initial_llm_calls=initial_llm_calls,
                started_at=started_at,
                finished_at=utc_now(),
                branch_meta=branch_meta,
                trace_correlation=trace_correlation,
                input_messages=list(payload.get('messages', []) if isinstance(payload, dict) else []),
                error=str(exc),
            )
            raise
        finally:
            self._release_thread_turn(thread_id=thread_id)

    def send_message(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        model: str | None = None,
        thinking_mode: str | None = None,
        request_id: str | None = None,
        skill_hints: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        branch_action_result = self._handle_branch_action_turn(
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            request_id=request_id,
        )
        if branch_action_result is not None:
            return branch_action_result["thread_state"]

        selection = self._select_skills_for_message(
            message=message,
            explicit_skill_hints=skill_hints,
        )
        selected_model = model or self.runtime.settings.model
        payload: dict[str, Any] = {
            'messages': [HumanMessage(content=message)],
            'task_brief': selection.stripped_message or message,
            'active_skill_ids': list(selection.skill_ids),
            'selected_model': selected_model,
            'selected_thinking_mode': self._effective_thinking_mode(
                model_id=selected_model,
                thinking_mode=thinking_mode,
            ),
        }
        if selection.prompt_mode is not None:
            payload['prompt_mode'] = selection.prompt_mode
        return self._run_invoke(
            thread_id=thread_id,
            user_id=user_id,
            payload=payload,
            run_name='focus_agent_turn',
            request_id=request_id,
            context_skill_hints=selection.skill_ids,
            kind='chat.turn',
        )

    def resume(self, *, thread_id: str, user_id: str, resume: Any, request_id: str | None = None) -> dict[str, Any]:
        return self._run_invoke(
            thread_id=thread_id,
            user_id=user_id,
            payload=Command(resume=resume),
            run_name='focus_agent_resume',
            request_id=request_id,
            kind='chat.resume',
        )

    def get_thread_state(self, *, thread_id: str, user_id: str, request_id: str | None = None) -> dict[str, Any]:
        context, branch_meta, _ = self._context_for_thread(thread_id=thread_id, user_id=user_id)
        self._ensure_access(thread_id=thread_id, user_id=user_id, context=context)
        trace_correlation = build_trace_correlation(
            settings=self.runtime.settings,
            request_id=request_id,
        )
        return self._response_payload(
            thread_id=thread_id,
            user_id=user_id,
            context=context,
            branch_meta=branch_meta,
            interrupts=self._safe_get_interrupts(thread_id),
            trace_correlation=trace_correlation,
        )

    @staticmethod
    def _is_chinese_text(text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in str(text or ""))

    def _branch_action_intent(self, *, values: dict[str, Any], branch_meta: BranchMeta | None, message: str) -> str | None:
        pending = latest_pending_branch_action(values.get("branch_actions"))
        if pending is not None and is_branch_action_confirmation(message):
            return "execute"
        if pending is not None and is_branch_action_dismissal(message):
            return "dismiss"
        if is_branch_action_request(message):
            return "propose"
        return None

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
        context, branch_meta, values = self._preflight_thread_access(
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
        is_chinese = self._is_chinese_text(message)
        assistant_text = proposal_message(action, is_chinese=is_chinese)
        audit = branch_action_audit_event(
            user_id=user_id,
            thread_id=thread_id,
            action=action,
            decision="proposed",
            reason="chat_branch_action_request",
            request_id=request_id,
        )
        self._update_branch_action_state(
            thread_id=thread_id,
            actions=actions,
            audit_event=audit,
            messages=[HumanMessage(content=message), AIMessage(content=assistant_text)],
        )
        thread_state = self.get_thread_state(thread_id=thread_id, user_id=user_id, request_id=request_id)
        return {
            "kind": "proposed",
            "message": assistant_text,
            "thread_state": thread_state,
            "branch_action": action.model_dump(mode="json"),
        }

    def _execute_branch_action_locked(
        self,
        *,
        thread_id: str,
        action_id: str,
        user_id: str,
        request_id: str | None = None,
        user_message: str | None = None,
    ) -> dict[str, Any]:
        context, branch_meta, values = self._preflight_thread_access(
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

        branch_record = None
        navigation: BranchActionNavigation | None = None
        try:
            if action.kind in {BranchActionKind.FORK_SIBLING_BRANCH, BranchActionKind.FORK_CHILD_BRANCH}:
                branch_record = self.runtime.branch_service.fork_branch(
                    parent_thread_id=action.target_parent_thread_id,
                    user_id=user_id,
                    branch_name=action.suggested_branch_name,
                    branch_role=action.branch_role,
                )
                navigation = BranchActionNavigation(
                    root_thread_id=branch_record.root_thread_id,
                    thread_id=branch_record.child_thread_id,
                )
            elif action.kind == BranchActionKind.RETURN_PARENT_BRANCH:
                navigation = BranchActionNavigation(root_thread_id=action.root_thread_id, thread_id=action.target_parent_thread_id)
            elif action.kind == BranchActionKind.OPEN_EXISTING_BRANCH:
                navigation = BranchActionNavigation(root_thread_id=action.root_thread_id, thread_id=action.target_parent_thread_id)
            else:
                raise ValueError(f"Unsupported branch action kind: {action.kind}")
        except Exception as exc:
            failed = mark_branch_action_failed(action, str(exc))
            self._update_branch_action_state(
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
        is_chinese = self._is_chinese_text(user_message or action.reason or "")
        assistant_text = execution_message(
            executed,
            branch_name=getattr(branch_record, "branch_name", None),
            is_chinese=is_chinese,
        )
        messages: list[Any] = []
        if user_message is not None:
            messages.append(HumanMessage(content=user_message))
        messages.append(AIMessage(content=assistant_text))
        self._update_branch_action_state(
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
        latest_context, latest_branch_meta, _ = self._context_for_thread(thread_id=thread_id, user_id=user_id)
        del context
        thread_state = self._response_payload(
            thread_id=thread_id,
            user_id=user_id,
            context=latest_context,
            branch_meta=latest_branch_meta,
            interrupts=self._safe_get_interrupts(thread_id),
            trace_correlation=build_trace_correlation(settings=self.runtime.settings, request_id=request_id),
        )
        return {
            "kind": "executed",
            "message": assistant_text,
            "thread_state": thread_state,
            "branch_action": executed.model_dump(mode="json"),
            "branch_record": branch_record.model_dump(mode="json") if branch_record is not None else None,
            "navigation": navigation.model_dump(mode="json") if navigation is not None else None,
        }

    def execute_branch_action(
        self,
        *,
        thread_id: str,
        action_id: str,
        user_id: str,
        request_id: str | None = None,
        user_message: str | None = None,
    ) -> dict[str, Any]:
        self._acquire_thread_turn(thread_id=thread_id)
        try:
            return self._execute_branch_action_locked(
                thread_id=thread_id,
                action_id=action_id,
                user_id=user_id,
                request_id=request_id,
                user_message=user_message,
            )
        finally:
            self._release_thread_turn(thread_id=thread_id)

    def _dismiss_branch_action_locked(
        self,
        *,
        thread_id: str,
        action_id: str,
        user_id: str,
        request_id: str | None = None,
        user_message: str | None = None,
    ) -> dict[str, Any]:
        self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            require_writable=True,
        )
        values = self._safe_get_values(thread_id)
        actions = normalize_branch_actions(values.get("branch_actions"))
        action = next((item for item in actions if item.action_id == action_id), None)
        if action is None:
            raise KeyError(action_id)
        if action.status.value != "pending":
            raise ValueError(f"Branch action {action_id} is not pending.")
        dismissed = mark_branch_action_dismissed(action)
        is_chinese = self._is_chinese_text(user_message or action.reason or "")
        assistant_text = dismissal_message(is_chinese=is_chinese)
        messages: list[Any] = []
        if user_message is not None:
            messages.append(HumanMessage(content=user_message))
        messages.append(AIMessage(content=assistant_text))
        self._update_branch_action_state(
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
        return self.get_thread_state(thread_id=thread_id, user_id=user_id, request_id=request_id)

    def dismiss_branch_action(
        self,
        *,
        thread_id: str,
        action_id: str,
        user_id: str,
        request_id: str | None = None,
        user_message: str | None = None,
    ) -> dict[str, Any]:
        self._acquire_thread_turn(thread_id=thread_id)
        try:
            return self._dismiss_branch_action_locked(
                thread_id=thread_id,
                action_id=action_id,
                user_id=user_id,
                request_id=request_id,
                user_message=user_message,
            )
        finally:
            self._release_thread_turn(thread_id=thread_id)

    def _handle_branch_action_turn(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        request_id: str | None = None,
    ) -> dict[str, Any] | None:
        context, branch_meta, values = self._context_for_thread(thread_id=thread_id, user_id=user_id)
        self._ensure_access(thread_id=thread_id, user_id=user_id, context=context)
        intent = self._branch_action_intent(values=values, branch_meta=branch_meta, message=message)
        if intent is None:
            return None
        self._acquire_thread_turn(thread_id=thread_id)
        try:
            context, branch_meta, values = self._context_for_thread(thread_id=thread_id, user_id=user_id)
            self._ensure_access(thread_id=thread_id, user_id=user_id, context=context)
            intent = self._branch_action_intent(values=values, branch_meta=branch_meta, message=message)
            if intent is None:
                return None
            if intent == "propose":
                return self._build_branch_action_proposal(
                    thread_id=thread_id,
                    user_id=user_id,
                    message=message,
                    request_id=request_id,
                )
            pending = latest_pending_branch_action(values.get("branch_actions"))
            if pending is None:
                return None
            if intent == "execute":
                return self._execute_branch_action_locked(
                    thread_id=thread_id,
                    action_id=pending.action_id,
                    user_id=user_id,
                    request_id=request_id,
                    user_message=message,
                )
            if intent == "dismiss":
                thread_state = self._dismiss_branch_action_locked(
                    thread_id=thread_id,
                    action_id=pending.action_id,
                    user_id=user_id,
                    request_id=request_id,
                    user_message=message,
                )
                return {
                    "kind": "dismissed",
                    "message": dismissal_message(is_chinese=self._is_chinese_text(message)),
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
            return None
        finally:
            self._release_thread_turn(thread_id=thread_id)

    async def _astream_branch_action_result(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        request_id: str | None,
    ) -> AsyncIterator[str]:
        try:
            result = self._handle_branch_action_turn(
                thread_id=thread_id,
                user_id=user_id,
                message=message,
                request_id=request_id,
            )
            if result is None:
                raise RuntimeError("No branch action intent was available.")
            yield self._sse_frame(
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
            yield self._sse_frame(event=event_name, data=payload)
            if result.get("message"):
                yield self._sse_frame(
                    event="visible_text.completed",
                    data={"content": result["message"], "thread_id": thread_id},
                )
                yield self._sse_frame(
                    event="message.completed",
                    data={"content": result["message"], "thread_id": thread_id},
                )
            yield self._sse_frame(event="turn.completed", data={"thread_state": result["thread_state"]})
        except Exception as exc:  # noqa: BLE001
            failed_action = next(
                (
                    action
                    for action in reversed(normalize_branch_actions(self._safe_get_values(thread_id).get("branch_actions")))
                    if action.status.value == "failed"
                ),
                None,
            )
            if failed_action is not None:
                yield self._sse_frame(
                    event="branch.action.failed",
                    data={"thread_id": thread_id, "branch_action": failed_action.model_dump(mode="json")},
                )
            yield self._sse_frame(
                event="turn.failed",
                data={"error": exc.__class__.__name__, "message": str(exc), "thread_id": thread_id},
            )
        finally:
            yield self._sse_frame(event="turn.closed", data={"status": "ok", "thread_id": thread_id})

    def _select_skills_for_message(
        self,
        *,
        message: str,
        explicit_skill_hints: tuple[str, ...],
    ) -> SkillSelection:
        registry = getattr(self.runtime, 'skill_registry', None)
        if registry is None:
            return SkillSelection(
                skill_ids=tuple(str(item) for item in explicit_skill_hints),
                stripped_message=message.strip(),
            )
        return registry.select_for_message(
            message,
            explicit_hints=explicit_skill_hints,
        )

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode='json')
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, list):
            return [ChatService._json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [ChatService._json_safe(item) for item in value]
        if isinstance(value, dict):
            return {str(key): ChatService._json_safe(item) for key, item in value.items()}
        if hasattr(value, 'content') or hasattr(value, 'tool_calls'):
            return {
                'type': getattr(value, 'type', value.__class__.__name__.replace('Message', '').lower()),
                'content': ChatService._message_content_to_text(getattr(value, 'content', '')),
                'tool_calls': ChatService._json_safe(getattr(value, 'tool_calls', None)),
                'name': getattr(value, 'name', None),
                'id': getattr(value, 'id', None),
            }
        return str(value)

    @staticmethod
    def _sse_frame(*, event: str, data: dict[str, Any]) -> str:
        payload = json.dumps(ChatService._json_safe(data), ensure_ascii=False)
        lines = [f'event: {event}']
        for line in payload.splitlines() or ['']:
            lines.append(f'data: {line}')
        return '\n'.join(lines) + '\n\n'

    def _schedule_branch_name_refresh_after_first_turn(
        self,
        *,
        thread_id: str,
        user_id: str,
        branch_meta: BranchMeta | None,
        kind: str,
    ) -> None:
        branch_service = getattr(self.runtime, 'branch_service', None)
        if branch_service is None:
            return
        if kind != 'chat.turn':
            return

        def dispatch_background(func, **kwargs) -> None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                threading.Thread(target=func, kwargs=kwargs, daemon=True).start()
                return
            loop.create_task(asyncio.to_thread(func, **kwargs))

        if branch_meta is None:
            refresh_title = getattr(branch_service, 'refresh_conversation_title_after_first_turn', None)
            if refresh_title is None:
                return
            dispatch_background(
                refresh_title,
                root_thread_id=thread_id,
                user_id=user_id,
            )
            return
        refresh_branch = getattr(branch_service, 'refresh_branch_metadata_after_first_turn', None)
        if refresh_branch is None:
            refresh_branch = getattr(branch_service, 'refresh_branch_name_after_first_turn', None)
        if refresh_branch is None:
            return
        dispatch_background(
            refresh_branch,
            child_thread_id=thread_id,
            user_id=user_id,
        )

    def _record_turn_trajectory_best_effort(
        self,
        *,
        thread_id: str,
        user_id: str,
        root_thread_id: str,
        kind: str,
        status: str,
        final_values: dict[str, Any],
        initial_message_count: int,
        initial_llm_calls: int,
        started_at,
        finished_at,
        branch_meta: BranchMeta | None,
        trace_correlation: TraceCorrelation | None = None,
        input_messages: list[Any] | None = None,
        answer: str | None = None,
        error: str | None = None,
    ) -> None:
        recorder = getattr(self.runtime, 'trajectory_recorder', None)
        if recorder is None:
            return
        record_turn = getattr(recorder, 'record_turn', None)
        if not callable(record_turn):
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
                observation_max_chars=self.runtime.settings.trajectory_observation_max_chars,
                answer_max_chars=self.runtime.settings.trajectory_answer_max_chars,
                hash_user_id=self.runtime.settings.trajectory_hash_user_id,
            )
            record_turn(record)
        except Exception:  # noqa: BLE001
            logger.warning("failed to persist turn trajectory", exc_info=True)

    async def _stream_graph_chunks(
        self,
        *,
        payload: Any,
        config: dict[str, Any],
        context: RequestContext,
        thread_id: str,
        user_id: str,
        kind: str,
        run_name: str,
        branch_meta: BranchMeta | None,
        trace_correlation: TraceCorrelation | None,
    ) -> AsyncIterator[dict[str, Any] | None]:
        with start_trace_span(
            name=run_name,
            settings=self.runtime.settings,
            trace_correlation=trace_correlation,
            span_id=trace_correlation.root_span_id if trace_correlation is not None else None,
            attributes=self._turn_span_attributes(
                thread_id=thread_id,
                user_id=user_id,
                root_thread_id=context.root_thread_id,
                kind=kind,
                branch_meta=branch_meta,
            ),
        ):
            if self._checkpointer_lacks_async_support():
                async for chunk in self._stream_graph_chunks_via_sync_stream(
                    payload=payload,
                    config=config,
                    context=context,
                ):
                    yield chunk
                return

            stream = self.runtime.graph.astream(
                payload,
                config=config,
                context=context,
                stream_mode=['messages', 'custom', 'updates', 'tasks'],
                version='v2',
            )
            stream_iter = stream.__aiter__()
            heartbeat_interval = max(float(self.runtime.settings.sse_heartbeat_seconds), 0.0)
            pending_next: asyncio.Task[Any] | None = None

            try:
                pending_next = asyncio.create_task(anext(stream_iter))
                while pending_next is not None:
                    if heartbeat_interval > 0:
                        done, _ = await asyncio.wait({pending_next}, timeout=heartbeat_interval)
                        if not done:
                            yield None
                            continue
                    try:
                        chunk = await pending_next
                    except StopAsyncIteration:
                        pending_next = None
                        break
                    pending_next = asyncio.create_task(anext(stream_iter))
                    yield chunk
            finally:
                if pending_next is not None and not pending_next.done():
                    pending_next.cancel()
                    with suppress(asyncio.CancelledError):
                        await pending_next
                aclose = getattr(stream_iter, 'aclose', None)
                if callable(aclose):
                    with suppress(Exception):  # noqa: BLE001
                        await aclose()

    def _checkpointer_lacks_async_support(self) -> bool:
        checkpointer = getattr(self.runtime, 'checkpointer', None)
        if checkpointer is None:
            return False
        return type(checkpointer).aget_tuple is BaseCheckpointSaver.aget_tuple

    @staticmethod
    def _is_internal_message_stream(metadata: dict[str, Any] | None) -> bool:
        node = str((metadata or {}).get('langgraph_node') or '').strip()
        return node in _INTERNAL_MESSAGE_STREAM_NODES

    @staticmethod
    def _is_tool_result_fallback_visible_delta(delta: str) -> bool:
        return delta.lstrip().startswith(_TOOL_RESULT_FALLBACK_VISIBLE_PREFIX)

    async def _stream_graph_chunks_via_sync_stream(
        self,
        *,
        payload: Any,
        config: dict[str, Any],
        context: RequestContext,
    ) -> AsyncIterator[dict[str, Any] | None]:
        stream = self.runtime.graph.stream(
            payload,
            config=config,
            context=context,
            stream_mode=['messages', 'custom', 'updates', 'tasks'],
            version='v2',
        )
        stream_iter = iter(stream)
        heartbeat_interval = max(float(self.runtime.settings.sse_heartbeat_seconds), 0.0)
        pending_next: asyncio.Task[Any] | None = None

        try:
            pending_next = asyncio.create_task(asyncio.to_thread(next, stream_iter, _STREAM_END))
            while pending_next is not None:
                if heartbeat_interval > 0:
                    done, _ = await asyncio.wait({pending_next}, timeout=heartbeat_interval)
                    if not done:
                        yield None
                        continue
                chunk = await pending_next
                if chunk is _STREAM_END:
                    pending_next = None
                    break
                pending_next = asyncio.create_task(asyncio.to_thread(next, stream_iter, _STREAM_END))
                yield chunk
        finally:
            if pending_next is not None and not pending_next.done():
                pending_next.cancel()
                with suppress(asyncio.CancelledError):
                    await pending_next
            close = getattr(stream_iter, 'close', None)
            if callable(close):
                with suppress(Exception):  # noqa: BLE001
                    close()

    async def _astream_result(
        self,
        *,
        thread_id: str,
        user_id: str,
        payload: Any,
        run_name: str,
        kind: str,
        request_id: str | None = None,
        context_skill_hints: tuple[str, ...] | None = None,
    ) -> AsyncIterator[str]:
        visible_text_buffer = ''
        reasoning_buffer = ''
        turn_acquired = False
        context: RequestContext | None = None
        branch_meta: BranchMeta | None = None
        trace_correlation: TraceCorrelation | None = None
        initial_message_count = 0
        initial_llm_calls = 0
        input_messages = list(payload.get('messages', []) if isinstance(payload, dict) else [])
        started_at = utc_now()
        try:
            context, branch_meta, initial_values = self._preflight_thread_access(
                thread_id=thread_id,
                user_id=user_id,
                explicit_skill_hints=context_skill_hints,
            )
            initial_messages = list(initial_values.get('messages', []) or [])
            initial_message_count = len(initial_messages)
            initial_llm_calls = int(initial_values.get('llm_calls') or 0)
            self._acquire_thread_turn(thread_id=thread_id)
            turn_acquired = True
            trace_correlation = build_trace_correlation(
                settings=self.runtime.settings,
                request_id=request_id,
            )
            config = build_invoke_config(
                settings=self.runtime.settings,
                thread_id=thread_id,
                user_id=user_id,
                root_thread_id=context.root_thread_id,
                branch_meta=branch_meta,
                trace_correlation=trace_correlation,
                run_name=run_name,
            )

            yield self._sse_frame(
                event='turn.status',
                data={'phase': 'accepted', 'thread_id': thread_id, 'kind': kind},
            )
            draft_message = self._draft_message_from_payload(payload)
            usage_before = self._context_usage_payload(initial_values, draft_message=draft_message)
            if (
                bool(getattr(self.runtime.settings, "context_auto_compaction_enabled", True))
                and float(usage_before.get("used_ratio") or 0)
                >= float(getattr(self.runtime.settings, "context_auto_compaction_pre_send_ratio", 0.92))
            ):
                yield self._sse_frame(
                    event='context.compaction.started',
                    data={'thread_id': thread_id, 'trigger': 'auto_pre_send', 'context_usage': usage_before},
                )
                compacted = self._auto_compact_context_before_turn(
                    thread_id=thread_id,
                    values=initial_values,
                    draft_message=draft_message,
                )
                latest_values = self._safe_get_values(thread_id) if compacted else initial_values
                yield self._sse_frame(
                    event='context.compaction.completed',
                    data={
                        'thread_id': thread_id,
                        'trigger': 'auto_pre_send',
                        'compacted': bool(compacted),
                        'context_usage': self._context_usage_payload(latest_values, draft_message=draft_message),
                    },
                )
            yield self._sse_frame(
                event='turn.status',
                data={'phase': 'invoke_started', 'thread_id': thread_id},
            )
            async for chunk in self._stream_graph_chunks(
                payload=payload,
                config=config,
                context=context,
                thread_id=thread_id,
                user_id=user_id,
                kind=kind,
                run_name=run_name,
                branch_meta=branch_meta,
                trace_correlation=trace_correlation,
            ):
                if chunk is None:
                    yield self._sse_frame(
                        event='status',
                        data={'stage': 'heartbeat', 'thread_id': thread_id, 'channel': 'system'},
                    )
                    continue
                chunk_type = chunk.get('type')
                data = chunk.get('data')
                namespace = list(chunk.get('ns') or ())

                if chunk_type == 'messages':
                    message_chunk, metadata = data
                    safe_metadata = sanitize_stream_metadata(metadata)
                    is_internal_message_stream = self._is_internal_message_stream(safe_metadata)
                    tool_chunks = extract_tool_call_chunks(message_chunk)

                    visible_delta = extract_visible_text_delta(message_chunk)
                    should_hide_visible_delta = (
                        is_internal_message_stream
                        or bool(tool_chunks)
                        or self._is_tool_result_fallback_visible_delta(visible_delta)
                    )
                    if visible_delta and not should_hide_visible_delta:
                        visible_text_buffer += visible_delta
                        payload_data = {
                            'delta': visible_delta,
                            'namespace': namespace,
                            'metadata': safe_metadata,
                            'channel': 'visible_text',
                        }
                        yield self._sse_frame(event='visible_text.delta', data=payload_data)
                        yield self._sse_frame(event='message.delta', data=payload_data)

                    reasoning_delta = extract_reasoning_delta(message_chunk)
                    if reasoning_delta and not is_internal_message_stream:
                        reasoning_buffer += reasoning_delta
                        yield self._sse_frame(
                            event='reasoning.delta',
                            data={
                                'delta': reasoning_delta,
                                'namespace': namespace,
                                'metadata': safe_metadata,
                                'channel': 'reasoning_tool_call',
                            },
                        )

                    for tool_chunk in tool_chunks:
                        yield self._sse_frame(
                            event='tool_call.delta',
                            data={
                                **tool_chunk,
                                'namespace': namespace,
                                'metadata': safe_metadata,
                                'channel': 'reasoning_tool_call',
                            },
                        )
                        yield self._sse_frame(
                            event='tool.call.delta',
                            data={
                                **tool_chunk,
                                'namespace': namespace,
                                'metadata': safe_metadata,
                                'channel': 'reasoning_tool_call',
                            },
                        )
                    continue

                if chunk_type == 'custom':
                    event_name, payload_data = map_custom_payload_to_event(data)
                    yield self._sse_frame(event=event_name, data={**payload_data, 'namespace': namespace})
                    continue

                if chunk_type == 'updates':
                    for item in extract_tool_requests_from_updates(data):
                        yield self._sse_frame(event='tool.requested', data={**item, 'namespace': namespace})
                    for item in extract_tool_results_from_updates(data):
                        yield self._sse_frame(event='tool.result', data={**item, 'namespace': namespace})
                    yield self._sse_frame(
                        event='agent.update',
                        data={'namespace': namespace, 'data': data},
                    )
                    continue

                if chunk_type == 'tasks':
                    event_name = 'task.update'
                    payload_data: dict[str, Any]
                    if isinstance(data, dict):
                        event_key = str(data.get('event') or data.get('status') or '').strip().lower()
                        if event_key:
                            suffix = event_key.replace('on_', '').replace('task_', '')
                            event_name = f'task.{suffix}'
                        payload_data = dict(data)
                    else:
                        payload_data = {'value': data}
                    yield self._sse_frame(event=event_name, data={**payload_data, 'namespace': namespace})
                    continue

                yield self._sse_frame(
                    event='stream.chunk',
                    data={'type': chunk_type, 'namespace': namespace, 'data': data},
                )

            latest_context, latest_branch_meta, final_values = self._context_for_thread(
                thread_id=thread_id,
                user_id=user_id,
            )
            final_state = self._response_payload(
                thread_id=thread_id,
                user_id=user_id,
                context=latest_context,
                branch_meta=latest_branch_meta,
                interrupts=self._safe_get_interrupts(thread_id),
                trace_correlation=trace_correlation,
            )
            final_messages = list(final_values.get('messages', []) or [])
            appended_messages = (
                final_messages[initial_message_count:]
                if len(final_messages) >= initial_message_count
                else final_messages
            )
            final_visible_text = self._latest_final_ai_text(appended_messages) or visible_text_buffer
            if final_visible_text:
                yield self._sse_frame(
                    event='visible_text.completed',
                    data={
                        'content': final_visible_text,
                        'thread_id': thread_id,
                    },
                )
                yield self._sse_frame(
                    event='message.completed',
                    data={
                        'content': final_visible_text,
                        'thread_id': thread_id,
                    },
                )
            if reasoning_buffer:
                yield self._sse_frame(
                    event='reasoning.completed',
                    data={
                        'content': reasoning_buffer,
                        'thread_id': thread_id,
                        },
                    )
            self._record_turn_trajectory_best_effort(
                thread_id=thread_id,
                user_id=user_id,
                root_thread_id=latest_context.root_thread_id,
                kind=kind,
                status='succeeded',
                final_values=final_values,
                initial_message_count=initial_message_count,
                initial_llm_calls=initial_llm_calls,
                started_at=started_at,
                finished_at=utc_now(),
                branch_meta=latest_branch_meta,
                trace_correlation=trace_correlation,
                input_messages=input_messages,
                answer=final_visible_text,
            )
            self._schedule_post_turn_context_compaction(
                thread_id=thread_id,
                user_id=user_id,
                kind=kind,
            )
            if final_state.get('interrupts'):
                for interrupt_payload in final_state['interrupts']:
                    yield self._sse_frame(
                        event='turn.interrupt',
                        data={'thread_id': thread_id, 'interrupt': interrupt_payload},
                    )
            self._schedule_branch_name_refresh_after_first_turn(
                thread_id=thread_id,
                user_id=user_id,
                branch_meta=latest_branch_meta,
                kind=kind,
            )
            yield self._sse_frame(
                event='turn.completed',
                data={'thread_state': final_state},
            )
        except Exception as exc:  # noqa: BLE001
            if turn_acquired and context is not None:
                self._record_turn_trajectory_best_effort(
                    thread_id=thread_id,
                    user_id=user_id,
                    root_thread_id=context.root_thread_id,
                    kind=kind,
                    status='failed',
                    final_values=self._safe_get_values(thread_id),
                    initial_message_count=initial_message_count,
                    initial_llm_calls=initial_llm_calls,
                    started_at=started_at,
                    finished_at=utc_now(),
                    branch_meta=branch_meta,
                    trace_correlation=trace_correlation,
                    input_messages=input_messages,
                    answer=visible_text_buffer or None,
                    error=str(exc),
                )
            yield self._sse_frame(
                event='turn.failed',
                data={
                    'error': exc.__class__.__name__,
                    'message': str(exc),
                    'thread_id': thread_id,
                },
            )
        finally:
            self._release_thread_turn(thread_id=thread_id)
            yield self._sse_frame(event='turn.closed', data={'status': 'ok', 'thread_id': thread_id})

    def stream_message(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        model: str | None = None,
        thinking_mode: str | None = None,
        request_id: str | None = None,
        skill_hints: tuple[str, ...] = (),
    ) -> AsyncIterator[str]:
        context, branch_meta, values = self._context_for_thread(thread_id=thread_id, user_id=user_id)
        self._ensure_access(thread_id=thread_id, user_id=user_id, context=context)
        if self._branch_action_intent(values=values, branch_meta=branch_meta, message=message) is not None:
            return self._astream_branch_action_result(
                thread_id=thread_id,
                user_id=user_id,
                message=message,
                request_id=request_id,
            )

        selection = self._select_skills_for_message(
            message=message,
            explicit_skill_hints=skill_hints,
        )
        selected_model = model or self.runtime.settings.model
        payload: dict[str, Any] = {
            'messages': [HumanMessage(content=message)],
            'task_brief': selection.stripped_message or message,
            'active_skill_ids': list(selection.skill_ids),
            'selected_model': selected_model,
            'selected_thinking_mode': self._effective_thinking_mode(
                model_id=selected_model,
                thinking_mode=thinking_mode,
            ),
        }
        if selection.prompt_mode is not None:
            payload['prompt_mode'] = selection.prompt_mode
        self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            explicit_skill_hints=selection.skill_ids,
            require_writable=True,
        )
        return self._astream_result(
            thread_id=thread_id,
            user_id=user_id,
            payload=payload,
            run_name='focus_agent_turn',
            kind='chat.turn',
            request_id=request_id,
            context_skill_hints=selection.skill_ids,
        )

    def stream_resume(
        self,
        *,
        thread_id: str,
        user_id: str,
        resume: Any,
        request_id: str | None = None,
    ) -> AsyncIterator[str]:
        self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            require_writable=True,
        )
        return self._astream_result(
            thread_id=thread_id,
            user_id=user_id,
            payload=Command(resume=resume),
            run_name='focus_agent_resume',
            kind='chat.resume',
            request_id=request_id,
        )


class ConcurrentTurnError(RuntimeError):
    """Raised when a thread already has an in-flight turn."""
