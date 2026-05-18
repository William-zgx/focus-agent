from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
import logging
import threading
from typing import Any

from langchain.messages import HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from ...core.branching import BranchMeta
from ...core.repo_call import has_repo_method
from ...observability.tracing import TraceCorrelation
from ...observability.trajectory import utc_now
from .threads import record_turn_trajectory_best_effort
from ..coordination import background_job_key

logger = logging.getLogger("focus_agent.chat")

_STREAM_END = object()


async def stream_graph_chunks(
    *,
    graph: Any,
    checkpointer: Any,
    settings: Any,
    payload: Any,
    config: dict[str, Any],
    context: Any,
) -> AsyncIterator[dict[str, Any] | None]:
    if checkpointer_lacks_async_support(checkpointer):
        async for chunk in stream_graph_chunks_via_sync_stream(
            graph=graph,
            settings=settings,
            payload=payload,
            config=config,
            context=context,
        ):
            yield chunk
        return

    stream_iter = graph.astream(
        payload,
        config=config,
        context=context,
        stream_mode=['messages', 'custom', 'updates', 'tasks'],
        version='v2',
    ).__aiter__()

    async for chunk in _consume_graph_stream(
        stream_iter=stream_iter,
        heartbeat_interval=max(float(settings.sse_heartbeat_seconds), 0.0),
        next_chunk=lambda: _next_graph_chunk(stream_iter),
        close_method='aclose',
    ):
        yield chunk


async def stream_graph_chunks_via_sync_stream(
    *,
    graph: Any,
    settings: Any,
    payload: Any,
    config: dict[str, Any],
    context: Any,
) -> AsyncIterator[dict[str, Any] | None]:
    stream_iter = graph.stream(
        payload,
        config=config,
        context=context,
        stream_mode=['messages', 'custom', 'updates', 'tasks'],
        version='v2',
    )
    async for chunk in _consume_graph_stream(
        stream_iter=stream_iter,
        heartbeat_interval=max(float(settings.sse_heartbeat_seconds), 0.0),
        next_chunk=lambda: asyncio.to_thread(next, stream_iter, _STREAM_END),
        close_method='close',
    ):
        yield chunk


async def _consume_graph_stream(
    *,
    stream_iter: Any,
    heartbeat_interval: float,
    next_chunk: Any,
    close_method: str,
) -> AsyncIterator[dict[str, Any] | None]:
    task: asyncio.Task[Any] | None = None
    try:
        task = asyncio.create_task(next_chunk())
        while task is not None:
            if heartbeat_interval > 0:
                done, _ = await asyncio.wait({task}, timeout=heartbeat_interval)
                if not done:
                    yield None
                    continue
            chunk = await task
            if chunk is _STREAM_END:
                break
            task = asyncio.create_task(next_chunk())
            yield chunk
    finally:
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await _close_stream_iter(stream_iter=stream_iter, close_method=close_method)


async def _next_graph_chunk(stream_iter: Any) -> Any:
    try:
        return await anext(stream_iter)
    except StopAsyncIteration:
        return _STREAM_END


async def _close_stream_iter(*, stream_iter: Any, close_method: str) -> None:
    if not has_repo_method(stream_iter, close_method):
        return
    with suppress(Exception):  # noqa: BLE001
        result = getattr(stream_iter, close_method)()
        if close_method == 'aclose' and hasattr(result, '__await__'):
            await result


def checkpointer_lacks_async_support(checkpointer: Any) -> bool:
    if checkpointer is None:
        return False
    return type(checkpointer).aget_tuple is BaseCheckpointSaver.aget_tuple


class ChatTurnRecordingMixin:
    _POST_TURN_REFRESH_KINDS = {"chat.turn", "chat.resume"}

    def _schedule_branch_name_refresh_after_first_turn(
        self,
        *,
        thread_id: str,
        user_id: str,
        branch_meta: BranchMeta | None,
        kind: str,
    ) -> None:
        branch_service = getattr(self.runtime, "branch_service", None)
        if branch_service is None:
            return
        if kind not in self._POST_TURN_REFRESH_KINDS:
            return

        def dispatch_background(func, **kwargs) -> None:
            if has_repo_method(self, "_submit_background_work"):
                task_key = str(kwargs.pop("_background_task_key"))
                self._submit_background_work(key=task_key, func=func, **kwargs)
                return
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                threading.Thread(target=func, kwargs=kwargs, daemon=True).start()
                return
            loop.create_task(asyncio.to_thread(func, **kwargs))

        if branch_meta is None:
            refresh_title = getattr(
                branch_service, "refresh_conversation_title_after_first_turn", None
            )
            if refresh_title is None:
                return
            task_key = background_job_key(kind="conversation_title", thread_id=thread_id)
            durable_enqueued = self._enqueue_durable_background_job(
                kind="conversation_title",
                key=task_key,
                payload={"root_thread_id": thread_id, "user_id": user_id},
                max_attempts=3,
                dedupe_policy="replace",
            )
            if durable_enqueued is not None:
                return
            dispatch_background(
                refresh_title,
                _background_task_key=task_key,
                root_thread_id=thread_id,
                user_id=user_id,
            )
            return
        refresh_branch = getattr(branch_service, "refresh_branch_metadata_after_first_turn", None)
        if refresh_branch is None:
            refresh_branch = getattr(branch_service, "refresh_branch_name_after_first_turn", None)
        if refresh_branch is None:
            return
        task_key = background_job_key(kind="branch_title", thread_id=thread_id)
        durable_enqueued = self._enqueue_durable_background_job(
            kind="branch_title",
            key=task_key,
            payload={"child_thread_id": thread_id, "user_id": user_id},
            max_attempts=3,
            dedupe_policy="replace",
        )
        if durable_enqueued is not None:
            return
        dispatch_background(
            refresh_branch,
            _background_task_key=task_key,
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
        record_turn_trajectory_best_effort(
            recorder=getattr(self.runtime, "trajectory_recorder", None),
            settings=self.runtime.settings,
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
        )


class ChatContextCompactionMixin:
    def _context_usage_payload(
        self, values: dict[str, Any], *, draft_message: str | None = None
    ) -> dict[str, Any]:
        try:
            from ...context_usage import build_context_usage

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
        context, _branch_meta, values = self._context_for_thread(
            thread_id=thread_id, user_id=user_id
        )
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
        previous_meta = (
            values.get("context_compaction")
            if isinstance(values.get("context_compaction"), dict)
            else {}
        )
        if not force and int(previous_meta.get("source_message_count") or -1) == len(messages):
            return None

        now = utc_now().isoformat()
        summary = self._build_compacted_summary(values)
        drift_report = self._build_context_compaction_drift_report(
            values=values,
            summary=summary,
        )
        compact_meta = {
            **previous_meta,
            "last_compacted_at": now,
            "trigger": trigger,
            "source_message_count": len(messages),
            "source_prompt_tokens": int(usage.get("used_tokens") or 0),
            "source_prompt_chars": int(usage.get("prompt_chars") or 0),
            "context_compaction_drift_report": drift_report,
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
                    logger.debug("post-turn context compaction skipped because the thread stayed busy")
                else:
                    logger.debug("post-turn context compaction skipped", exc_info=True)

        schedule_compact_later(delay=0.05, attempt=0)

    def _build_compacted_summary(self, values: dict[str, Any]) -> str:
        lines = ["Context compaction snapshot:"]
        branch_meta = (
            values.get("branch_meta") if isinstance(values.get("branch_meta"), dict) else {}
        )
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
        constraints = self._compact_state_items(
            values.get("user_constraints"), key="constraint", limit=6
        )
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
        artifact_refs = self._compact_artifact_refs(values.get("artifacts"), limit=6)
        if artifact_refs:
            lines.append("Artifact refs: " + "; ".join(artifact_refs))

        previous = " ".join(str(values.get("rolling_summary") or "").split())
        if previous:
            lines.append("Previous summary: " + self._truncate_inline(previous, 900))

        recent_lines = []
        for message in list(values.get("messages", []) or [])[
            -self._CONTEXT_COMPACTION_RECENT_MESSAGES :
        ]:
            role = getattr(
                message, "type", message.__class__.__name__.replace("Message", "").lower()
            )
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
                text = str(
                    item.get(key) or item.get("summary") or item.get("content") or ""
                ).strip()
            else:
                text = str(getattr(item, key, "") or getattr(item, "summary", "") or item).strip()
            if text:
                values.append(self._truncate_inline(text, 220))
        return values

    def _compact_artifact_refs(self, items: Any, *, limit: int) -> list[str]:
        refs: list[str] = []
        for item in list(items or [])[:limit]:
            if isinstance(item, dict):
                title = str(item.get("title") or item.get("artifact_id") or "").strip()
                uri = str(item.get("uri") or item.get("artifact_id") or "").strip()
            else:
                title = str(getattr(item, "title", "") or getattr(item, "artifact_id", "")).strip()
                uri = str(getattr(item, "uri", "") or getattr(item, "artifact_id", "")).strip()
            text = " ".join(part for part in (title, uri) if part)
            if text:
                refs.append(self._truncate_inline(text, 220))
        return refs

    def _build_context_compaction_drift_report(
        self,
        *,
        values: dict[str, Any],
        summary: str,
    ) -> dict[str, Any]:
        source_text = self._compaction_source_text(values)
        recall_targets = self._compaction_recall_targets(values)
        grounding_targets = self._compaction_grounding_targets(values)
        answerability_targets = self._compaction_answerability_targets(values)
        recall = self._target_coverage(recall_targets, summary)
        precision = self._summary_precision(summary=summary, source_text=source_text)
        grounding = self._target_coverage(grounding_targets, summary)
        answerability = self._target_coverage(answerability_targets, summary)
        overall_drift = round(1.0 - ((recall + precision + grounding + answerability) / 4), 4)
        if overall_drift >= 0.34:
            drift_risk = "high"
        elif overall_drift > 0.0:
            drift_risk = "medium"
        else:
            drift_risk = "low"
        return {
            "recall": recall,
            "precision": precision,
            "grounding": grounding,
            "answerability": answerability,
            "overall_drift": overall_drift,
            "drift_risk": drift_risk,
            "target_counts": {
                "recall": len(recall_targets),
                "grounding": len(grounding_targets),
                "answerability": len(answerability_targets),
            },
        }

    def _compaction_source_text(self, values: dict[str, Any]) -> str:
        parts: list[str] = [
            str(values.get("active_goal") or ""),
            str(values.get("rolling_summary") or ""),
        ]
        for key in (
            "user_constraints",
            "pinned_facts",
            "imported_findings",
            "branch_local_findings",
            "artifacts",
        ):
            parts.extend(self._compact_source_items(values.get(key)))
        for message in list(values.get("messages", []) or []):
            parts.append(self._message_content_to_text(getattr(message, "content", "")))
        return "\n".join(part for part in parts if str(part).strip())

    def _compact_source_items(self, items: Any) -> list[str]:
        source_items: list[str] = []
        for item in list(items or []):
            if isinstance(item, dict):
                source_items.extend(str(value) for value in item.values() if value)
            else:
                source_items.append(str(item))
                for attr in ("fact", "constraint", "finding", "title", "summary", "uri", "artifact_id"):
                    value = getattr(item, attr, None)
                    if value:
                        source_items.append(str(value))
        return source_items

    def _compaction_recall_targets(self, values: dict[str, Any]) -> list[str]:
        targets = [
            str(values.get("active_goal") or "").strip(),
            *self._compact_state_items(values.get("user_constraints"), key="constraint", limit=6),
            *self._compact_state_items(values.get("pinned_facts"), key="fact", limit=6),
            *self._compact_state_items(values.get("imported_findings"), key="finding", limit=4),
            *self._compact_state_items(values.get("branch_local_findings"), key="finding", limit=4),
        ]
        return self._dedupe_compaction_targets(targets)

    def _compaction_grounding_targets(self, values: dict[str, Any]) -> list[str]:
        targets: list[str] = []
        for item in list(values.get("artifacts") or []):
            if isinstance(item, dict):
                targets.extend(
                    str(item.get(key) or "").strip()
                    for key in ("uri", "artifact_id")
                    if item.get(key)
                )
            else:
                for attr in ("uri", "artifact_id"):
                    value = getattr(item, attr, None)
                    if value:
                        targets.append(str(value).strip())
        for item in [*list(values.get("imported_findings") or []), *list(values.get("branch_local_findings") or [])]:
            refs = item.get("evidence_refs") if isinstance(item, dict) else getattr(item, "evidence_refs", [])
            targets.extend(str(ref).strip() for ref in list(refs or []) if str(ref).strip())
        return self._dedupe_compaction_targets(targets)

    def _compaction_answerability_targets(self, values: dict[str, Any]) -> list[str]:
        targets = [
            str(values.get("active_goal") or "").strip(),
            *self._compact_state_items(values.get("user_constraints"), key="constraint", limit=4),
            *self._compact_state_items(values.get("pinned_facts"), key="fact", limit=4),
        ]
        if not any(targets):
            for message in reversed(list(values.get("messages", []) or [])):
                content = self._message_content_to_text(getattr(message, "content", ""))
                if content.strip():
                    targets.append(content)
                    break
        return self._dedupe_compaction_targets(targets)

    @staticmethod
    def _dedupe_compaction_targets(targets: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for target in targets:
            compact = " ".join(str(target or "").split())
            if not compact:
                continue
            key = compact.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(compact)
        return deduped

    def _target_coverage(self, targets: list[str], summary: str) -> float:
        if not targets:
            return 1.0
        covered = sum(1 for target in targets if self._summary_contains_target(summary, target))
        return round(covered / len(targets), 4)

    def _summary_precision(self, *, summary: str, source_text: str) -> float:
        claims = [
            line.strip("- ").strip()
            for line in summary.splitlines()
            if line.strip() and not line.strip().endswith(":")
        ]
        claims = [claim for claim in claims if len(claim) >= 12]
        if not claims:
            return 1.0
        supported = sum(1 for claim in claims if self._summary_contains_target(source_text, claim))
        return round(supported / len(claims), 4)

    @staticmethod
    def _summary_contains_target(haystack: str, target: str) -> bool:
        normalized_haystack = " ".join(str(haystack or "").casefold().split())
        normalized_target = " ".join(str(target or "").casefold().split())
        if not normalized_target:
            return True
        if normalized_target in normalized_haystack:
            return True
        prefix = normalized_target[:80].strip()
        if len(prefix) >= 24 and prefix in normalized_haystack:
            return True
        words = [word for word in normalized_target.split() if len(word) >= 4]
        if not words:
            return False
        required = max(1, int(len(words) * 0.67))
        return sum(1 for word in words if word in normalized_haystack) >= required

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
