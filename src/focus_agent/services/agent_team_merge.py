from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from focus_agent.core.agent_team import (
    AgentTeamFinalAnswerStatus,
    AgentTeamMergeBundle,
    AgentTeamMergeDecision,
    AgentTeamMergeReview,
    AgentTeamMergeReviewEvent,
    AgentTeamMergeReviewStatus,
    AgentTeamRecommendedAction,
    AgentTeamSession,
    AgentTeamSessionStatus,
    AgentTeamTask,
    AgentTeamTaskStatus,
)
from focus_agent.multi_agent.conflict_detector import MergeConflictDetector

from .agent_team_helpers import _dedupe, _now
from .agent_team_merge_helpers import (
    _build_final_answer,
    _execution_evidence,
    _has_review_or_verification_evidence,
    _merge_test_evidence,
    _missing_required_evidence,
    _planning_risk_notes,
    _strong_evidence_gate_violations,
)
from .agent_team_merge_preview import _build_merge_review_preview
from .agent_team_merge_review_actions import (
    _capture_merge_review_payload,
    _merge_review_applied,
    _merge_review_apply_conflict,
    _merge_review_apply_error,
    _merge_review_event,
)
from .agent_team_merge_review_git import (
    check_patch as _check_patch,
)
from .agent_team_merge_review_git import (
    repo_root as _repo_root,
)
from .agent_team_merge_review_git import (
    run_git_apply as _run_git_apply,
)


def _multi_agent_merge_conflict_detection_enabled(settings: Any | None) -> bool:
    return bool(getattr(settings, "multi_agent_v2_enabled", False))


def _task_outputs_for_conflict_detection(
    *,
    tasks: list[AgentTeamTask],
    outputs: list[Any],
) -> dict[str, dict[str, Any]]:
    by_task: dict[str, dict[str, Any]] = {
        task.task_id: {
            "summary": task.verification_summary or "",
            "changed_files": list(task.changed_files),
        }
        for task in tasks
    }
    for output in outputs:
        payload = by_task.setdefault(
            output.task_id,
            {"summary": "", "changed_files": []},
        )
        if output.summary:
            payload["summary"] = " ".join(
                part for part in [payload.get("summary"), output.summary] if part
            )
        payload["changed_files"] = _dedupe(
            [*payload.get("changed_files", []), *output.changed_files]
        )
    return by_task


class AgentTeamMergeMixin:
    def prepare_merge_bundle(self, *, session_id: str, user_id: str) -> AgentTeamMergeBundle:
        session = self.get_session(session_id, user_id=user_id)
        tasks = self.list_tasks(session_id=session_id, user_id=user_id)
        outputs = [
            output
            for task in tasks
            for output in self.repository.list_task_outputs(task_id=task.task_id)
        ]
        accepted = [task.task_id for task in tasks if task.status == AgentTeamTaskStatus.DONE]
        rejected = [
            task.task_id
            for task in tasks
            if task.status in {AgentTeamTaskStatus.FAILED, AgentTeamTaskStatus.CANCELLED}
        ]
        blocked = [task for task in tasks if task.status == AgentTeamTaskStatus.BLOCKED]
        pending = [
            task
            for task in tasks
            if task.status
            in {
                AgentTeamTaskStatus.PENDING,
                AgentTeamTaskStatus.QUEUED,
                AgentTeamTaskStatus.RUNNING,
            }
        ]
        risk_items = _dedupe(
            [note for task in tasks for note in task.risk_notes]
            + [note for output in outputs for note in output.risk_notes]
            + _planning_risk_notes(session=session, outputs=outputs)
        )
        missing_required_evidence = _missing_required_evidence(tasks=tasks, outputs=outputs)
        strong_evidence_violations = _strong_evidence_gate_violations(
            tasks=tasks,
            outputs=outputs,
        )
        risk_items = _dedupe([*risk_items, *missing_required_evidence, *strong_evidence_violations])
        test_evidence = _merge_test_evidence(tasks=tasks, outputs=outputs)
        execution_evidence = _execution_evidence(tasks=tasks, outputs=outputs)
        has_review_evidence = _has_review_or_verification_evidence(
            tasks=tasks,
            outputs=outputs,
        )
        if not has_review_evidence:
            missing_evidence_note = (
                "Missing review/verification evidence: add reviewer, verifier, or test "
                "evidence before merge."
            )
            risk_items = _dedupe([*risk_items, missing_evidence_note])
        key_findings = _dedupe(output.summary for output in outputs if output.summary)
        changed_files = _dedupe(
            [path for task in tasks for path in task.changed_files]
            + [path for output in outputs for path in output.changed_files]
        )
        conflict_reports = []
        if _multi_agent_merge_conflict_detection_enabled(getattr(self, "settings", None)):
            task_outputs = _task_outputs_for_conflict_detection(tasks=tasks, outputs=outputs)
            conflict_reports = MergeConflictDetector().detect(task_outputs)
            risk_items = _dedupe(
                [
                    *risk_items,
                    *[
                        f"Merge conflict {report.severity}: {report.description}"
                        for report in conflict_reports
                    ],
                ]
            )
        open_questions = _dedupe(
            [f"{task.role.value}: {self._compact_task_goal(task.goal)}" for task in blocked]
            + [
                f"Pending {task.role.value}: {self._compact_task_goal(task.goal)}"
                for task in pending
            ]
            + (
                ["Collect review/verification evidence before merge."]
                if not has_review_evidence
                else []
            )
        )
        blocking_conflicts = [
            report for report in conflict_reports if report.severity == "blocking"
        ]
        if blocking_conflicts:
            open_questions = _dedupe(
                [
                    *open_questions,
                    *[
                        f"Resolve blocking conflict {report.conflict_id}: {report.suggested_resolution}"
                        for report in blocking_conflicts
                    ],
                ]
            )
        recommended = self._recommended_action(
            accepted_count=len(accepted),
            rejected_count=len(rejected),
            pending_count=len(pending),
            blocked_count=len(blocked) + len(blocking_conflicts),
            risk_count=len(risk_items),
        )
        final_answer = _build_final_answer(
            session=session,
            tasks=tasks,
            outputs=outputs,
            open_questions=open_questions,
            risk_items=risk_items,
        )
        if final_answer["status"] == AgentTeamFinalAnswerStatus.PLACEHOLDER:
            recommended = AgentTeamRecommendedAction.REQUEST_CHANGES
        if blocking_conflicts or strong_evidence_violations:
            recommended = AgentTeamRecommendedAction.REQUEST_CHANGES
            if blocking_conflicts or final_answer["status"] == AgentTeamFinalAnswerStatus.READY:
                final_answer["status"] = AgentTeamFinalAnswerStatus.BLOCKED
            final_answer["warnings"] = _dedupe(
                [
                    *list(final_answer["warnings"]),
                    *(
                        ["Blocking multi-agent merge conflict detected."]
                        if blocking_conflicts
                        else []
                    ),
                    *(
                        ["Strong execution evidence gate blocked merge."]
                        if strong_evidence_violations
                        else []
                    ),
                ]
            )
        bundle = AgentTeamMergeBundle(
            session_id=session_id,
            summary=self._bundle_summary(session=session, tasks=tasks, key_findings=key_findings),
            final_answer=str(final_answer["answer"]),
            final_answer_status=final_answer["status"],
            final_answer_warnings=list(final_answer["warnings"]),
            source_output_ids=list(final_answer["source_output_ids"]),
            accepted_tasks=accepted,
            rejected_tasks=rejected,
            key_findings=key_findings,
            changed_files=changed_files,
            test_evidence=test_evidence,
            execution_evidence=execution_evidence,
            open_questions=open_questions,
            risk_items=risk_items,
            recommended_next_action=recommended,
        )
        with self._lock:
            self.repository.save_session(
                session.model_copy(
                    update={
                        "status": AgentTeamSessionStatus.AWAITING_REVIEW,
                        "latest_merge_bundle": bundle.model_dump(mode="json"),
                        "updated_at": _now(),
                    }
                )
            )
        return bundle

    def apply_merge_decision(
        self,
        *,
        session_id: str,
        user_id: str,
        approved: bool,
        action: AgentTeamRecommendedAction | str | None = None,
        rationale: str | None = None,
        accepted_tasks: list[str] | None = None,
        rejected_tasks: list[str] | None = None,
    ) -> AgentTeamMergeDecision:
        session = self.get_session(session_id, user_id=user_id)
        bundle_payload = dict(session.latest_merge_bundle or {})
        tasks = self.list_tasks(session_id=session_id, user_id=user_id)
        outputs = [
            output
            for task in tasks
            for output in self.repository.list_task_outputs(task_id=task.task_id)
        ]
        strong_evidence_violations = _strong_evidence_gate_violations(
            tasks=tasks,
            outputs=outputs,
        )
        resolved_action = AgentTeamRecommendedAction(
            action
            or bundle_payload.get("recommended_next_action")
            or AgentTeamRecommendedAction.MERGE
        )
        if strong_evidence_violations:
            approved = False
            resolved_action = AgentTeamRecommendedAction.REQUEST_CHANGES
            rationale = _merge_gate_rationale(
                rationale=rationale,
                violations=strong_evidence_violations,
            )
        decision = AgentTeamMergeDecision(
            decision_id=str(uuid4()),
            session_id=session_id,
            approved=approved,
            action=resolved_action,
            rationale=rationale,
            accepted_tasks=list(
                accepted_tasks
                if accepted_tasks is not None
                else bundle_payload.get("accepted_tasks") or []
            ),
            rejected_tasks=list(
                rejected_tasks
                if rejected_tasks is not None
                else bundle_payload.get("rejected_tasks") or []
            ),
            created_at=_now(),
        )
        next_status = (
            AgentTeamSessionStatus.COMPLETED
            if approved and resolved_action == AgentTeamRecommendedAction.MERGE
            else AgentTeamSessionStatus.AWAITING_REVIEW
        )
        if resolved_action == AgentTeamRecommendedAction.DISCARD:
            next_status = AgentTeamSessionStatus.CANCELLED
        with self._lock:
            self.repository.save_session(
                session.model_copy(
                    update={
                        "status": next_status,
                        "merge_decision": decision.model_dump(mode="json"),
                        "updated_at": _now(),
                    }
                )
            )
        if next_status in {AgentTeamSessionStatus.COMPLETED, AgentTeamSessionStatus.CANCELLED}:
            try:
                self.workspace_service.cleanup_workspace(session_id=session_id, force=True)
            except Exception:  # noqa: BLE001
                pass
        return decision

    def create_merge_review(
        self,
        *,
        session_id: str,
        user_id: str,
        selected_task_ids: list[str] | None = None,
        excluded_task_ids: list[str] | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentTeamMergeReview:
        session = self.get_session(session_id, user_id=user_id)
        task_ids = {
            task.task_id for task in self.list_tasks(session_id=session_id, user_id=user_id)
        }
        selected = _normalize_task_selection(selected_task_ids, known_task_ids=task_ids)
        excluded = _normalize_task_selection(excluded_task_ids, known_task_ids=task_ids)
        now = _now()
        review = AgentTeamMergeReview(
            review_id=str(uuid4()),
            session_id=session.session_id,
            user_id=user_id,
            status=AgentTeamMergeReviewStatus.DRAFT,
            title=title or f"{session.title} merge review",
            selected_task_ids=selected,
            excluded_task_ids=excluded,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self.repository.save_merge_review(review)
            self._record_merge_review_event(
                review=review,
                event_type="created",
                message="Merge review created.",
            )
        return review

    def get_merge_review(
        self,
        *,
        session_id: str,
        review_id: str,
        user_id: str,
    ) -> AgentTeamMergeReview:
        self.get_session(session_id, user_id=user_id)
        with self._lock:
            review = self.repository.get_merge_review(review_id)
        if review.session_id != session_id:
            raise KeyError(f"Unknown agent team merge review: {review_id}")
        if review.user_id != user_id:
            raise PermissionError("Agent team merge review belongs to another user.")
        return review

    def list_merge_reviews(self, *, session_id: str, user_id: str) -> list[AgentTeamMergeReview]:
        self.get_session(session_id, user_id=user_id)
        with self._lock:
            reviews = self.repository.list_merge_reviews(session_id=session_id)
        return [review for review in reviews if review.user_id == user_id]

    def list_merge_review_events(
        self,
        *,
        session_id: str,
        review_id: str,
        user_id: str,
    ) -> list[AgentTeamMergeReviewEvent]:
        self.get_merge_review(session_id=session_id, review_id=review_id, user_id=user_id)
        with self._lock:
            return self.repository.list_merge_review_events(review_id=review_id)

    def update_merge_review(
        self,
        *,
        session_id: str,
        review_id: str,
        user_id: str,
        selected_task_ids: list[str] | None = None,
        excluded_task_ids: list[str] | None = None,
        status: AgentTeamMergeReviewStatus | str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentTeamMergeReview:
        review = self.get_merge_review(session_id=session_id, review_id=review_id, user_id=user_id)
        task_ids = {
            task.task_id for task in self.list_tasks(session_id=session_id, user_id=user_id)
        }
        updates: dict[str, Any] = {"updated_at": _now()}
        if selected_task_ids is not None:
            updates["selected_task_ids"] = _normalize_task_selection(
                selected_task_ids,
                known_task_ids=task_ids,
            )
        if excluded_task_ids is not None:
            updates["excluded_task_ids"] = _normalize_task_selection(
                excluded_task_ids,
                known_task_ids=task_ids,
            )
        if title is not None:
            updates["title"] = title
        if metadata is not None:
            updates["metadata"] = {**review.metadata, **metadata}
        if status is not None:
            updates["status"] = _allowed_review_transition(
                current=review.status,
                target=AgentTeamMergeReviewStatus(status),
            )
        updated = review.model_copy(update=updates)
        with self._lock:
            self.repository.save_merge_review(updated)
            self._record_merge_review_event(
                review=updated,
                event_type="updated",
                message="Merge review updated.",
                metadata={"updated_fields": sorted(updates)},
            )
        return updated

    def preview_merge_review(
        self,
        *,
        session_id: str,
        review_id: str,
        user_id: str,
    ) -> AgentTeamMergeReview:
        review = self.get_merge_review(session_id=session_id, review_id=review_id, user_id=user_id)
        tasks = self.list_tasks(session_id=session_id, user_id=user_id)
        outputs = [
            output
            for task in tasks
            for output in self.repository.list_task_outputs(task_id=task.task_id)
        ]
        selected_tasks = _selected_review_tasks(review=review, tasks=tasks)
        preview = _build_merge_review_preview(review=review, tasks=selected_tasks, outputs=outputs)
        target_root = _repo_root(self)
        check = _check_patch(target_root=target_root, patch=preview["patch"])
        status = AgentTeamMergeReviewStatus.READY
        error_message = None
        conflict_files: list[str] = []
        if preview["non_adoptable_task_ids"]:
            status = AgentTeamMergeReviewStatus.ERROR
            error_message = (
                "Selected tasks include fake or placeholder outputs and cannot be adopted."
            )
        elif preview["patch"] and not check["ok"]:
            status = AgentTeamMergeReviewStatus.CONFLICT
            error_message = check["message"]
            conflict_files = list(check["files"])
        updated = review.model_copy(
            update={
                "status": status,
                "summary": preview["summary"],
                "changed_files": preview["changed_files"],
                "diffstat": preview["diffstat"],
                "test_evidence": preview["test_evidence"],
                "risk_items": preview["risk_items"],
                "task_summaries": preview["task_summaries"],
                "conflict_files": conflict_files,
                "error_message": error_message,
                "metadata": {
                    **review.metadata,
                    "patch": preview["patch"],
                    "patch_bytes": len(preview["patch"].encode("utf-8")),
                    "non_adoptable_task_ids": preview["non_adoptable_task_ids"],
                    "preview_check": check,
                },
                "previewed_at": _now(),
                "updated_at": _now(),
            }
        )
        with self._lock:
            self.repository.save_merge_review(updated)
            self._record_merge_review_event(
                review=updated,
                event_type="previewed",
                message=error_message or "Merge review preview generated.",
                metadata={"status": updated.status.value, "changed_files": updated.changed_files},
            )
        return updated

    def apply_merge_review(
        self,
        *,
        session_id: str,
        review_id: str,
        user_id: str,
        apply_target_path: str | None = None,
    ) -> AgentTeamMergeReview:
        review = self.get_merge_review(session_id=session_id, review_id=review_id, user_id=user_id)
        patch = str(review.metadata.get("patch") or "")
        if not patch or review.status not in {
            AgentTeamMergeReviewStatus.READY,
            AgentTeamMergeReviewStatus.APPROVED,
        }:
            review = self.preview_merge_review(
                session_id=session_id,
                review_id=review_id,
                user_id=user_id,
            )
            patch = str(review.metadata.get("patch") or "")
        if review.status == AgentTeamMergeReviewStatus.CONFLICT:
            return review
        if review.status == AgentTeamMergeReviewStatus.ERROR:
            raise ValueError(review.error_message or "Merge review cannot be applied.")
        if not patch.strip():
            raise ValueError("Merge review has no patch to apply.")
        target_root = (
            Path(apply_target_path).expanduser().resolve()
            if apply_target_path
            else _repo_root(self)
        )
        check = _check_patch(target_root=target_root, patch=patch)
        if not check["ok"]:
            updated = _merge_review_apply_conflict(
                review,
                check=check,
                target_root=target_root,
            )
            with self._lock:
                self.repository.save_merge_review(updated)
                self._record_merge_review_event(
                    review=updated,
                    event_type="apply_conflict",
                    message=updated.error_message,
                    metadata=check,
                )
            return updated
        apply_result = _run_git_apply(target_root=target_root, patch=patch, check_only=False)
        if apply_result["returncode"] != 0:
            updated = _merge_review_apply_error(
                review,
                apply_result=apply_result,
                target_root=target_root,
            )
            with self._lock:
                self.repository.save_merge_review(updated)
                self._record_merge_review_event(
                    review=updated,
                    event_type="apply_error",
                    message=updated.error_message,
                    metadata=apply_result,
                )
            return updated
        updated = _merge_review_applied(review, target_root=target_root)
        with self._lock:
            self.repository.save_merge_review(updated)
            self._record_merge_review_event(
                review=updated,
                event_type="applied",
                message="Merge review patch applied.",
                metadata={"apply_target_path": str(target_root)},
            )
        return updated

    def reject_merge_review(
        self,
        *,
        session_id: str,
        review_id: str,
        user_id: str,
        rationale: str | None = None,
    ) -> AgentTeamMergeReview:
        review = self.get_merge_review(session_id=session_id, review_id=review_id, user_id=user_id)
        updated = review.model_copy(
            update={
                "status": AgentTeamMergeReviewStatus.REJECTED,
                "metadata": {**review.metadata, "rejection_rationale": rationale},
                "rejected_at": _now(),
                "updated_at": _now(),
            }
        )
        with self._lock:
            self.repository.save_merge_review(updated)
            self._record_merge_review_event(
                review=updated,
                event_type="rejected",
                message=rationale or "Merge review rejected.",
            )
        return updated

    def capture_merge_review(
        self,
        *,
        session_id: str,
        review_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        review = self.get_merge_review(session_id=session_id, review_id=review_id, user_id=user_id)
        return _capture_merge_review_payload(review)

    def _record_merge_review_event(
        self,
        *,
        review: AgentTeamMergeReview,
        event_type: str,
        message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.repository.add_merge_review_event(
            _merge_review_event(
                review=review,
                event_type=event_type,
                message=message,
                metadata=metadata,
            )
        )

    @staticmethod
    def _bundle_summary(
        *, session: AgentTeamSession, tasks: list[AgentTeamTask], key_findings: list[str]
    ) -> str:
        done = len([task for task in tasks if task.status == AgentTeamTaskStatus.DONE])
        total = len(tasks)
        headline = f"{session.title}: {done}/{total} tasks ready for merge."
        if key_findings:
            return f"{headline} Top finding: {key_findings[0]}"
        return headline


def _normalize_task_selection(
    task_ids: list[str] | None,
    *,
    known_task_ids: set[str],
) -> list[str]:
    values = _dedupe(str(item).strip() for item in task_ids or [] if str(item).strip())
    unknown = sorted(set(values) - known_task_ids)
    if unknown:
        raise ValueError(f"Unknown agent team task ids: {', '.join(unknown)}")
    return values


def _merge_gate_rationale(*, rationale: str | None, violations: list[str]) -> str:
    gate_reason = "Strong execution evidence gate blocked merge: " + " ".join(violations)
    return f"{rationale}\n{gate_reason}" if rationale else gate_reason


def _selected_review_tasks(
    *,
    review: AgentTeamMergeReview,
    tasks: list[AgentTeamTask],
) -> list[AgentTeamTask]:
    selected = set(review.selected_task_ids)
    excluded = set(review.excluded_task_ids)
    if selected:
        candidates = [task for task in tasks if task.task_id in selected]
    else:
        candidates = [task for task in tasks if task.status == AgentTeamTaskStatus.DONE]
    return [task for task in candidates if task.task_id not in excluded]


def _allowed_review_transition(
    *,
    current: AgentTeamMergeReviewStatus,
    target: AgentTeamMergeReviewStatus,
) -> AgentTeamMergeReviewStatus:
    if current == target:
        return target
    allowed = {
        AgentTeamMergeReviewStatus.DRAFT: {
            AgentTeamMergeReviewStatus.READY,
            AgentTeamMergeReviewStatus.APPROVED,
            AgentTeamMergeReviewStatus.REJECTED,
            AgentTeamMergeReviewStatus.ERROR,
        },
        AgentTeamMergeReviewStatus.READY: {
            AgentTeamMergeReviewStatus.APPROVED,
            AgentTeamMergeReviewStatus.REJECTED,
            AgentTeamMergeReviewStatus.CONFLICT,
            AgentTeamMergeReviewStatus.ERROR,
        },
        AgentTeamMergeReviewStatus.APPROVED: {
            AgentTeamMergeReviewStatus.APPLIED,
            AgentTeamMergeReviewStatus.REJECTED,
            AgentTeamMergeReviewStatus.CONFLICT,
            AgentTeamMergeReviewStatus.ERROR,
        },
        AgentTeamMergeReviewStatus.CONFLICT: {
            AgentTeamMergeReviewStatus.READY,
            AgentTeamMergeReviewStatus.REJECTED,
            AgentTeamMergeReviewStatus.ERROR,
        },
        AgentTeamMergeReviewStatus.ERROR: {
            AgentTeamMergeReviewStatus.DRAFT,
            AgentTeamMergeReviewStatus.REJECTED,
        },
        AgentTeamMergeReviewStatus.APPLIED: set(),
        AgentTeamMergeReviewStatus.REJECTED: set(),
    }
    if target not in allowed[current]:
        raise ValueError(
            f"Invalid merge review status transition: {current.value} -> {target.value}"
        )
    return target


__all__ = ["AgentTeamMergeMixin"]
