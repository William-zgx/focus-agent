from __future__ import annotations

import logging
import threading
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from typing import Protocol as Protocol

from langchain.messages import AIMessage, HumanMessage
from langgraph.types import Command

from ...core.branching import (
    BranchActionKind as BranchActionKind,
)
from ...core.branching import (
    BranchActionNavigation as BranchActionNavigation,
)
from ...core.branching import (
    BranchMeta,
)
from ...core.repo_call import has_repo_method
from ...core.request_context import RequestContext
from ...observability.tracing import (
    TraceCorrelation,
    build_invoke_config,
    build_trace_correlation,
    start_trace_span,
)
from ...observability.trajectory import utc_now
from ...skills.models import SkillSelection
from ..branch_actions import (
    latest_pending_branch_action,
    normalize_branch_actions,
    proposal_message,
    serialize_branch_actions,
)
from ..chat_turn_errors import ConcurrentTurnError  # noqa: F401
from ..coordination import (
    BackgroundJobSpec,
    background_job_key,
    create_in_memory_coordination_backend,
)
from .branch_actions import ChatBranchActionFacadeMixin
from .branch_navigation import (  # noqa: F401
    BranchServiceProtocol,
    execute_branch_action_navigation,
)
from .ports import ChatServicePorts
from .threads import (
    ChatThreadAccessMixin,
    effective_thinking_mode,
    json_safe,
    latest_final_ai_text,
    message_content_to_text,
    response_payload,
    serialize_message,
    sse_frame,
    thread_state_messages,
)
from .turns import ChatContextCompactionMixin, ChatTurnRecordingMixin

if TYPE_CHECKING:
    from ...engine.runtime import AppRuntime
    from ..thread_turn_lease import ThreadTurnLeaseManager

logger = logging.getLogger("focus_agent.chat")


class ChatService(
    ChatBranchActionFacadeMixin,
    ChatTurnRecordingMixin,
    ChatContextCompactionMixin,
    ChatThreadAccessMixin,
):
    _THREAD_STATE_MESSAGE_LIMIT = 200
    _CONTEXT_COMPACTION_SUMMARY_CHARS = 2600
    _CONTEXT_COMPACTION_RECENT_MESSAGES = 8

    def __init__(self, runtime: AppRuntime | ChatServicePorts):
        self.ports = (
            runtime
            if isinstance(runtime, ChatServicePorts)
            else ChatServicePorts.from_runtime(runtime)
        )
        self.runtime = self.ports
        self._coordination_backend = (
            self.ports.coordination_backend or create_in_memory_coordination_backend()
        )
        self._active_turn_leases: dict[str, Any] = {}
        self._active_turns_lock = threading.Lock()
        self._background_work = self.ports.background_work

    def _thread_turn_lease(self, *, thread_id: str) -> ThreadTurnLeaseManager:
        from ..thread_turn_lease import ThreadTurnLeaseManager

        return ThreadTurnLeaseManager(
            backend=self._coordination_backend.thread_turns,
            thread_id=thread_id,
            ttl_seconds=self._thread_turn_lock_ttl_seconds(),
            heartbeat_interval_seconds=self._thread_turn_lock_heartbeat_seconds(),
        )

    def _acquire_thread_turn(self, *, thread_id: str) -> None:
        lease = self._thread_turn_lease(thread_id=thread_id)
        lease.acquire()
        with self._active_turns_lock:
            self._active_turn_leases[thread_id] = lease

    def _heartbeat_thread_turn(self, *, thread_id: str) -> bool:
        with self._active_turns_lock:
            lease = self._active_turn_leases.get(thread_id)
        if lease is None:
            return False
        return lease.heartbeat_once()

    def _release_thread_turn(self, *, thread_id: str) -> None:
        with self._active_turns_lock:
            lease = self._active_turn_leases.pop(thread_id, None)
        if lease is not None:
            lease.close()

    def _thread_turn_lock_ttl_seconds(self) -> float:
        return max(
            float(
                getattr(self.runtime.settings, "runtime_thread_lock_ttl_seconds", 300.0) or 300.0
            ),
            1.0,
        )

    def _thread_turn_lock_heartbeat_seconds(self) -> float:
        ttl_seconds = self._thread_turn_lock_ttl_seconds()
        configured_seconds = float(
            getattr(self.runtime.settings, "runtime_thread_lock_heartbeat_seconds", 30.0) or 30.0
        )
        return max(min(ttl_seconds / 3.0, configured_seconds), 0.001)

    def _submit_background_work(
        self, *, key: str, func, delay_seconds: float = 0.0, **kwargs: Any
    ) -> bool:
        if self._background_work is None:
            from ..background_work import BoundedBackgroundQueue

            settings = self.runtime.settings
            self._background_work = BoundedBackgroundQueue(
                name="chat",
                max_concurrency=getattr(settings, "background_worker_max_concurrency", 2),
                max_size=getattr(settings, "background_queue_max_size", 1000),
                job_deduper=self._coordination_backend.job_deduper,
            )
        return self._background_work.submit(
            key=key,
            func=func,
            delay_seconds=delay_seconds,
            **kwargs,
        )

    def _release_background_job_key(self, key: str) -> None:
        if has_repo_method(self._background_work, "release_job_key"):
            self._background_work.release_job_key(key)
            return
        self._coordination_backend.job_deduper.release_job_key(key)

    def _durable_background_execution_enabled(self) -> bool:
        return (
            str(getattr(self.runtime.settings, "background_job_execution", "best_effort"))
            .strip()
            .lower()
            == "durable"
        )

    def _enqueue_durable_background_job(
        self,
        *,
        kind: str,
        key: str,
        payload: dict[str, Any],
        delay_seconds: float = 0.0,
        max_attempts: int = 3,
        dedupe_policy: str = "replace",
    ) -> bool | None:
        if not self._durable_background_execution_enabled():
            return None
        if not has_repo_method(self._coordination_backend.job_deduper, "enqueue_job"):
            return None
        try:
            return bool(
                self._coordination_backend.job_deduper.enqueue_job(
                    BackgroundJobSpec(
                        kind=kind,
                        key=key,
                        payload=payload,
                        run_at=utc_now() + timedelta(seconds=max(float(delay_seconds or 0.0), 0.0)),
                        max_attempts=max_attempts,
                        dedupe_policy=dedupe_policy,
                    )
                )
            )
        except Exception:  # noqa: BLE001 - post-turn scheduling must not fail the completed turn
            logger.warning(
                "failed to enqueue durable background job; falling back to best-effort scheduling",
                extra={"job_key": key, "job_kind": kind},
                exc_info=True,
            )
            return None

    def _schedule_post_turn_branch_decision(
        self,
        *,
        thread_id: str,
        user_id: str,
        root_thread_id: str,
        request_id: str | None,
        trace_id: str | None,
    ) -> None:
        branch_decision_service = getattr(self.runtime, "branch_decision_service", None)
        if branch_decision_service is None:
            return
        config = getattr(branch_decision_service, "config", lambda: None)()
        if config is None or not bool(getattr(config, "enabled", False)):
            return
        job_key = background_job_key(kind="branch_decision_evaluate", thread_id=thread_id)
        payload = {
            "thread_id": thread_id,
            "user_id": user_id,
            "root_thread_id": root_thread_id,
            "request_id": request_id,
            "trace_id": trace_id,
        }
        durable_enqueued = self._enqueue_durable_background_job(
            kind="branch_decision_evaluate",
            key=job_key,
            payload=payload,
            delay_seconds=0.05,
            max_attempts=3,
            dedupe_policy="replace",
        )
        if durable_enqueued is not None:
            return
        handler = getattr(branch_decision_service, "evaluate_thread_turn", None)
        if not callable(handler):
            return
        self._submit_background_work(
            key=job_key,
            func=handler,
            delay_seconds=0.05,
            **payload,
        )

    @staticmethod
    def _message_content_to_text(content: Any) -> str:
        return message_content_to_text(content)

    def _latest_final_ai_text(self, messages: list[Any]) -> str | None:
        return latest_final_ai_text(messages, message_content_to_text=self._message_content_to_text)

    def _serialize_message(self, message: Any) -> dict[str, Any]:
        return serialize_message(message)

    def _thread_state_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        return thread_state_messages(messages, limit=self._THREAD_STATE_MESSAGE_LIMIT)

    def _normalize_result(self, result: Any) -> tuple[dict[str, Any], list[Any]]:
        if hasattr(result, "value") and hasattr(result, "interrupts"):
            return dict(result.value or {}), list(result.interrupts or [])
        if isinstance(result, dict):
            return result, []
        return {"result": result}, []

    def _response_payload(
        self,
        *,
        thread_id: str,
        user_id: str,
        context: RequestContext,
        branch_meta: BranchMeta | None,
        interrupts: list[Any],
        trace_correlation: TraceCorrelation | None = None,
        strict_state_read: bool = False,
    ) -> dict[str, Any]:
        values = self._safe_get_values(thread_id, strict=strict_state_read)
        payload = response_payload(
            thread_id=thread_id,
            user_id=user_id,
            context=context,
            branch_meta=branch_meta,
            interrupts=interrupts,
            values=values,
            settings=self.runtime.settings,
            context_usage=self._context_usage_payload(values),
            message_content_to_text=self._message_content_to_text,
            message_limit=self._THREAD_STATE_MESSAGE_LIMIT,
            trace_correlation=trace_correlation,
        )
        payload["active_skills"] = self._active_skill_metadata(
            payload.get("active_skill_ids", [])
        )
        branch_decision_service = getattr(self.runtime, "branch_decision_service", None)
        if branch_decision_service is not None and hasattr(
            branch_decision_service, "summary_for_thread"
        ):
            try:
                payload["branch_decision_summary"] = branch_decision_service.summary_for_thread(
                    thread_id=thread_id,
                    user_id=user_id,
                ).model_dump(mode="json")
            except Exception:  # noqa: BLE001 - thread state should remain available without autonomy evidence.
                logger.debug("failed to attach branch decision summary", exc_info=True)
                payload["branch_decision_summary"] = None
        else:
            payload["branch_decision_summary"] = None
        return payload

    def _effective_thinking_mode(self, *, model_id: str, thinking_mode: Any) -> str:
        return effective_thinking_mode(
            model_id=model_id,
            thinking_mode=thinking_mode,
            settings=self.runtime.settings,
        )

    def _active_skill_metadata(self, skill_ids: Any) -> list[dict[str, Any]]:
        registry = getattr(self.runtime, "skill_registry", None)
        resolve = getattr(registry, "resolve", None)
        is_skill_enabled = getattr(registry, "is_skill_enabled", None)
        active_skills: list[dict[str, Any]] = []
        seen: set[str] = set()
        raw_skill_ids = [skill_ids] if isinstance(skill_ids, str) else list(skill_ids or [])
        for raw_skill_id in raw_skill_ids:
            skill_id = str(raw_skill_id or "").strip()
            if not skill_id or skill_id in seen:
                continue
            seen.add(skill_id)
            skill = resolve(skill_id) if callable(resolve) else None
            enabled = (
                bool(is_skill_enabled(skill_id))
                if callable(is_skill_enabled)
                else True
            )
            if skill is None:
                active_skills.append(
                    {
                        "skill_id": skill_id,
                        "name": skill_id,
                        "description": "",
                        "enabled": enabled,
                        "triggers": [],
                        "aliases": [],
                        "primary_tools": [],
                        "recommended_tools": [],
                        "prompt_mode": None,
                        "source_id": "",
                        "source_type": "",
                        "version": None,
                        "trust_level": "",
                        "install_state": "",
                    }
                )
                continue
            prompt_mode = getattr(skill, "prompt_mode", None)
            active_skills.append(
                {
                    "skill_id": str(getattr(skill, "skill_id", skill_id)),
                    "name": str(getattr(skill, "skill_id", skill_id)),
                    "description": str(getattr(skill, "description", "") or ""),
                    "enabled": enabled,
                    "triggers": list(getattr(skill, "triggers", ()) or ()),
                    "aliases": list(getattr(skill, "aliases", ()) or ()),
                    "primary_tools": list(getattr(skill, "primary_tools", ()) or ()),
                    "recommended_tools": list(getattr(skill, "recommended_tools", ()) or ()),
                    "prompt_mode": getattr(prompt_mode, "value", prompt_mode),
                    "source_id": str(getattr(skill, "source_id", "") or ""),
                    "source_type": str(getattr(skill, "source_type", "") or ""),
                    "version": getattr(skill, "version", None),
                    "trust_level": str(getattr(skill, "trust_level", "") or ""),
                    "install_state": str(getattr(skill, "install_state", "") or ""),
                }
            )
        return active_skills

    @staticmethod
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

    @staticmethod
    def _skill_selection_metadata(
        *,
        selection: SkillSelection,
        active_skills: list[dict[str, Any]],
        active_skill_ids: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        prompt_mode = selection.prompt_mode
        metadata_skill_ids = (
            list(active_skill_ids)
            if active_skill_ids is not None
            else list(selection.skill_ids)
        )
        return {
            "active_skill_ids": metadata_skill_ids,
            "active_skills": active_skills,
            "skill_selection": {
                "selection_source": selection.selection_source,
                "matched_triggers": list(selection.matched_triggers),
                "confidence": selection.confidence,
                "rationale": selection.rationale,
                "prompt_mode": getattr(prompt_mode, "value", prompt_mode),
            },
        }

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
        kind: str = "chat.turn",
    ) -> dict[str, Any]:
        from ..thread_turn_lease import ThreadTurnLeaseLost

        context, branch_meta, initial_values = self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            explicit_skill_hints=context_skill_hints,
            require_writable=True,
        )
        initial_message_count = len(list(initial_values.get("messages", []) or []))
        initial_llm_calls = int(initial_values.get("llm_calls") or 0)
        started_at = utc_now()
        trace_correlation: TraceCorrelation | None = None
        pending_branch_name_refresh: dict[str, Any] | None = None
        response: dict[str, Any] | None = None
        with self._thread_turn_lease(thread_id=thread_id) as turn_lease:
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
                        version="v2",
                    )
                turn_lease.raise_if_lost()
                _, interrupts = self._normalize_result(result)
                latest_context, latest_branch_meta, final_values = self._context_for_thread(
                    thread_id=thread_id, user_id=user_id
                )
                response = self._response_payload(
                    thread_id=thread_id,
                    user_id=user_id,
                    context=latest_context,
                    branch_meta=latest_branch_meta,
                    interrupts=interrupts,
                    trace_correlation=trace_correlation,
                )
                turn_lease.raise_if_lost()
                self._record_turn_trajectory_best_effort(
                    thread_id=thread_id,
                    user_id=user_id,
                    root_thread_id=latest_context.root_thread_id,
                    kind=kind,
                    status="succeeded",
                    final_values=final_values,
                    initial_message_count=initial_message_count,
                    initial_llm_calls=initial_llm_calls,
                    started_at=started_at,
                    finished_at=utc_now(),
                    branch_meta=latest_branch_meta,
                    trace_correlation=trace_correlation,
                    input_messages=list(
                        payload.get("messages", []) if isinstance(payload, dict) else []
                    ),
                    answer=response.get("assistant_message"),
                )
                turn_lease.raise_if_lost()
                self._schedule_post_turn_context_compaction(
                    thread_id=thread_id,
                    user_id=user_id,
                    kind=kind,
                )
                turn_lease.raise_if_lost()
                self._schedule_post_turn_branch_decision(
                    thread_id=thread_id,
                    user_id=user_id,
                    root_thread_id=latest_context.root_thread_id,
                    request_id=request_id,
                    trace_id=trace_correlation.trace_id if trace_correlation is not None else None,
                )
                turn_lease.raise_if_lost()
                pending_branch_name_refresh = {
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "branch_meta": latest_branch_meta,
                    "kind": kind,
                }
            except Exception as exc:
                if not isinstance(exc, ThreadTurnLeaseLost):
                    self._record_turn_trajectory_best_effort(
                        thread_id=thread_id,
                        user_id=user_id,
                        root_thread_id=context.root_thread_id,
                        kind=kind,
                        status="failed",
                        final_values=self._safe_get_values(thread_id),
                        initial_message_count=initial_message_count,
                        initial_llm_calls=initial_llm_calls,
                        started_at=started_at,
                        finished_at=utc_now(),
                        branch_meta=branch_meta,
                        trace_correlation=trace_correlation,
                        input_messages=list(
                            payload.get("messages", []) if isinstance(payload, dict) else []
                        ),
                        error=str(exc),
                    )
                raise
        if pending_branch_name_refresh is not None:
            self._schedule_branch_name_refresh_after_first_turn(**pending_branch_name_refresh)
        if response is None:
            raise RuntimeError("chat turn completed without a response payload")
        return response

    def _handle_branch_recommendation_turn(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        request_id: str | None,
    ) -> dict[str, Any] | None:
        branch_decision_service = getattr(self.runtime, "branch_decision_service", None)
        if branch_decision_service is None:
            return None
        recommendation_config = getattr(branch_decision_service, "recommendation_config", None)
        if not callable(recommendation_config):
            return None
        config = recommendation_config()
        if config is None or not bool(getattr(config, "enabled", False)):
            return None
        context, _branch_meta, _values = self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            require_writable=True,
        )
        handler = getattr(
            branch_decision_service,
            "evaluate_pre_turn_recommendation",
            None,
        ) or getattr(branch_decision_service, "recommend_for_message", None)
        if not callable(handler):
            return None
        try:
            decision = handler(
                thread_id=thread_id,
                user_id=user_id,
                message=message,
                root_thread_id=context.root_thread_id,
                request_id=request_id,
            )
        except Exception:  # noqa: BLE001 - recommendation must never block a normal turn.
            logger.warning("pre-turn branch recommendation failed", exc_info=True)
            return None
        if not isinstance(decision, dict):
            return None
        promoted_action_id = str(decision.get("promoted_action_id") or "")
        if decision.get("status") != "promoted" or not promoted_action_id:
            return None
        values = self._safe_get_values(thread_id)
        action = latest_pending_branch_action(values.get("branch_actions"))
        needs_branch_action_rewrite = False
        if action is None or action.action_id != promoted_action_id:
            metadata = decision.get("metadata") if isinstance(decision.get("metadata"), dict) else {}
            action_payload = metadata.get("branch_action") if isinstance(metadata, dict) else None
            actions_from_decision = normalize_branch_actions([action_payload])
            action = actions_from_decision[0] if actions_from_decision else None
            if action is None or action.action_id != promoted_action_id:
                return None
            needs_branch_action_rewrite = True
        assistant_text = proposal_message(
            action,
            is_chinese=self._is_chinese_text(message),
        )
        if not has_repo_method(self.runtime.graph, "update_state"):
            return None
        update_values: dict[str, Any] = {
            "messages": [HumanMessage(content=message), AIMessage(content=assistant_text)]
        }
        existing_actions = normalize_branch_actions(values.get("branch_actions"))
        if not any(existing.action_id == action.action_id for existing in existing_actions):
            needs_branch_action_rewrite = True
            existing_actions = [*existing_actions, action]
        if needs_branch_action_rewrite:
            update_values["branch_actions"] = serialize_branch_actions(existing_actions)
            metadata = decision.get("metadata") if isinstance(decision.get("metadata"), dict) else {}
            audit = metadata.get("branch_action_audit") if isinstance(metadata, dict) else None
            current_audit = [
                item
                for item in list(values.get("branch_action_audit") or [])
                if isinstance(item, dict)
            ]
            if isinstance(audit, dict) and not any(
                item.get("action_id") == audit.get("action_id")
                and item.get("decision") == audit.get("decision")
                for item in current_audit
            ):
                update_values["branch_action_audit"] = [*current_audit, audit]
        self.runtime.graph.update_state(
            {"configurable": {"thread_id": thread_id}},
            update_values,
            as_node="bootstrap_turn",
        )
        latest_context, latest_branch_meta, _ = self._context_for_thread(
            thread_id=thread_id,
            user_id=user_id,
        )
        thread_state = self._response_payload(
            thread_id=thread_id,
            user_id=user_id,
            context=latest_context,
            branch_meta=latest_branch_meta,
            interrupts=self._safe_get_interrupts(thread_id),
            trace_correlation=build_trace_correlation(
                settings=self.runtime.settings,
                request_id=request_id,
            ),
        )
        return {
            "kind": "recommended",
            "message": assistant_text,
            "thread_state": thread_state,
            "branch_action": action.model_dump(mode="json"),
            "branch_decision": decision,
        }

    def _branch_recommendation_turn_enabled(self) -> bool:
        branch_decision_service = getattr(self.runtime, "branch_decision_service", None)
        if branch_decision_service is None:
            return False
        recommendation_config = getattr(branch_decision_service, "recommendation_config", None)
        if not callable(recommendation_config):
            return False
        config = recommendation_config()
        return bool(config is not None and getattr(config, "enabled", False))

    def _handle_branch_recommendation_turn_with_lease(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        request_id: str | None,
    ) -> dict[str, Any] | None:
        if not self._branch_recommendation_turn_enabled():
            return None
        with self._thread_turn_lease(thread_id=thread_id):
            return self._handle_branch_recommendation_turn(
                thread_id=thread_id,
                user_id=user_id,
                message=message,
                request_id=request_id,
            )

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

        branch_recommendation_result = self._handle_branch_recommendation_turn_with_lease(
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            request_id=request_id,
        )
        if branch_recommendation_result is not None:
            return branch_recommendation_result["thread_state"]

        selection = self._select_skills_for_message(
            message=message,
            explicit_skill_hints=skill_hints,
        )
        _, _, current_values = self._preflight_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            require_writable=True,
        )
        active_skill_ids = self._merged_skill_ids(
            selection.skill_ids,
            current_values.get("active_skill_ids", []),
        )
        selected_model = model or self.runtime.settings.model
        active_skills = self._active_skill_metadata(active_skill_ids)
        message_metadata = self._skill_selection_metadata(
            selection=selection,
            active_skills=active_skills,
            active_skill_ids=active_skill_ids,
        )
        payload: dict[str, Any] = {
            "messages": [
                HumanMessage(
                    content=message,
                    response_metadata={"focus_agent": message_metadata},
                )
            ],
            "task_brief": selection.stripped_message or message,
            "active_skill_ids": list(active_skill_ids),
            "selected_model": selected_model,
            "selected_thinking_mode": self._effective_thinking_mode(
                model_id=selected_model,
                thinking_mode=thinking_mode,
            ),
        }
        if selection.prompt_mode is not None:
            payload["prompt_mode"] = selection.prompt_mode
        return self._run_invoke(
            thread_id=thread_id,
            user_id=user_id,
            payload=payload,
            run_name="focus_agent_turn",
            request_id=request_id,
            context_skill_hints=active_skill_ids,
            kind="chat.turn",
        )

    def resume(
        self, *, thread_id: str, user_id: str, resume: Any, request_id: str | None = None
    ) -> dict[str, Any]:
        return self._run_invoke(
            thread_id=thread_id,
            user_id=user_id,
            payload=Command(resume=resume),
            run_name="focus_agent_resume",
            request_id=request_id,
            kind="chat.resume",
        )

    def get_thread_state(
        self, *, thread_id: str, user_id: str, request_id: str | None = None
    ) -> dict[str, Any]:
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
            interrupts=self._safe_get_interrupts(thread_id, strict=True),
            trace_correlation=trace_correlation,
            strict_state_read=True,
        )

    def _select_skills_for_message(
        self,
        *,
        message: str,
        explicit_skill_hints: tuple[str, ...],
    ) -> SkillSelection:
        registry = getattr(self.runtime, "skill_registry", None)
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
        return json_safe(value)

    @staticmethod
    def _sse_frame(*, event: str, data: dict[str, Any]) -> str:
        return sse_frame(event=event, data=data)
