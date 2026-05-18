from __future__ import annotations

import logging
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from focus_agent.core.branching import (
    BranchActionKind,
    BranchMeta,
    BranchRole,
    BranchStatus,
)
from focus_agent.core.governance import (
    BranchDecisionAction,
    BranchDecisionConfig,
    BranchDecisionEvent,
    BranchDecisionMode,
    BranchDecisionRecommendationTarget,
    BranchDecisionStatus,
    BranchDecisionSummary,
)
from focus_agent.core.repo_call import has_repo_method
from focus_agent.core.state import normalize_agent_state
from focus_agent.services.branch_actions import (
    branch_action_audit_event,
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
            recommendation_enabled=bool(
                getattr(self.settings, "agent_branch_recommendation_enabled", False)
            ),
            recommendation_mode=recommendation_mode,
            recommendation_min_confidence=float(
                getattr(self.settings, "agent_branch_recommendation_min_confidence", 0.72)
            ),
        )

    def recommendation_config(self) -> BranchDecisionConfig:
        mode = _branch_decision_mode(
            getattr(self.settings, "agent_branch_recommendation_mode", "shadow")
        )
        return BranchDecisionConfig(
            enabled=bool(getattr(self.settings, "agent_branch_recommendation_enabled", False)),
            mode=mode,
            min_confidence=float(
                getattr(self.settings, "agent_branch_recommendation_min_confidence", 0.72)
            ),
            recommendation_enabled=bool(
                getattr(self.settings, "agent_branch_recommendation_enabled", False)
            ),
            recommendation_mode=mode,
            recommendation_min_confidence=float(
                getattr(self.settings, "agent_branch_recommendation_min_confidence", 0.72)
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
        branch_meta = self._branch_meta_from_values(values)
        resolved_root_thread_id = root_thread_id or (
            branch_meta.root_thread_id if branch_meta is not None else thread_id
        )
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
                branch_id=branch_meta.branch_id if branch_meta is not None else None,
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
        branch_meta = self._branch_meta_from_values(values)
        resolved_root_thread_id = root_thread_id or (
            branch_meta.root_thread_id if branch_meta is not None else thread_id
        )
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
                branch_id=branch_meta.branch_id if branch_meta is not None else None,
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
        status = self._gate_status(
            config=config,
            values=values,
            branch_meta=branch_meta,
            score=best.score,
            threshold=best.threshold,
            user_id=user_id,
            thread_id=thread_id,
        )
        metadata: dict[str, Any] = {}
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
        status = self._gate_recommendation_status(
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
        }
        if suggested_branch_name:
            metadata["suggested_branch_name"] = suggested_branch_name
        if target_parent:
            metadata["target_parent_thread_id"] = target_parent
        if action in {
            BranchDecisionAction.FORK_CHILD_BRANCH,
            BranchDecisionAction.FORK_SIBLING_BRANCH,
        }:
            metadata["handoff_message_preview"] = str(message or "").strip()[:240]
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
    ) -> BranchDecisionStatus:
        del user_id
        if branch_meta is not None and branch_meta.branch_status in {
            BranchStatus.MERGED,
            BranchStatus.DISCARDED,
            BranchStatus.CLOSED,
        }:
            return BranchDecisionStatus.BLOCKED
        if latest_pending_branch_action(values.get("branch_actions")) is not None:
            return BranchDecisionStatus.BLOCKED
        if score < max(config.min_confidence, threshold):
            return BranchDecisionStatus.SKIPPED
        if self._rate_limited(thread_id=thread_id, limit=config.rate_limit_per_hour):
            return BranchDecisionStatus.BLOCKED
        if config.mode == BranchDecisionMode.SHADOW:
            return BranchDecisionStatus.SHADOWED
        return BranchDecisionStatus.SUGGESTED

    def _gate_recommendation_status(
        self,
        *,
        config: BranchDecisionConfig,
        values: dict[str, Any],
        branch_meta: BranchMeta | None,
        action: BranchDecisionAction,
        score: float,
        threshold: float,
    ) -> BranchDecisionStatus:
        if branch_meta is not None and branch_meta.branch_status in {
            BranchStatus.MERGED,
            BranchStatus.DISCARDED,
            BranchStatus.CLOSED,
        }:
            return BranchDecisionStatus.BLOCKED
        if (
            action
            in {
                BranchDecisionAction.FORK_CHILD_BRANCH,
                BranchDecisionAction.FORK_SIBLING_BRANCH,
            }
            and latest_pending_branch_action(values.get("branch_actions")) is not None
        ):
            return BranchDecisionStatus.BLOCKED
        if score < max(config.min_confidence, threshold):
            return BranchDecisionStatus.SKIPPED
        if action == BranchDecisionAction.CONTINUE_CURRENT:
            if config.mode == BranchDecisionMode.SHADOW:
                return BranchDecisionStatus.SHADOWED
            return BranchDecisionStatus.SKIPPED
        if action == BranchDecisionAction.FORK_CHILD_BRANCH and self._child_depth_exceeded(
            branch_meta
        ):
            return BranchDecisionStatus.BLOCKED
        if config.mode == BranchDecisionMode.SHADOW:
            return BranchDecisionStatus.SHADOWED
        return BranchDecisionStatus.SUGGESTED

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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


__all__ = ["BranchDecisionService"]
