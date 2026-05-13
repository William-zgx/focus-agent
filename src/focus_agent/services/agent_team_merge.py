from __future__ import annotations

import json
from uuid import uuid4

from focus_agent.core.agent_team import (
    AgentTeamFinalAnswerStatus,
    AgentTeamMergeBundle,
    AgentTeamMergeDecision,
    AgentTeamRecommendedAction,
    AgentTeamSession,
    AgentTeamSessionStatus,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)

from .agent_team_helpers import _dedupe, _now


_REVIEW_EVIDENCE_ROLES = {
    "reviewer",
    "test_engineer",
    "verifier",
}


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
            + _planning_risk_notes(session=session, outputs=outputs)
        )
        missing_required_evidence = _missing_required_evidence(tasks=tasks, outputs=outputs)
        risk_items = _dedupe([*risk_items, *missing_required_evidence])
        test_evidence = _merge_test_evidence(tasks=tasks, outputs=outputs)
        execution_evidence = self._execution_evidence(tasks, outputs)
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
        recommended = self._recommended_action(
            accepted_count=len(accepted),
            rejected_count=len(rejected),
            pending_count=len(pending),
            blocked_count=len(blocked),
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


def _missing_required_evidence(
    *, tasks: list[AgentTeamTask], outputs: list[AgentTeamTaskOutput]
) -> list[str]:
    outputs_by_task: dict[str, list[AgentTeamTaskOutput]] = {}
    for output in outputs:
        outputs_by_task.setdefault(output.task_id, []).append(output)

    missing: list[str] = []
    for task in tasks:
        if task.status != AgentTeamTaskStatus.DONE or not task.evidence_required:
            continue
        available = "\n".join(
            _dedupe(
                [task.verification_summary or ""]
                + task.risk_notes
                + task.changed_files
                + [output.summary for output in outputs_by_task.get(task.task_id, [])]
                + [item for output in outputs_by_task.get(task.task_id, []) for item in output.test_evidence]
                + [item for output in outputs_by_task.get(task.task_id, []) for item in output.changed_files]
                + [item for output in outputs_by_task.get(task.task_id, []) for item in output.risk_notes]
                + [
                    value
                    for output in outputs_by_task.get(task.task_id, [])
                    for value in _artifact_payload_values(output.metadata)
                ]
            )
        ).lower()
        missing_items = [
            item
            for item in task.evidence_required
            if str(item).strip() and str(item).strip().lower() not in available
        ]
        if missing_items:
            label = task.title or task.goal
            missing.append(
                f"Missing required evidence for {task.role.value} task '{label}': {', '.join(missing_items)}."
            )
    return _dedupe(missing)

def _merge_test_evidence(
    *, tasks: list[AgentTeamTask], outputs: list[AgentTeamTaskOutput]
) -> list[str]:
    values: list[str] = []
    for output in outputs:
        values.extend(_explicit_evidence_items(output.test_evidence))
    values.extend(
        _explicit_evidence_items(
            _metadata_values(outputs, "test_evidence", "verification_evidence", "tests")
        )
    )
    values.extend(
        _explicit_evidence_items(
            [
                task.verification_summary or ""
                for task in tasks
                if task.role.value in _REVIEW_EVIDENCE_ROLES
            ]
        )
    )
    return _dedupe(values)


def _has_review_or_verification_evidence(
    *,
    tasks: list[AgentTeamTask],
    outputs: list[AgentTeamTaskOutput],
) -> bool:
    task_by_id = {task.task_id: task for task in tasks}
    for output in outputs:
        task = task_by_id.get(output.task_id)
        role = task.role.value if task is not None else ""
        if _explicit_evidence_items(
            [
                *output.test_evidence,
                *_values_for_keys(
                    output.metadata, "test_evidence", "verification_evidence", "tests"
                ),
            ]
        ):
            return True
        if role not in _REVIEW_EVIDENCE_ROLES and output.kind.value not in {
            "review_report",
            "test_report",
        }:
            continue
        if output.summary or output.artifact_id or output.metadata:
            return True
    return any(
        task.role.value in _REVIEW_EVIDENCE_ROLES and bool(task.verification_summary)
        for task in tasks
    )


def _build_final_answer(
    *,
    session: AgentTeamSession,
    tasks: list[AgentTeamTask],
    outputs: list[AgentTeamTaskOutput],
    open_questions: list[str],
    risk_items: list[str],
) -> dict[str, object]:
    source_output_ids = _dedupe(output.output_id for output in outputs if output.output_id)
    if not outputs:
        return {
            "status": AgentTeamFinalAnswerStatus.BLOCKED,
            "answer": (
                f"Agent Team 尚未产生可汇总的任务回传，无法回答：{session.goal}"
            ),
            "warnings": ["No task outputs are available for final answer synthesis."],
            "source_output_ids": source_output_ids,
        }

    if _has_fake_outputs(outputs):
        return {
            "status": AgentTeamFinalAnswerStatus.PLACEHOLDER,
            "answer": (
                "当前是模拟执行，只验证了 Agent Team 的拆解、运行和回传流程，"
                f"没有生成可交付的真实答案。请使用真实模型执行后再生成最终答案。\n\n目标：{session.goal}"
            ),
            "warnings": [
                "Current mission outputs were produced by fake execution mode.",
                "Fake execution validates workflow only; it must not be treated as a deliverable final answer.",
            ],
            "source_output_ids": source_output_ids,
        }

    if not _has_executor_or_writer_output(tasks=tasks, outputs=outputs):
        return {
            "status": AgentTeamFinalAnswerStatus.BLOCKED,
            "answer": (
                "Agent Team 已有部分任务回传，但缺少执行/撰写任务产出，"
                f"暂时无法形成面向用户目标的最终答案。\n\n目标：{session.goal}"
            ),
            "warnings": ["Missing executor or writer output for final answer synthesis."],
            "source_output_ids": source_output_ids,
        }

    body_items = _final_answer_content_items(
        _deliverable_outputs(tasks=tasks, outputs=outputs)
    )
    if not body_items:
        return {
            "status": AgentTeamFinalAnswerStatus.BLOCKED,
            "answer": (
                "Agent Team 已完成任务，但回传内容为空，无法形成最终答案。"
                f"\n\n目标：{session.goal}"
            ),
            "warnings": ["Task outputs did not include summary, raw_text, or parsed content."],
            "source_output_ids": source_output_ids,
        }

    warnings = _dedupe([*risk_items, *open_questions])
    sections = [
        f"目标：{session.goal}",
        "Agent Team 最终答案：",
        *[f"{index}. {item}" for index, item in enumerate(body_items, start=1)],
    ]
    if warnings:
        sections.extend(["需要注意：", *[f"- {item}" for item in warnings]])
    return {
        "status": AgentTeamFinalAnswerStatus.READY,
        "answer": "\n".join(sections),
        "warnings": warnings,
        "source_output_ids": source_output_ids,
    }


def _has_fake_outputs(outputs: list[AgentTeamTaskOutput]) -> bool:
    for output in outputs:
        execution = output.metadata.get("execution")
        execution_mode = execution.get("execution_mode") if isinstance(execution, dict) else None
        if str(execution_mode or "").strip().lower() == "fake":
            return True
        run = output.metadata.get("run")
        run_execution_mode = run.get("execution_mode") if isinstance(run, dict) else None
        if str(run_execution_mode or "").strip().lower() == "fake":
            return True
        if str(output.metadata.get("execution_mode") or "").strip().lower() == "fake":
            return True
        if output.summary.strip().lower().startswith("fake delegated"):
            return True
    return False


def _has_executor_or_writer_output(
    *, tasks: list[AgentTeamTask], outputs: list[AgentTeamTaskOutput]
) -> bool:
    task_by_id = {task.task_id: task for task in tasks}
    for output in outputs:
        task = task_by_id.get(output.task_id)
        if task is None:
            continue
        if task.role in {
            AgentTeamTaskRole.BACKEND_EXECUTOR,
            AgentTeamTaskRole.FRONTEND_EXECUTOR,
            AgentTeamTaskRole.WRITER,
        }:
            return True
    return False


def _deliverable_outputs(
    *, tasks: list[AgentTeamTask], outputs: list[AgentTeamTaskOutput]
) -> list[AgentTeamTaskOutput]:
    task_by_id = {task.task_id: task for task in tasks}
    deliverable_roles = {
        AgentTeamTaskRole.BACKEND_EXECUTOR,
        AgentTeamTaskRole.FRONTEND_EXECUTOR,
        AgentTeamTaskRole.WRITER,
    }
    deliverables = [
        output
        for output in outputs
        if task_by_id.get(output.task_id) is not None
        and task_by_id[output.task_id].role in deliverable_roles
    ]
    return deliverables or outputs


def _final_answer_content_items(outputs: list[AgentTeamTaskOutput]) -> list[str]:
    items: list[str] = []
    for output in outputs:
        items.extend(_artifact_payload_values(output.metadata))
        if output.summary:
            items.append(output.summary)
    return _dedupe(item.strip() for item in items if item and item.strip())


def _artifact_payload_values(metadata: dict[str, object]) -> list[str]:
    values: list[str] = []
    direct_payload = metadata.get("payload")
    if isinstance(direct_payload, dict):
        values.extend(_payload_values(direct_payload))
    artifacts = metadata.get("artifacts")
    if not isinstance(artifacts, list):
        return values
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        payload = artifact.get("payload")
        if not isinstance(payload, dict):
            continue
        values.extend(_payload_values(payload))
    return values


def _payload_values(payload: dict[str, object]) -> list[str]:
    values: list[str] = []
    raw_text = payload.get("raw_text")
    if isinstance(raw_text, str) and raw_text.strip():
        values.append(raw_text)
    parsed = payload.get("parsed")
    if isinstance(parsed, dict):
        extracted = False
        for key in ("summary", "final_answer", "answer", "findings"):
            raw = parsed.get(key)
            if isinstance(raw, str) and raw.strip():
                values.append(raw)
                extracted = True
            elif isinstance(raw, list):
                values.extend(str(item) for item in raw if item)
                extracted = True
        if not extracted:
            values.append(json.dumps(parsed, ensure_ascii=False, sort_keys=True))
    elif isinstance(parsed, list):
        values.extend(str(item) for item in parsed if item)
    elif isinstance(parsed, str) and parsed.strip():
        values.append(parsed)
    return values


def _explicit_evidence_items(values: list[str]) -> list[str]:
    return [value for value in values if _is_explicit_evidence(value)]


def _is_explicit_evidence(value: str) -> bool:
    text = value.strip().lower()
    return bool(text) and not text.startswith("delegated ") and not text.startswith("completed ") and text != "completed"


def _planning_risk_notes(
    *, session: AgentTeamSession, outputs: list[AgentTeamTaskOutput]
) -> list[str]:
    values: list[str] = []
    latest_bundle = session.latest_merge_bundle or {}
    if isinstance(latest_bundle, dict):
        values.extend(_values_for_keys(latest_bundle, "risk_items", "risk_notes", "risks"))
    for output in outputs:
        values.extend(
            _values_for_keys(
                output.metadata,
                "risk_items",
                "risk_notes",
                "risks",
                "open_risks",
            )
        )
        planning = output.metadata.get("planning")
        if isinstance(planning, dict):
            values.extend(
                _values_for_keys(
                    planning,
                    "risk_items",
                    "risk_notes",
                    "risks",
                    "open_risks",
                )
            )
    return _dedupe(values)


def _metadata_values(outputs: list[AgentTeamTaskOutput], *keys: str) -> list[str]:
    values: list[str] = []
    for output in outputs:
        values.extend(_values_for_keys(output.metadata, *keys))
    return _dedupe(values)


def _values_for_keys(payload: dict[str, object], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = payload.get(key)
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, list):
            values.extend(str(item) for item in raw if item)
    return values


__all__ = ["AgentTeamMergeMixin"]
