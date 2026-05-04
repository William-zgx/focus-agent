from __future__ import annotations

import logging
import threading
from typing import Any

from langchain.messages import HumanMessage

from ..context_usage import build_context_usage
from ..observability.trajectory import utc_now
from .chat_turn_errors import ConcurrentTurnError

logger = logging.getLogger("focus_agent.chat")


class ChatContextCompactionMixin:
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

        now = utc_now().isoformat()
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

    def _compact_state_items(self, items: Any, *, key: str, limit: int) -> list[str]:
        values: list[str] = []
        for item in list(items or [])[:limit]:
            if isinstance(item, dict):
                text = str(item.get(key) or item.get("summary") or item.get("content") or "").strip()
            else:
                text = str(getattr(item, key, "") or getattr(item, "summary", "") or item).strip()
            if text:
                values.append(self._truncate_inline(text, 220))
        return values

    @staticmethod
    def _truncate_inline(text: str, max_chars: int) -> str:
        compact = " ".join(str(text or "").split())
        if len(compact) <= max_chars:
            return compact
        return f"{compact[: max(0, max_chars - 15)].rstrip()} ...[trimmed]"

    def _draft_message_from_payload(self, payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        for message in reversed(list(payload.get("messages", []) or [])):
            if isinstance(message, HumanMessage):
                return self._message_content_to_text(getattr(message, "content", ""))
        return None
