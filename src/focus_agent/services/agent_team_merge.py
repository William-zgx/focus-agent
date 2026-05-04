from __future__ import annotations

from uuid import uuid4

from focus_agent.core.agent_team import (
    AgentTeamMergeBundle,
    AgentTeamMergeDecision,
    AgentTeamRecommendedAction,
    AgentTeamSession,
    AgentTeamSessionStatus,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskStatus,
)

from .agent_team_helpers import _dedupe, _now


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
            if task.status in {AgentTeamTaskStatus.PENDING, AgentTeamTaskStatus.RUNNING}
        ]
        risk_items = _dedupe(
            [note for task in tasks for note in task.risk_notes]
            + [note for output in outputs for note in output.risk_notes]
        )
        test_evidence = _dedupe(
            [task.verification_summary or "" for task in tasks]
            + [evidence for output in outputs for evidence in output.test_evidence]
        )
        key_findings = _dedupe(output.summary for output in outputs if output.summary)
        changed_files = _dedupe(
            [path for task in tasks for path in task.changed_files]
            + [path for output in outputs for path in output.changed_files]
        )
        open_questions = _dedupe(
            [f"{task.role.value}: {self._compact_task_goal(task.goal)}" for task in blocked]
            + [
                f"Pending {task.role.value}: {self._compact_task_goal(task.goal)}"
                for task in pending
            ]
        )
        recommended = self._recommended_action(
            accepted_count=len(accepted),
            rejected_count=len(rejected),
            pending_count=len(pending),
            blocked_count=len(blocked),
            risk_count=len(risk_items),
        )
        bundle = AgentTeamMergeBundle(
            session_id=session_id,
            summary=self._bundle_summary(session=session, tasks=tasks, key_findings=key_findings),
            accepted_tasks=accepted,
            rejected_tasks=rejected,
            key_findings=key_findings,
            changed_files=changed_files,
            test_evidence=test_evidence,
            execution_evidence=self._execution_evidence(tasks, outputs),
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
        resolved_action = AgentTeamRecommendedAction(
            action
            or bundle_payload.get("recommended_next_action")
            or AgentTeamRecommendedAction.MERGE
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
        return decision

    @staticmethod
    def _execution_evidence(
        tasks: list[AgentTeamTask],
        outputs: list[AgentTeamTaskOutput],
    ) -> list[dict[str, object]]:
        evidence: list[dict[str, object]] = []
        seen: set[tuple[str, str, str, str, tuple[str, ...]]] = set()

        def append_item(item: dict[str, object]) -> None:
            artifact_ids = _dedupe(str(value) for value in item.get("artifact_ids", []) or [])
            canonical: dict[str, object] = {"task_id": str(item.get("task_id") or "")}
            role = str(item.get("role") or "").strip()
            if role:
                canonical["role"] = role
            for field in ("agent_run_id", "delegated_task_id", "execution_status"):
                value = str(item.get(field) or "").strip()
                if value:
                    canonical[field] = value
            if artifact_ids:
                canonical["artifact_ids"] = artifact_ids
            key = (
                str(canonical.get("task_id") or ""),
                str(canonical.get("agent_run_id") or ""),
                str(canonical.get("delegated_task_id") or ""),
                str(canonical.get("execution_status") or ""),
                tuple(artifact_ids),
            )
            if key not in seen and any(key[1:]):
                seen.add(key)
                evidence.append(canonical)

        for task in tasks:
            append_item(
                {
                    "task_id": task.task_id,
                    "role": task.role.value,
                    "agent_run_id": task.agent_run_id,
                    "delegated_task_id": task.delegated_task_id,
                    "artifact_ids": task.artifact_ids,
                    "execution_status": task.execution_status,
                }
            )

        for output in outputs:
            execution_metadata = output.metadata.get("execution")
            if not isinstance(execution_metadata, dict):
                execution_metadata = {
                    key: output.metadata[key]
                    for key in (
                        "agent_run_id",
                        "delegated_task_id",
                        "artifact_ids",
                        "execution_status",
                    )
                    if key in output.metadata
                }
            if execution_metadata:
                append_item({"task_id": output.task_id, **execution_metadata})

        return evidence

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


__all__ = ["AgentTeamMergeMixin"]
