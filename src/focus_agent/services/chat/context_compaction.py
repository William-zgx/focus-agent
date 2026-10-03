from __future__ import annotations

import logging
from typing import Any

from langchain.messages import HumanMessage

from ...core.context_compaction import build_incremental_compaction_update
from ...core.repo_call import has_repo_method
from ...observability.trajectory import utc_now
from ..coordination import background_job_key

logger = logging.getLogger("focus_agent.chat")


class ChatContextCompactionMixin:
    def _context_usage_payload(
        self, values: dict[str, Any], *, draft_message: str | None = None
    ) -> dict[str, Any]:
        try:
            from ...context_usage import build_context_usage

            selected_model = str(values.get("selected_model") or self.runtime.settings.model)
            registry = getattr(self.runtime, "tool_registry", None)
            available_tools = tuple(getattr(registry, "tools", ()) or ())
            return build_context_usage(
                values,
                draft_message=draft_message,
                selected_model=selected_model,
                available_tools=available_tools,
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
                "counting_backend": "chars_fallback",
                "tokenizer_id": None,
                "estimated": True,
                "drift_risk": "high",
                "last_compacted_at": None,
                "error": str(exc),
            }

    def preview_thread_context(
        self, *, thread_id: str, user_id: str, draft_message: str | None = None
    ) -> dict[str, Any]:
        self._assert_known_thread_owner_before_context(thread_id=thread_id, user_id=user_id)
        context, _branch_meta, values = self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
        )
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
        self._assert_known_thread_owner_before_context(thread_id=thread_id, user_id=user_id)
        _context, branch_meta, values = self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            require_writable=True,
        )
        with self._thread_turn_lease(thread_id=thread_id) as turn_lease:
            self._compact_thread_context_locked(
                thread_id=thread_id,
                values=values,
                trigger=trigger,
                draft_message=draft_message,
                force=force,
            )
            turn_lease.raise_if_lost()
            latest_context, latest_branch_meta, _ = self._context_for_thread(
                thread_id=thread_id, user_id=user_id
            )
            return self._response_payload(
                thread_id=thread_id,
                user_id=user_id,
                context=latest_context,
                branch_meta=latest_branch_meta or branch_meta,
                interrupts=self._safe_get_interrupts(thread_id),
                trace_correlation=None,
            )

    def _assert_known_thread_owner_before_context(self, *, thread_id: str, user_id: str) -> None:
        """Reject a known owner mismatch before loading graph state.

        Unknown/legacy threads retain the existing access path: ``_ensure_access``
        may establish ownership after resolving the context.  For repositories
        that already know the owner, the check must happen before
        ``_context_for_thread`` can read or derive any state.
        """
        repo = getattr(self.runtime, "repo", None)
        get_owner = getattr(repo, "get_thread_owner", None)
        assert_owner = getattr(repo, "assert_thread_owner", None)
        if not callable(get_owner) or not callable(assert_owner):
            return
        if get_owner(thread_id=thread_id) is not None:
            assert_owner(thread_id=thread_id, owner_user_id=user_id)

    def _compact_thread_context_locked(
        self,
        *,
        thread_id: str,
        values: dict[str, Any],
        trigger: str,
        draft_message: str | None = None,
        force: bool = False,
    ) -> dict[str, Any] | None:
        # The caller may have preflighted the thread before acquiring the lease.
        # Re-read while the lease is held so a branch merge/artifact update is
        # not compacted from an older snapshot.
        try:
            snapshot = self.runtime.graph.get_state({"configurable": {"thread_id": thread_id}})
            snapshot_values = getattr(snapshot, "values", None)
            if not isinstance(snapshot_values, dict):
                raise RuntimeError("graph state refresh returned no mapping")
            latest_values = dict(snapshot_values)
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to refresh state before compaction; skipping", exc_info=True)
            raise RuntimeError("cannot compact without a fresh graph state") from exc

        if getattr(snapshot, "interrupts", ()):
            from .service import ConcurrentTurnError

            # LangGraph update_state clears pending interrupt writes. Wait for
            # the user's answer/approval instead of invalidating its resume ID.
            raise ConcurrentTurnError(
                "Context compaction is deferred while a user response or tool approval is pending."
            )

        usage = self._context_usage_payload(latest_values, draft_message=draft_message)
        threshold = self._context_compaction_threshold(trigger)
        if not force and self._pretrim_context_ratio(usage) < threshold:
            return None

        previous_meta = (
            latest_values.get("context_compaction")
            if isinstance(latest_values.get("context_compaction"), dict)
            else {}
        )
        update = build_incremental_compaction_update(
            latest_values,
            previous_meta,
            trigger=trigger,
            force=force,
            now=utc_now().isoformat(),
        )
        summary = str(update.get("rolling_summary") or "")
        compact_meta = dict(update.get("context_compaction") or {})
        if not force and compact_meta.get("no_gain") is True:
            return None
        before_usage = {
            "used_tokens": int(usage.get("used_tokens") or 0),
            "pretrim_tokens": int(usage.get("pretrim_tokens") or 0),
            "posttrim_tokens": int(usage.get("posttrim_tokens") or 0),
            "input_token_limit": int(
                usage.get("input_token_limit") or usage.get("token_limit") or 0
            ),
            "prompt_chars": int(usage.get("prompt_chars") or 0),
            "summary_chars": len(str(latest_values.get("rolling_summary") or "")),
        }
        after_values = {
            **latest_values,
            "rolling_summary": summary,
            "context_compaction": compact_meta,
        }
        after_usage = self._context_usage_payload(after_values, draft_message=draft_message)
        after_measurement = {
            "used_tokens": int(after_usage.get("used_tokens") or 0),
            "pretrim_tokens": int(after_usage.get("pretrim_tokens") or 0),
            "posttrim_tokens": int(after_usage.get("posttrim_tokens") or 0),
            "input_token_limit": int(
                after_usage.get("input_token_limit") or after_usage.get("token_limit") or 0
            ),
            "prompt_chars": int(after_usage.get("prompt_chars") or 0),
            "summary_chars": len(summary),
        }
        no_gain = (
            after_measurement["pretrim_tokens"] >= before_usage["pretrim_tokens"]
            and after_measurement["prompt_chars"] >= before_usage["prompt_chars"]
        )
        compact_meta.update(
            {
                "source_prompt_tokens": before_usage["used_tokens"],
                "source_prompt_chars": before_usage["prompt_chars"],
                "before": {**dict(compact_meta.get("before") or {}), **before_usage},
                "after": {**dict(compact_meta.get("after") or {}), **after_measurement},
                "no_gain": no_gain,
                "status": "no_gain" if no_gain else "updated",
                "context_compaction_drift_report": compact_meta.get(
                    "context_compaction_drift_report", {}
                ),
                "non_destructive": True,
            }
        )
        final_update = {
            "rolling_summary": summary,
            "context_compaction": compact_meta,
        }
        self.runtime.graph.update_state(
            {"configurable": {"thread_id": thread_id}},
            final_update,
        )
        return final_update

    @staticmethod
    def _pretrim_context_ratio(usage: dict[str, Any]) -> float:
        numerator = int(usage.get("pretrim_tokens") or usage.get("used_tokens") or 0)
        denominator = int(usage.get("input_token_limit") or usage.get("token_limit") or 0)
        if denominator <= 0:
            if bool(usage.get("required_overflow")):
                return 1.0
            return 0.0
        return numerator / denominator

    def _context_compaction_threshold(self, trigger: str) -> float:
        if trigger == "auto_post_turn":
            return float(
                getattr(self.runtime.settings, "context_auto_compaction_post_turn_ratio", 0.85)
            )
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

    def _schedule_post_turn_context_compaction(
        self, *, thread_id: str, user_id: str, kind: str
    ) -> None:
        if kind not in {"chat.turn", "chat.resume"}:
            return
        if not bool(getattr(self.runtime.settings, "context_auto_compaction_enabled", True)):
            return
        job_key = background_job_key(kind="context_compaction", thread_id=thread_id)
        durable_enqueued = self._enqueue_durable_background_job(
            kind="context_compaction",
            key=job_key,
            payload={
                "thread_id": thread_id,
                "user_id": user_id,
                "trigger": "auto_post_turn",
                "force": False,
            },
            delay_seconds=0.05,
            max_attempts=3,
            dedupe_policy="replace",
        )
        if durable_enqueued is not None:
            return

        def schedule_compact_later(*, delay: float, attempt: int) -> None:
            if has_repo_method(self, "_submit_background_work"):
                self._submit_background_work(
                    key=job_key,
                    func=compact_later,
                    delay_seconds=delay,
                    attempt=attempt,
                )
                return
            compact_later(attempt=attempt)

        def compact_later(*, attempt: int) -> None:
            from .service import ConcurrentTurnError

            try:
                self.compact_thread_context(
                    thread_id=thread_id,
                    user_id=user_id,
                    trigger="auto_post_turn",
                    force=False,
                )
            except Exception as exc:
                if isinstance(exc, ConcurrentTurnError):
                    if attempt < 2:
                        if has_repo_method(self, "_release_background_job_key"):
                            self._release_background_job_key(job_key)
                        schedule_compact_later(delay=0.2, attempt=attempt + 1)
                        return
                    logger.debug(
                        "post-turn context compaction skipped because the thread stayed busy"
                    )
                else:
                    logger.debug("post-turn context compaction skipped", exc_info=True)

        schedule_compact_later(delay=0.05, attempt=0)

    def _draft_message_from_payload(self, payload: Any) -> str | None:
        if not isinstance(payload, dict):
            return None
        for message in reversed(list(payload.get("messages", []) or [])):
            if isinstance(message, HumanMessage):
                return self._message_content_to_text(getattr(message, "content", ""))
        return None
