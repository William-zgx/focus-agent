from __future__ import annotations

import logging
from dataclasses import replace
from hashlib import sha256
from typing import Any

from focus_agent.core.branching import (
    BranchMeta,
)
from focus_agent.core.governance import (
    BranchDecisionAction,
    BranchDecisionConfig,
    BranchDecisionEvent,
    BranchDecisionMode,
    BranchDecisionRecommendationTarget,
    BranchDecisionSignal,
    BranchDecisionStatus,
    BranchDecisionSummary,
)
from focus_agent.core.repo_call import has_repo_method
from focus_agent.retrieval.branch_context import (
    BranchContextRetrievalService,
    index_branch_decision_event,
)
from focus_agent.services.branch_actions import (
    branch_handoff_message_from_text,
    infer_suggested_branch_name,
    latest_pending_branch_action,
    target_parent_thread_id,
)

from .scorers import score_branch_decisions, score_branch_recommendation, select_best_score
from .service_helpers import (
    _branch_action_kind_for_decision,
    _branch_decision_mode,
    _branch_handoff_idempotency_key,
    _decision_action_for_branch_action_kind,
    _message_preview,
    _normalized_message_hash,
    _now_iso,
    _recommendation_diagnostics,
    _recommendation_target_for_decision,
    _recommendation_user_visible,
    _semantic_topic_relation_diagnostic,
    _semantic_topic_relation_metadata,
    _should_run_semantic_topic_relation,
)
from .service_runtime import BranchDecisionServiceRuntimeMixin
from .signals import collect_branch_decision_signals, collect_branch_recommendation_signals

logger = logging.getLogger("focus_agent.branch_decision")


class BranchDecisionService(BranchDecisionServiceRuntimeMixin):
    def __init__(
        self,
        *,
        settings: Any,
        graph: Any,
        governance_repository: Any,
        branch_service: Any | None = None,
        coordination_backend: Any | None = None,
        retrieval_index: Any | None = None,
        memory_embedding_provider: Any | None = None,
    ) -> None:
        self.settings = settings
        self.graph = graph
        self.governance_repository = governance_repository
        self.branch_service = branch_service
        self.coordination_backend = coordination_backend
        self.retrieval_index = retrieval_index
        self.memory_embedding_provider = memory_embedding_provider

    def config(self) -> BranchDecisionConfig:
        mode = _branch_decision_mode(getattr(self.settings, "agent_branch_decision_mode", "shadow"))
        recommendation_mode = _branch_decision_mode(
            getattr(self.settings, "agent_branch_recommendation_mode", "shadow")
        )
        recommendation_enabled = bool(
            getattr(self.settings, "agent_branch_recommendation_enabled", False)
        )
        recommendation_semantic_enabled = bool(
            getattr(self.settings, "agent_branch_recommendation_semantic_enabled", False)
        )
        recommendation_semantic_model = getattr(
            self.settings,
            "agent_branch_recommendation_semantic_model",
            None,
        )
        return BranchDecisionConfig(
            enabled=bool(getattr(self.settings, "agent_branch_decision_enabled", False)),
            mode=mode,
            min_confidence=float(
                getattr(self.settings, "agent_branch_decision_min_confidence", 0.70)
            ),
            split_threshold=float(
                getattr(self.settings, "agent_branch_decision_split_threshold", 0.65)
            ),
            conclude_threshold=float(
                getattr(self.settings, "agent_branch_decision_conclude_threshold", 0.70)
            ),
            merge_candidate_threshold=float(
                getattr(self.settings, "agent_branch_decision_merge_candidate_threshold", 0.75)
            ),
            rate_limit_per_hour=int(
                getattr(self.settings, "agent_branch_decision_rate_limit_per_hour", 3)
            ),
            recommendation_enabled=recommendation_enabled,
            recommendation_mode=recommendation_mode,
            recommendation_min_confidence=float(
                getattr(self.settings, "agent_branch_recommendation_min_confidence", 0.72)
            ),
            recommendation_semantic_enabled=recommendation_semantic_enabled,
            recommendation_semantic_model=recommendation_semantic_model,
            recommendation_user_visible=_recommendation_user_visible(
                enabled=recommendation_enabled,
                mode=recommendation_mode,
            ),
            recommendation_diagnostics=_recommendation_diagnostics(
                enabled=recommendation_enabled,
                mode=recommendation_mode,
                semantic_enabled=recommendation_semantic_enabled,
                semantic_model=recommendation_semantic_model,
            ),
        )

    def recommendation_config(self) -> BranchDecisionConfig:
        mode = _branch_decision_mode(
            getattr(self.settings, "agent_branch_recommendation_mode", "shadow")
        )
        enabled = bool(getattr(self.settings, "agent_branch_recommendation_enabled", False))
        semantic_enabled = bool(
            getattr(self.settings, "agent_branch_recommendation_semantic_enabled", False)
        )
        semantic_model = getattr(
            self.settings,
            "agent_branch_recommendation_semantic_model",
            None,
        )
        return BranchDecisionConfig(
            enabled=enabled,
            mode=mode,
            min_confidence=float(
                getattr(self.settings, "agent_branch_recommendation_min_confidence", 0.72)
            ),
            recommendation_enabled=enabled,
            recommendation_mode=mode,
            recommendation_min_confidence=float(
                getattr(self.settings, "agent_branch_recommendation_min_confidence", 0.72)
            ),
            recommendation_semantic_enabled=semantic_enabled,
            recommendation_semantic_model=semantic_model,
            recommendation_user_visible=_recommendation_user_visible(
                enabled=enabled,
                mode=mode,
            ),
            recommendation_diagnostics=_recommendation_diagnostics(
                enabled=enabled,
                mode=mode,
                semantic_enabled=semantic_enabled,
                semantic_model=semantic_model,
            ),
        )

    def recommend_for_message(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        root_thread_id: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any] | None:
        config = self.recommendation_config()
        if not config.enabled:
            return None
        values = self._safe_get_values(thread_id)
        resolution = self._thread_resolution(thread_id=thread_id, user_id=user_id)
        branch_meta = self._branch_meta_for_thread(thread_id=thread_id, values=values)
        resolved_root_thread_id = root_thread_id or resolution.root_thread_id
        message_hash = sha256(str(message or "").encode("utf-8")).hexdigest()[:16]
        idempotency_key = f"pre_turn:{thread_id}:{request_id or trace_id or message_hash}"
        try:
            event = self._evaluate_pre_turn_recommendation(
                config=config,
                values=values,
                branch_meta=branch_meta,
                thread_id=thread_id,
                root_thread_id=resolved_root_thread_id,
                user_id=user_id,
                message=message,
                request_id=request_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # noqa: BLE001 - recommendation failures are audit evidence.
            logger.warning("branch recommendation evaluation failed", exc_info=True)
            event = BranchDecisionEvent(
                user_id=user_id,
                root_thread_id=resolved_root_thread_id,
                source_thread_id=thread_id,
                branch_id=branch_meta.branch_id
                if branch_meta is not None
                else resolution.branch_id,
                recommendation_target=BranchDecisionRecommendationTarget.CONTINUE_CURRENT,
                confidence=0.0,
                action=BranchDecisionAction.CONTINUE_CURRENT,
                status=BranchDecisionStatus.ERROR,
                mode=config.mode,
                rationale="Branch recommendation evaluation failed.",
                idempotency_key=idempotency_key,
                request_id=request_id,
                trace_id=trace_id,
                error=str(exc),
                metadata={"phase": "pre_turn"},
            )
            event = self._save_event(event)
        return event.model_dump(mode="json")

    def evaluate_pre_turn_recommendation(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str,
        root_thread_id: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any] | None:
        return self.recommend_for_message(
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            root_thread_id=root_thread_id,
            request_id=request_id,
            trace_id=trace_id,
        )

    def record_branch_handoff_auto_run_decision(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str | None = None,
        root_thread_id: str | None = None,
        handoff_run_id: str | None = None,
        handoff_run_status: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> BranchDecisionEvent:
        config = self.recommendation_config()
        values = self._safe_get_values(thread_id)
        resolution = self._thread_resolution(thread_id=thread_id, user_id=user_id)
        branch_meta = self._branch_meta_for_thread(thread_id=thread_id, values=values)
        resolved_root_thread_id = root_thread_id or resolution.root_thread_id
        message_preview = _message_preview(message)
        metadata: dict[str, Any] = {
            "source": "branch_handoff",
            "branch_handoff_auto_run": True,
            "handoff_run_id": str(handoff_run_id).strip() if handoff_run_id else None,
            "handoff_run_status": str(handoff_run_status).strip()
            if handoff_run_status
            else None,
            "handoff_message_preview": message_preview,
            "message_hash": _normalized_message_hash(message),
            "reason": "branch_handoff_auto_run",
        }
        event = BranchDecisionEvent(
            user_id=user_id,
            root_thread_id=resolved_root_thread_id,
            source_thread_id=thread_id,
            branch_id=branch_meta.branch_id if branch_meta is not None else resolution.branch_id,
            recommendation_target=BranchDecisionRecommendationTarget.CONTINUE_CURRENT,
            action=BranchDecisionAction.CONTINUE_CURRENT,
            status=BranchDecisionStatus.SKIPPED,
            mode=config.mode,
            score=0.0,
            confidence=0.0,
            threshold=config.min_confidence,
            signals=[
                BranchDecisionSignal(
                    name="branch_handoff_context",
                    value={
                        "branch_handoff_auto_run": True,
                        "handoff_run_id": metadata["handoff_run_id"],
                        "handoff_run_status": metadata["handoff_run_status"],
                        "message_preview": message_preview,
                    },
                    rationale="Automatic branch handoff run continues in the target thread.",
                )
            ],
            rationale="Automatic branch handoff run continues in the target thread.",
            idempotency_key=_branch_handoff_idempotency_key(
                thread_id=thread_id,
                message=message,
            ),
            request_id=request_id,
            trace_id=trace_id,
            metadata=metadata,
        )
        return self._save_event(event)

    def update_branch_handoff_auto_run_outcome(
        self,
        *,
        decision_id: str,
        handoff_run_status: str,
        handoff_run_id: str | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> BranchDecisionEvent:
        event = self._require_event(decision_id)
        metadata = {
            **event.metadata,
            "source": event.metadata.get("source") or "branch_handoff",
            "handoff_run_status": str(handoff_run_status).strip(),
        }
        if handoff_run_id is not None:
            metadata["handoff_run_id"] = str(handoff_run_id).strip()
        if message is not None:
            metadata["handoff_message_preview"] = _message_preview(message)
        return self._update_event(
            event,
            error=str(error).strip() or None if error is not None else event.error,
            metadata=metadata,
            executed_at=_now_iso(),
        )

    def record_branch_handoff_decision(
        self,
        *,
        thread_id: str,
        user_id: str,
        message: str | None = None,
        root_thread_id: str | None = None,
        run_id: str | None = None,
        run_status: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> BranchDecisionEvent:
        return self.record_branch_handoff_auto_run_decision(
            thread_id=thread_id,
            user_id=user_id,
            message=message,
            root_thread_id=root_thread_id,
            handoff_run_id=run_id,
            handoff_run_status=run_status,
            request_id=request_id,
            trace_id=trace_id,
        )

    def mark_branch_handoff_decision_outcome(
        self,
        *,
        decision_id: str,
        run_status: str,
        run_id: str | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> BranchDecisionEvent:
        return self.update_branch_handoff_auto_run_outcome(
            decision_id=decision_id,
            handoff_run_id=run_id,
            handoff_run_status=run_status,
            message=message,
            error=error,
        )

    def evaluate_thread_turn(
        self,
        *,
        thread_id: str,
        user_id: str,
        root_thread_id: str | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any] | None:
        config = self.config()
        if not config.enabled:
            return None
        values = self._safe_get_values(thread_id)
        resolution = self._thread_resolution(thread_id=thread_id, user_id=user_id)
        branch_meta = self._branch_meta_for_thread(thread_id=thread_id, values=values)
        resolved_root_thread_id = root_thread_id or resolution.root_thread_id
        idempotency_key = (
            f"{thread_id}:{request_id or trace_id or len(values.get('messages') or [])}"
        )
        try:
            event = self._evaluate(
                config=config,
                values=values,
                branch_meta=branch_meta,
                thread_id=thread_id,
                root_thread_id=resolved_root_thread_id,
                user_id=user_id,
                request_id=request_id,
                trace_id=trace_id,
                idempotency_key=idempotency_key,
            )
        except Exception as exc:  # noqa: BLE001 - background evaluation records failure evidence.
            logger.warning("branch decision evaluation failed", exc_info=True)
            event = BranchDecisionEvent(
                user_id=user_id,
                root_thread_id=resolved_root_thread_id,
                source_thread_id=thread_id,
                branch_id=branch_meta.branch_id
                if branch_meta is not None
                else resolution.branch_id,
                confidence=0.0,
                action=BranchDecisionAction.SPLIT,
                status=BranchDecisionStatus.ERROR,
                mode=config.mode,
                rationale="Branch decision evaluation failed.",
                idempotency_key=idempotency_key,
                request_id=request_id,
                trace_id=trace_id,
                error=str(exc),
            )
            event = self._save_event(event)
        return event.model_dump(mode="json")

    def list_decisions(
        self,
        *,
        thread_id: str,
        user_id: str,
        status: str | None = None,
        action: str | None = None,
        limit: int = 50,
    ) -> list[BranchDecisionEvent]:
        self._assert_thread_owner(thread_id=thread_id, user_id=user_id)
        return self.governance_repository.list_branch_decision_events(
            user_id=user_id,
            source_thread_id=thread_id,
            status=status,
            action=action,
            limit=limit,
        )

    def summary_for_thread(self, *, thread_id: str, user_id: str) -> BranchDecisionSummary:
        if not has_repo_method(self.governance_repository, "list_branch_decision_events"):
            return BranchDecisionSummary()
        events = self.governance_repository.list_branch_decision_events(
            user_id=user_id,
            source_thread_id=thread_id,
            limit=20,
        )
        latest = events[0] if events else None
        dismissed_count = sum(1 for item in events if item.status == BranchDecisionStatus.DISMISSED)
        pending_action_id = (
            latest.promoted_action_id
            if latest and latest.status == BranchDecisionStatus.PROMOTED
            else None
        )
        return BranchDecisionSummary(
            latest_decision=latest,
            actionable=bool(latest and latest.can_promote),
            pending_action_id=pending_action_id,
            dismissed_count=dismissed_count,
        )

    def promote_decision(
        self,
        *,
        thread_id: str,
        decision_id: str,
        user_id: str,
        request_id: str | None = None,
    ) -> BranchDecisionEvent:
        self._assert_thread_owner(thread_id=thread_id, user_id=user_id)
        event = self._require_event(decision_id)
        if event.source_thread_id != thread_id:
            raise PermissionError("Branch decision does not belong to this thread.")
        if event.user_id not in {None, user_id}:
            raise PermissionError("Branch decision is not owned by this user.")
        if event.status == BranchDecisionStatus.DISMISSED:
            raise ValueError("Dismissed branch decisions cannot be promoted.")
        if event.promoted_action_id:
            return event
        if event.action not in {
            BranchDecisionAction.SPLIT,
            BranchDecisionAction.FORK_CHILD_BRANCH,
            BranchDecisionAction.FORK_SIBLING_BRANCH,
        }:
            updated = self._update_event(
                event,
                status=BranchDecisionStatus.BLOCKED,
                error="Only branch fork decisions can be promoted to a branch action.",
                metadata={**event.metadata, "reason": "unsupported_promotion_action"},
            )
            return updated
        return self._promote_branch_action_decision(
            event,
            user_id=user_id,
            request_id=request_id,
        )

    def dismiss_decision(
        self,
        *,
        thread_id: str,
        decision_id: str,
        user_id: str,
        reason: str | None = None,
    ) -> BranchDecisionEvent:
        self._assert_thread_owner(thread_id=thread_id, user_id=user_id)
        event = self._require_event(decision_id)
        if event.source_thread_id != thread_id:
            raise PermissionError("Branch decision does not belong to this thread.")
        if event.user_id not in {None, user_id}:
            raise PermissionError("Branch decision is not owned by this user.")
        return self._update_event(
            event,
            status=BranchDecisionStatus.DISMISSED,
            dismiss_reason=reason or "user_dismissed",
            executed_at=_now_iso(),
        )

    def _evaluate(
        self,
        *,
        config: BranchDecisionConfig,
        values: dict[str, Any],
        branch_meta: BranchMeta | None,
        thread_id: str,
        root_thread_id: str,
        user_id: str,
        request_id: str | None,
        trace_id: str | None,
        idempotency_key: str,
    ) -> BranchDecisionEvent:
        signals = collect_branch_decision_signals(values=values, branch_meta=branch_meta)
        best = select_best_score(
            score_branch_decisions(
                signals=signals,
                branch_meta=branch_meta,
                split_threshold=config.split_threshold,
                conclude_threshold=config.conclude_threshold,
                merge_candidate_threshold=config.merge_candidate_threshold,
            )
        )
        status, gate_reason = self._gate_status(
            config=config,
            values=values,
            branch_meta=branch_meta,
            score=best.score,
            threshold=best.threshold,
            user_id=user_id,
            thread_id=thread_id,
        )
        metadata: dict[str, Any] = {}
        if status in {
            BranchDecisionStatus.BLOCKED,
            BranchDecisionStatus.SKIPPED,
            BranchDecisionStatus.SHADOWED,
        }:
            metadata["reason"] = gate_reason
        if status == BranchDecisionStatus.SUGGESTED and config.mode == BranchDecisionMode.EXECUTE:
            metadata["downgraded_from_execute"] = True
            metadata["effective_mode"] = BranchDecisionMode.SUGGEST.value
        event = BranchDecisionEvent(
            user_id=user_id,
            root_thread_id=root_thread_id,
            source_thread_id=thread_id,
            branch_id=branch_meta.branch_id if branch_meta is not None else None,
            action=best.action,
            status=status,
            mode=config.mode,
            score=best.score,
            confidence=best.score,
            threshold=best.threshold,
            signals=signals,
            rationale=best.rationale,
            idempotency_key=idempotency_key,
            request_id=request_id,
            trace_id=trace_id,
            metadata=metadata,
        )
        event = self._save_event(event)
        if (
            event.status == BranchDecisionStatus.SUGGESTED
            and event.action == BranchDecisionAction.SPLIT
        ):
            event = self._promote_branch_action_decision(
                event,
                user_id=user_id,
                request_id=request_id,
            )
        elif event.status == BranchDecisionStatus.SUGGESTED and event.action in {
            BranchDecisionAction.CONCLUDE,
            BranchDecisionAction.MERGE_CANDIDATE,
        }:
            event = self._prepare_merge_proposal_for_event(event, user_id=user_id)
        return event

    def _evaluate_pre_turn_recommendation(
        self,
        *,
        config: BranchDecisionConfig,
        values: dict[str, Any],
        branch_meta: BranchMeta | None,
        thread_id: str,
        root_thread_id: str,
        user_id: str,
        message: str,
        request_id: str | None,
        trace_id: str | None,
        idempotency_key: str,
    ) -> BranchDecisionEvent:
        signals = collect_branch_recommendation_signals(
            message=message,
            values=values,
            branch_meta=branch_meta,
        )
        best = score_branch_recommendation(
            signals=signals,
            min_confidence=config.min_confidence,
        )
        if _should_run_semantic_topic_relation(signals=signals, action=best.action):
            semantic_topic_relation = self._classify_semantic_topic_relation(
                message=message,
                values=values,
                branch_meta=branch_meta,
            )
            signals = collect_branch_recommendation_signals(
                message=message,
                values=values,
                branch_meta=branch_meta,
                semantic_topic_relation=semantic_topic_relation,
            )
            best = score_branch_recommendation(
                signals=signals,
                min_confidence=config.min_confidence,
            )
        signals = [
            *signals,
            *self._zvec_branch_context_shadow_signals(
                message=message,
                user_id=user_id,
                root_thread_id=root_thread_id,
            ),
        ]
        action = best.action
        target_parent: str | None = None
        suggested_branch_name: str | None = None
        if action in {
            BranchDecisionAction.FORK_CHILD_BRANCH,
            BranchDecisionAction.FORK_SIBLING_BRANCH,
        }:
            handoff_message = branch_handoff_message_from_text(message) or str(
                message or ""
            ).strip()
            requested_kind = _branch_action_kind_for_decision(action)
            resolved_kind, target_parent = target_parent_thread_id(
                source_thread_id=thread_id,
                branch_meta=branch_meta,
                kind=requested_kind,
            )
            action = _decision_action_for_branch_action_kind(resolved_kind)
            suggested_branch_name = infer_suggested_branch_name(
                message,
                list(values.get("messages", []) or []),
            )
            pending_action = latest_pending_branch_action(values.get("branch_actions"))
            if pending_action is not None and self._can_replace_pending_branch_action(
                action=action,
                pending_action=pending_action,
                handoff_message=handoff_message,
            ):
                semantic_diagnostic = _semantic_topic_relation_diagnostic(signals)
                semantic_confidence = float(
                    semantic_diagnostic.get("semantic_confidence") or 0.0
                )
                best = replace(
                    best,
                    score=max(best.score, semantic_confidence),
                    rationale=f"{best.rationale}, replacing stale pending branch action.",
                )
        else:
            handoff_message = branch_handoff_message_from_text(message) or str(
                message or ""
            ).strip()
        recommendation_target = _recommendation_target_for_decision(action)
        status, gate_reason = self._gate_recommendation_status(
            config=config,
            values={
                **values,
                "_branch_decision_handoff_message": handoff_message,
            },
            branch_meta=branch_meta,
            action=action,
            score=best.score,
            threshold=best.threshold,
        )
        metadata: dict[str, Any] = {
            "phase": "pre_turn",
            "recommendation_target": recommendation_target.value,
            "message_hash": sha256(str(message or "").encode("utf-8")).hexdigest()[:16],
            **_semantic_topic_relation_metadata(signals),
            "recommendation_user_visible": _recommendation_user_visible(
                enabled=config.enabled,
                mode=config.mode,
            )
            and status == BranchDecisionStatus.SUGGESTED,
            "diagnostic": {
                "gate_reason": gate_reason,
                "mode": config.mode.value,
                "threshold": max(config.min_confidence, best.threshold),
                **_semantic_topic_relation_diagnostic(signals),
            },
        }
        if status in {
            BranchDecisionStatus.BLOCKED,
            BranchDecisionStatus.SKIPPED,
            BranchDecisionStatus.SHADOWED,
        }:
            metadata["reason"] = gate_reason
        if suggested_branch_name:
            metadata["suggested_branch_name"] = suggested_branch_name
        if target_parent:
            metadata["target_parent_thread_id"] = target_parent
        if action in {
            BranchDecisionAction.FORK_CHILD_BRANCH,
            BranchDecisionAction.FORK_SIBLING_BRANCH,
        }:
            handoff_message = branch_handoff_message_from_text(message) or str(
                message or ""
            ).strip()
            metadata["handoff_message"] = handoff_message
            metadata["handoff_message_preview"] = handoff_message[:240]
        if status == BranchDecisionStatus.SUGGESTED and config.mode == BranchDecisionMode.EXECUTE:
            metadata["downgraded_from_execute"] = True
            metadata["effective_mode"] = BranchDecisionMode.SUGGEST.value
        event = BranchDecisionEvent(
            user_id=user_id,
            root_thread_id=root_thread_id,
            source_thread_id=thread_id,
            branch_id=branch_meta.branch_id if branch_meta is not None else None,
            recommendation_target=recommendation_target,
            target_parent_thread_id=target_parent,
            suggested_branch_name=suggested_branch_name,
            action=action,
            status=status,
            mode=config.mode,
            score=best.score,
            confidence=best.score,
            threshold=best.threshold,
            signals=signals,
            rationale=best.rationale,
            idempotency_key=idempotency_key,
            request_id=request_id,
            trace_id=trace_id,
            metadata=metadata,
        )
        event = self._save_event(event)
        if event.status == BranchDecisionStatus.SUGGESTED and event.action in {
            BranchDecisionAction.FORK_CHILD_BRANCH,
            BranchDecisionAction.FORK_SIBLING_BRANCH,
        }:
            event = self._promote_branch_action_decision(
                event,
                user_id=user_id,
                request_id=request_id,
            )
        return event

    def _zvec_branch_context_shadow_signals(
        self,
        *,
        message: str,
        user_id: str | None,
        root_thread_id: str | None,
    ) -> list[BranchDecisionSignal]:
        if self.retrieval_index is None or self.memory_embedding_provider is None:
            return []
        try:
            hits = BranchContextRetrievalService(
                retrieval_index=self.retrieval_index,
                embedding_provider=self.memory_embedding_provider,
                repository=self.governance_repository,
            ).search_similar_context(
                query=message,
                user_id=user_id,
                root_thread_id=root_thread_id,
                limit=3,
            )
        except Exception:  # noqa: BLE001
            return []
        if not hits:
            return []
        return [
            BranchDecisionSignal(
                name="zvec_branch_context",
                value={
                    "mode": "shadow",
                    "hit_count": len(hits),
                    "top_score": hits[0].score,
                    "source_ids": [hit.source_id for hit in hits],
                },
                score=hits[0].score,
                weight=0.0,
                evidence_refs=[hit.source_id for hit in hits],
                rationale="Zvec branch context shadow retrieval.",
            )
        ]

    def _index_branch_decision_best_effort(self, event: BranchDecisionEvent) -> None:
        try:
            index_branch_decision_event(
                retrieval_index=self.retrieval_index,
                embedding_provider=self.memory_embedding_provider,
                event=event,
            )
        except Exception:  # noqa: BLE001
            return


__all__ = ["BranchDecisionService"]
