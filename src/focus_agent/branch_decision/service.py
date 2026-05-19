from __future__ import annotations

import logging
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from typing import Any

from focus_agent.core.branching import (
    BranchActionKind,
    BranchMeta,
    BranchRole,
    BranchStatus,
    ThreadResolution,
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
from focus_agent.core.state import normalize_agent_state
from focus_agent.services.branch_actions import (
    branch_action_audit_event,
    branch_handoff_message_from_text,
    build_branch_action_proposal,
    infer_suggested_branch_name,
    latest_pending_branch_action,
    normalize_branch_actions,
    serialize_branch_actions,
    target_parent_thread_id,
)

from .scorers import score_branch_decisions, score_branch_recommendation, select_best_score
from .signals import collect_branch_decision_signals, collect_branch_recommendation_signals

logger = logging.getLogger("focus_agent.branch_decision")


class BranchDecisionService:
    def __init__(
        self,
        *,
        settings: Any,
        graph: Any,
        governance_repository: Any,
        branch_service: Any | None = None,
        coordination_backend: Any | None = None,
    ) -> None:
        self.settings = settings
        self.graph = graph
        self.governance_repository = governance_repository
        self.branch_service = branch_service
        self.coordination_backend = coordination_backend

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
        action = best.action
        target_parent: str | None = None
        suggested_branch_name: str | None = None
        if action in {
            BranchDecisionAction.FORK_CHILD_BRANCH,
            BranchDecisionAction.FORK_SIBLING_BRANCH,
        }:
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
        recommendation_target = _recommendation_target_for_decision(action)
        status, gate_reason = self._gate_recommendation_status(
            config=config,
            values=values,
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

    def _classify_semantic_topic_relation(
        self,
        *,
        message: str,
        values: dict[str, Any],
        branch_meta: BranchMeta | None,
    ) -> dict[str, Any]:
        classifier = self._semantic_topic_relation_classifier()
        if classifier is None:
            return {
                "status": "unavailable",
                "topic_shift": False,
                "confidence": 0.0,
                "recommended_action": BranchDecisionAction.CONTINUE_CURRENT.value,
                "reason": "No semantic topic relation classifier is configured.",
            }
        try:
            result = _call_semantic_topic_relation_classifier(
                classifier,
                settings=self.settings,
                message=message,
                values=values,
                branch_meta=branch_meta,
            )
        except Exception as exc:  # noqa: BLE001 - semantic recommendation must fail closed.
            logger.warning("semantic topic relation classification failed", exc_info=True)
            return {
                "status": "unavailable",
                "topic_shift": False,
                "confidence": 0.0,
                "recommended_action": BranchDecisionAction.CONTINUE_CURRENT.value,
                "reason": str(exc) or exc.__class__.__name__,
            }
        return _normalize_semantic_topic_relation_result(result)

    def _semantic_topic_relation_classifier(self) -> Any | None:
        for attr in (
            "classify_branch_recommendation_semantic",
            "semantic_branch_recommendation_classifier",
        ):
            classifier = globals().get(attr)
            if classifier is not None:
                return classifier
        for owner in (self.settings, self.branch_service, self.coordination_backend):
            for attr in (
                "agent_branch_recommendation_semantic_classifier",
                "branch_recommendation_semantic_classifier",
                "semantic_topic_relation_classifier",
                "semantic_topic_classifier",
                "classify_branch_recommendation_semantic",
                "semantic_branch_recommendation_classifier",
            ):
                classifier = getattr(owner, attr, None) if owner is not None else None
                if classifier is not None:
                    return classifier
        for module_name in (
            "focus_agent.branch_decision.semantic",
            "focus_agent.branch_decision.semantic_topic_relation",
            "focus_agent.branch_decision.classifier",
        ):
            try:
                module = import_module(module_name)
            except ImportError:
                continue
            for attr in (
                "classify_semantic_topic_relation",
                "classify_topic_relation",
                "semantic_topic_relation_classifier",
                "classify_branch_recommendation_semantic",
                "semantic_branch_recommendation_classifier",
            ):
                classifier = getattr(module, attr, None)
                if classifier is not None:
                    return classifier
        return None

    def _gate_status(
        self,
        *,
        config: BranchDecisionConfig,
        values: dict[str, Any],
        branch_meta: BranchMeta | None,
        score: float,
        threshold: float,
        user_id: str,
        thread_id: str,
    ) -> tuple[BranchDecisionStatus, str]:
        del user_id
        if branch_meta is not None and branch_meta.branch_status in {
            BranchStatus.MERGED,
            BranchStatus.DISCARDED,
            BranchStatus.CLOSED,
        }:
            return BranchDecisionStatus.BLOCKED, "closed_branch"
        if latest_pending_branch_action(values.get("branch_actions")) is not None:
            return BranchDecisionStatus.BLOCKED, "pending_branch_action"
        if score < max(config.min_confidence, threshold):
            return BranchDecisionStatus.SKIPPED, "below_threshold"
        if self._rate_limited(thread_id=thread_id, limit=config.rate_limit_per_hour):
            return BranchDecisionStatus.BLOCKED, "rate_limited"
        if config.mode == BranchDecisionMode.SHADOW:
            return BranchDecisionStatus.SHADOWED, "shadow_mode"
        return BranchDecisionStatus.SUGGESTED, "eligible"

    def _gate_recommendation_status(
        self,
        *,
        config: BranchDecisionConfig,
        values: dict[str, Any],
        branch_meta: BranchMeta | None,
        action: BranchDecisionAction,
        score: float,
        threshold: float,
    ) -> tuple[BranchDecisionStatus, str]:
        if branch_meta is not None and branch_meta.branch_status in {
            BranchStatus.MERGED,
            BranchStatus.DISCARDED,
            BranchStatus.CLOSED,
        }:
            return BranchDecisionStatus.BLOCKED, "closed_branch"
        if (
            action
            in {
                BranchDecisionAction.FORK_CHILD_BRANCH,
                BranchDecisionAction.FORK_SIBLING_BRANCH,
            }
            and latest_pending_branch_action(values.get("branch_actions")) is not None
        ):
            return BranchDecisionStatus.BLOCKED, "pending_branch_action"
        if score < max(config.min_confidence, threshold):
            return BranchDecisionStatus.SKIPPED, "below_threshold"
        if action == BranchDecisionAction.CONTINUE_CURRENT:
            if config.mode == BranchDecisionMode.SHADOW:
                return BranchDecisionStatus.SHADOWED, "shadow_mode"
            return BranchDecisionStatus.SKIPPED, "continue_current"
        if action == BranchDecisionAction.FORK_CHILD_BRANCH and self._child_depth_exceeded(
            branch_meta
        ):
            return BranchDecisionStatus.BLOCKED, "child_depth_exceeded"
        if config.mode == BranchDecisionMode.SHADOW:
            return BranchDecisionStatus.SHADOWED, "shadow_mode"
        return BranchDecisionStatus.SUGGESTED, "eligible"

    def _child_depth_exceeded(self, branch_meta: BranchMeta | None) -> bool:
        try:
            max_depth = int(getattr(self.settings, "branch_max_depth", 5) or 5)
        except (TypeError, ValueError):
            max_depth = 5
        current_depth = int(branch_meta.branch_depth) if branch_meta is not None else 0
        return current_depth + 1 > max(0, max_depth)

    def _rate_limited(self, *, thread_id: str, limit: int) -> bool:
        rate_limiter = getattr(self.coordination_backend, "rate_limiter", None)
        if rate_limiter is None or not has_repo_method(rate_limiter, "check"):
            return False
        result = rate_limiter.check(
            key=f"branch_decision:{thread_id}",
            limit=max(0, int(limit or 0)),
            window_seconds=3600.0,
        )
        return not bool(getattr(result, "allowed", True))

    def _promote_branch_action_decision(
        self,
        event: BranchDecisionEvent,
        *,
        user_id: str,
        request_id: str | None = None,
    ) -> BranchDecisionEvent:
        values = self._safe_get_values(event.source_thread_id)
        actions = normalize_branch_actions(values.get("branch_actions"))
        if latest_pending_branch_action(actions) is not None:
            return self._update_event(
                event,
                status=BranchDecisionStatus.BLOCKED,
                error="A pending branch action already exists.",
                metadata={**event.metadata, "reason": "pending_branch_action"},
            )
        branch_meta = self._branch_meta_from_values(values)
        requested_kind = _branch_action_kind_for_decision(event.action)
        kind, target_thread_id = target_parent_thread_id(
            source_thread_id=event.source_thread_id,
            branch_meta=branch_meta,
            kind=requested_kind,
        )
        if event.target_parent_thread_id:
            target_thread_id = event.target_parent_thread_id
        suggested_branch_name = (
            str(event.suggested_branch_name or "").strip()
            or str(event.metadata.get("suggested_branch_name") or "").strip()
            or "AI suggested branch"
        )
        action = build_branch_action_proposal(
            kind=kind,
            root_thread_id=event.root_thread_id,
            source_thread_id=event.source_thread_id,
            target_parent_thread_id=target_thread_id,
            suggested_branch_name=suggested_branch_name,
            branch_role=_branch_role_for_recommendation(event.recommendation_target),
            reason=event.rationale,
            handoff_message=str(event.metadata.get("handoff_message") or "").strip()
            or str(event.metadata.get("handoff_message_preview") or "").strip()
            or None,
        ).model_copy(
            update={
                "source": "branch_decision",
                "source_decision_id": event.decision_id,
                "confidence": event.score,
                "rationale": event.rationale,
            }
        )
        audit = branch_action_audit_event(
            user_id=user_id,
            thread_id=event.source_thread_id,
            action=action,
            decision="proposed",
            reason="branch_decision_promoted",
            request_id=request_id or event.request_id,
        )
        current_audit = [
            item for item in list(values.get("branch_action_audit") or []) if isinstance(item, dict)
        ]
        if not has_repo_method(self.graph, "update_state"):
            raise RuntimeError("Conversation graph does not support branch action state updates.")
        self.graph.update_state(
            {"configurable": {"thread_id": event.source_thread_id}},
            {
                "branch_actions": serialize_branch_actions([*actions, action]),
                "branch_action_audit": [*current_audit, audit],
            },
            as_node="bootstrap_turn",
        )
        return self._update_event(
            event,
            status=BranchDecisionStatus.PROMOTED,
            promoted_action_id=action.action_id,
            executed_at=_now_iso(),
            metadata={
                **event.metadata,
                "promoted_to_pending_branch_action": True,
                "requested_branch_action_kind": requested_kind.value,
                "branch_action_kind": kind.value,
                "target_parent_thread_id": target_thread_id,
                "suggested_branch_name": suggested_branch_name,
            },
        )

    def _prepare_merge_proposal_for_event(
        self,
        event: BranchDecisionEvent,
        *,
        user_id: str,
    ) -> BranchDecisionEvent:
        if self.branch_service is None or not has_repo_method(
            self.branch_service,
            "prepare_merge_proposal",
        ):
            return self._update_event(
                event,
                status=BranchDecisionStatus.BLOCKED,
                error="Branch merge proposal service is not configured.",
                metadata={**event.metadata, "reason": "merge_service_unconfigured"},
            )
        try:
            proposal = self.branch_service.prepare_merge_proposal(
                child_thread_id=event.source_thread_id,
                user_id=user_id,
            )
        except KeyError:
            return self._update_event(
                event,
                status=BranchDecisionStatus.BLOCKED,
                error="Merge proposal preparation requires an existing child branch.",
                metadata={**event.metadata, "reason": "merge_requires_child_branch"},
            )
        except ValueError as exc:
            return self._update_event(
                event,
                status=BranchDecisionStatus.BLOCKED,
                error=str(exc),
                metadata={**event.metadata, "reason": "merge_requires_child_branch"},
            )
        except Exception as exc:  # noqa: BLE001 - proposal generation errors are audit evidence.
            logger.warning("branch decision merge proposal preparation failed", exc_info=True)
            return self._update_event(event, status=BranchDecisionStatus.ERROR, error=str(exc))
        return self._update_event(
            event,
            metadata={
                **event.metadata,
                "merge_proposal_prepared": True,
                "merge_proposal_summary_chars": len(proposal.summary or ""),
            },
        )

    def _save_event(self, event: BranchDecisionEvent) -> BranchDecisionEvent:
        if not has_repo_method(self.governance_repository, "save_branch_decision_event"):
            return event
        decision_id = self.governance_repository.save_branch_decision_event(event)
        if decision_id != event.decision_id and has_repo_method(
            self.governance_repository,
            "get_branch_decision_event",
        ):
            return self.governance_repository.get_branch_decision_event(decision_id) or event
        return event

    def _update_event(self, event: BranchDecisionEvent, **updates: Any) -> BranchDecisionEvent:
        updated = event.model_copy(update={**updates, "updated_at": _now_iso()})
        if has_repo_method(self.governance_repository, "update_branch_decision_event"):
            return self.governance_repository.update_branch_decision_event(updated)
        self._save_event(updated)
        return updated

    def _require_event(self, decision_id: str) -> BranchDecisionEvent:
        if not has_repo_method(self.governance_repository, "get_branch_decision_event"):
            raise KeyError(decision_id)
        event = self.governance_repository.get_branch_decision_event(decision_id)
        if event is None:
            raise KeyError(decision_id)
        return event

    def _assert_thread_owner(self, *, thread_id: str, user_id: str) -> None:
        repo = getattr(self.branch_service, "repo", None)
        if repo is not None and has_repo_method(repo, "assert_thread_owner"):
            repo.assert_thread_owner(thread_id=thread_id, owner_user_id=user_id)

    def _thread_resolution(self, *, thread_id: str, user_id: str) -> ThreadResolution:
        repo = getattr(self.branch_service, "repo", None)
        resolver = getattr(repo, "resolve_thread_ref", None)
        if callable(resolver):
            return resolver(thread_id=thread_id, owner_user_id=user_id)
        return ThreadResolution(
            input_thread_id=thread_id,
            root_thread_id=thread_id,
            source_thread_id=thread_id,
            diagnostic="resolver_unavailable_assumed_root",
        )

    def _branch_meta_for_thread(
        self, *, thread_id: str, values: dict[str, Any]
    ) -> BranchMeta | None:
        repo = getattr(self.branch_service, "repo", None)
        get_by_child = getattr(repo, "get_by_child_thread_id", None)
        if callable(get_by_child):
            try:
                record = get_by_child(thread_id)
            except KeyError:
                record = None
            if record is not None:
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
        return self._branch_meta_from_values(values)

    def _safe_get_values(self, thread_id: str) -> dict[str, Any]:
        if not has_repo_method(self.graph, "get_state"):
            return normalize_agent_state()
        snapshot = self.graph.get_state({"configurable": {"thread_id": thread_id}})
        return normalize_agent_state(dict(getattr(snapshot, "values", {}) or {}))

    @staticmethod
    def _branch_meta_from_values(values: dict[str, Any]) -> BranchMeta | None:
        raw = values.get("branch_meta")
        if not isinstance(raw, dict):
            return None
        try:
            return BranchMeta.model_validate(raw)
        except Exception:
            return None


def _should_run_semantic_topic_relation(
    *,
    signals: list[Any],
    action: BranchDecisionAction,
) -> bool:
    explicit_source = str(
        _branch_recommendation_signal_value(
            signals,
            "recommendation_explicit_source",
            "none",
        )
    )
    shape = _branch_recommendation_signal_value(signals, "pre_turn_message_shape", {})
    has_history_context = bool(
        shape.get("has_history_context") if isinstance(shape, dict) else False
    )
    return (
        explicit_source == "none"
        and action == BranchDecisionAction.CONTINUE_CURRENT
        and has_history_context
    )


def _branch_recommendation_signal_value(
    signals: list[Any],
    name: str,
    default: Any,
) -> Any:
    for signal in signals:
        if getattr(signal, "name", None) == name:
            return getattr(signal, "value", default)
    return default


def _normalized_message_hash(message: str | None) -> str:
    normalized = " ".join(str(message or "").split())
    return sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _branch_handoff_idempotency_key(*, thread_id: str, message: str | None) -> str:
    return f"branch_handoff:{thread_id}:{_normalized_message_hash(message)}"


def _message_preview(message: str | None, *, limit: int = 240) -> str:
    return " ".join(str(message or "").split())[:limit]


def _semantic_topic_relation_metadata(signals: list[Any]) -> dict[str, Any]:
    relation = _semantic_topic_relation_from_signals(signals)
    return {
        "semantic_relatedness": relation.get("relatedness"),
        "semantic_relationship": relation.get("relationship"),
        "semantic_reason": relation.get("reason"),
        "semantic_model": relation.get("model"),
        "semantic_classifier_status": relation.get("status"),
    }


def _semantic_topic_relation_diagnostic(signals: list[Any]) -> dict[str, Any]:
    relation = _semantic_topic_relation_from_signals(signals)
    return {
        "semantic_topic_shift": bool(relation.get("topic_shift")),
        "semantic_confidence": float(relation.get("confidence") or 0.0),
        "semantic_recommended_action": relation.get("recommended_action"),
        "semantic_classifier_status": relation.get("status"),
        "semantic_reason": relation.get("reason"),
    }


def _semantic_topic_relation_from_signals(signals: list[Any]) -> dict[str, Any]:
    value = _branch_recommendation_signal_value(signals, "semantic_topic_relation", {})
    return value if isinstance(value, dict) else {}


def _call_semantic_topic_relation_classifier(
    classifier: Any,
    *,
    settings: Any,
    message: str,
    values: dict[str, Any],
    branch_meta: BranchMeta | None,
) -> Any:
    callable_classifier = _semantic_topic_relation_callable(classifier)
    messages = list(values.get("messages", []) or [])
    kwargs = {
        "settings": settings,
        "message": message,
        "incoming_message": message,
        "values": values,
        "messages": messages,
        "branch_history": messages,
        "branch_meta": branch_meta,
        "on_branch": branch_meta is not None,
        "selected_model": _selected_model_from_values(values),
    }
    for candidate_kwargs in (
        kwargs,
        {
            "message": message,
            "branch_history": messages,
            "on_branch": branch_meta is not None,
        },
        {
            "settings": settings,
            "message": message,
            "branch_history": messages,
            "on_branch": branch_meta is not None,
            "selected_model": _selected_model_from_values(values),
        },
        {
            "message": message,
            "messages": messages,
            "branch_meta": branch_meta,
        },
        {
            "message": message,
            "values": values,
        },
        {
            "message": message,
        },
    ):
        try:
            return callable_classifier(**candidate_kwargs)
        except TypeError:
            continue
    return callable_classifier(message, messages, branch_meta)


def _semantic_topic_relation_callable(classifier: Any) -> Any:
    for attr in (
        "classify_semantic_topic_relation",
        "classify_topic_relation",
        "classify",
        "evaluate",
    ):
        candidate = getattr(classifier, attr, None)
        if callable(candidate):
            return candidate
    if callable(classifier):
        return classifier
    raise TypeError("semantic topic relation classifier is not callable")


def _normalize_semantic_topic_relation_result(result: Any) -> dict[str, Any]:
    payload = _model_payload(result)
    if not payload or set(payload) == {"raw_response"}:
        return {
            "status": "non_json" if payload else "error",
            "topic_shift": False,
            "confidence": 0.0,
            "recommended_action": BranchDecisionAction.CONTINUE_CURRENT.value,
            "reason": "Semantic classifier returned no structured result.",
        }
    return {
        "status": _semantic_status(payload.get("status")),
        "topic_shift": bool(
            payload.get("topic_shift")
            if "topic_shift" in payload
            else payload.get("is_topic_shift", payload.get("new_topic", False))
        ),
        "confidence": _semantic_confidence(payload),
        "recommended_action": _semantic_recommended_action(
            payload.get("recommended_action")
            or payload.get("action")
            or payload.get("recommendation_target")
        ).value,
        "relatedness": payload.get("relatedness")
        if "relatedness" in payload
        else payload.get("semantic_relatedness", payload.get("relatedness_score")),
        "relationship": payload.get("relationship")
        if "relationship" in payload
        else payload.get("relation", payload.get("semantic_relationship")),
        "reason": str(payload.get("reason") or payload.get("rationale") or ""),
        "model": payload.get("model") or payload.get("model_name"),
    }


def _selected_model_from_values(values: dict[str, Any]) -> str | None:
    for key in ("selected_model", "model", "model_id"):
        text = str(values.get(key) or "").strip()
        if text:
            return text
    return None


def _model_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        dumped = dict_method()
        return dumped if isinstance(dumped, dict) else {}
    raw_dict = getattr(value, "__dict__", None)
    return raw_dict if isinstance(raw_dict, dict) else {}


def _semantic_status(value: Any) -> str:
    status = str(value or "success").strip().lower()
    if status in {"succeeded", "completed"}:
        return "success"
    return status or "error"


def _semantic_confidence(payload: dict[str, Any]) -> float:
    raw = payload.get("confidence")
    if raw is None:
        raw = payload.get("score", payload.get("probability", 0.0))
    try:
        return max(0.0, min(float(raw or 0.0), 1.0))
    except (TypeError, ValueError):
        return 0.0


def _semantic_recommended_action(value: Any) -> BranchDecisionAction:
    raw = str(value or "").strip()
    for action in {
        BranchDecisionAction.CONTINUE_CURRENT,
        BranchDecisionAction.FORK_CHILD_BRANCH,
        BranchDecisionAction.FORK_SIBLING_BRANCH,
    }:
        if raw == action.value:
            return action
    return BranchDecisionAction.CONTINUE_CURRENT


def _branch_decision_mode(value: object) -> BranchDecisionMode:
    normalized = str(value or "").strip().lower()
    if normalized == BranchDecisionMode.SUGGEST.value:
        return BranchDecisionMode.SUGGEST
    if normalized == BranchDecisionMode.EXECUTE.value:
        return BranchDecisionMode.EXECUTE
    return BranchDecisionMode.SHADOW


def _branch_action_kind_for_decision(action: BranchDecisionAction) -> BranchActionKind:
    if action == BranchDecisionAction.FORK_SIBLING_BRANCH:
        return BranchActionKind.FORK_SIBLING_BRANCH
    return BranchActionKind.FORK_CHILD_BRANCH


def _decision_action_for_branch_action_kind(kind: BranchActionKind) -> BranchDecisionAction:
    if kind == BranchActionKind.FORK_SIBLING_BRANCH:
        return BranchDecisionAction.FORK_SIBLING_BRANCH
    return BranchDecisionAction.FORK_CHILD_BRANCH


def _recommendation_target_for_decision(
    action: BranchDecisionAction,
) -> BranchDecisionRecommendationTarget:
    if action == BranchDecisionAction.FORK_SIBLING_BRANCH:
        return BranchDecisionRecommendationTarget.FORK_SIBLING_BRANCH
    if action == BranchDecisionAction.FORK_CHILD_BRANCH:
        return BranchDecisionRecommendationTarget.FORK_CHILD_BRANCH
    return BranchDecisionRecommendationTarget.CONTINUE_CURRENT


def _branch_role_for_recommendation(
    target: BranchDecisionRecommendationTarget | None,
) -> BranchRole:
    if target == BranchDecisionRecommendationTarget.FORK_CHILD_BRANCH:
        return BranchRole.DEEP_DIVE
    return BranchRole.EXPLORE_ALTERNATIVES


def _recommendation_user_visible(*, enabled: bool, mode: BranchDecisionMode) -> bool:
    return bool(enabled and mode == BranchDecisionMode.SUGGEST)


def _recommendation_diagnostics(
    *,
    enabled: bool,
    mode: BranchDecisionMode,
    semantic_enabled: bool = False,
    semantic_model: str | None = None,
) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "mode": mode.value,
        "user_visible": _recommendation_user_visible(enabled=enabled, mode=mode),
        "shadow_records_events_only": mode == BranchDecisionMode.SHADOW,
        "pending_action_mode": BranchDecisionMode.SUGGEST.value,
        "semantic_enabled": bool(semantic_enabled),
        "semantic_model": semantic_model,
    }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


__all__ = ["BranchDecisionService"]
