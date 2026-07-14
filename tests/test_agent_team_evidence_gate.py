from __future__ import annotations

import pytest

from focus_agent.core.agent_team import (
    AgentTeamArtifactKind,
    AgentTeamFinalAnswerStatus,
    AgentTeamRecommendedAction,
    AgentTeamTask,
    AgentTeamTaskOutput,
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)
from focus_agent.services.agent_team import AgentTeamService


def _evidence(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "execution_class": "real_tool_loop",
        "evidence_level": "verified",
        "evidence_verdict": "verified",
        "sandbox_backend": "docker",
        "fallback_used": False,
        "commands": [{"command": "pytest -q", "exit_code": 0}],
        "worktree_hash": "worktree-sha256",
        "diff_hash": "diff-sha256",
    }
    payload.update(updates)
    return payload


def _create_service_with_verified_task(
    *,
    evidence: dict[str, object] | None = None,
    execution_class: str = "sandbox_verified",
    evidence_level: str = "verified",
    evidence_verdict: str = "verified",
) -> tuple[AgentTeamService, str]:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(user_id="user-1", goal="Merge evidence-gated change")
    task = AgentTeamTask(
        task_id="write-task",
        session_id=session.session_id,
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Implement the evidence-gated change",
        status=AgentTeamTaskStatus.DONE,
        created_at="2026-07-13T00:00:00+00:00",
        updated_at="2026-07-13T00:00:00+00:00",
    )
    output = AgentTeamTaskOutput(
        output_id="write-output",
        task_id=task.task_id,
        kind=AgentTeamArtifactKind.PATCH_SUMMARY,
        summary="Implemented the evidence-gated change.",
        execution_class=execution_class,
        evidence_level=evidence_level,
        evidence_verdict=evidence_verdict,
        sandbox_id="sandbox-1" if execution_class == "sandbox_verified" else None,
        metadata={"evidence": _evidence() if evidence is None else evidence},
        created_at="2026-07-13T00:01:00+00:00",
    )
    service.repository.create_task(task)
    service.repository.add_task_output(output)
    _add_legacy_verifier(service=service, session_id=session.session_id)
    return service, session.session_id


def _add_legacy_verifier(*, service: AgentTeamService, session_id: str) -> None:
    task = AgentTeamTask(
        task_id="verify-task",
        session_id=session_id,
        role=AgentTeamTaskRole.VERIFIER,
        goal="Review the change",
        status=AgentTeamTaskStatus.DONE,
        created_at="2026-07-13T00:02:00+00:00",
        updated_at="2026-07-13T00:02:00+00:00",
    )
    output = AgentTeamTaskOutput(
        output_id="verify-output",
        task_id=task.task_id,
        kind=AgentTeamArtifactKind.TEST_REPORT,
        summary="Verifier reviewed the change.",
        test_evidence=["pytest -q"],
        created_at="2026-07-13T00:03:00+00:00",
    )
    service.repository.create_task(task)
    service.repository.add_task_output(output)


def test_strong_evidence_gate_allows_verified_docker_execution() -> None:
    service, session_id = _create_service_with_verified_task()

    bundle = service.prepare_merge_bundle(session_id=session_id, user_id="user-1")

    assert bundle.recommended_next_action == AgentTeamRecommendedAction.MERGE
    assert bundle.final_answer_status == AgentTeamFinalAnswerStatus.READY
    assert not any("Strong evidence gate rejected" in item for item in bundle.risk_items)

    decision = service.apply_merge_decision(
        session_id=session_id,
        user_id="user-1",
        approved=True,
        action=AgentTeamRecommendedAction.MERGE,
    )

    assert decision.approved is True
    assert decision.action == AgentTeamRecommendedAction.MERGE


@pytest.mark.parametrize(
    ("evidence", "expected_reason"),
    [
        (
            _evidence(fallback_used=True),
            "fallback_used must be false",
        ),
        (
            _evidence(commands=[{"command": "pytest -q", "exit_code": 1}]),
            "successful command exit_code=0",
        ),
        (
            _evidence(diff_hash=""),
            "diff hash evidence is required",
        ),
    ],
)
def test_strong_evidence_gate_requests_changes_for_incomplete_runtime_proof(
    evidence: dict[str, object],
    expected_reason: str,
) -> None:
    service, session_id = _create_service_with_verified_task(evidence=evidence)

    bundle = service.prepare_merge_bundle(session_id=session_id, user_id="user-1")

    assert bundle.recommended_next_action == AgentTeamRecommendedAction.REQUEST_CHANGES
    assert bundle.final_answer_status == AgentTeamFinalAnswerStatus.BLOCKED
    assert any(expected_reason in item for item in bundle.risk_items)

    decision = service.apply_merge_decision(
        session_id=session_id,
        user_id="user-1",
        approved=True,
        action=AgentTeamRecommendedAction.MERGE,
    )

    assert decision.approved is False
    assert decision.action == AgentTeamRecommendedAction.REQUEST_CHANGES


@pytest.mark.parametrize("execution_class", ["model_text", "fake"])
def test_strong_evidence_gate_rejects_model_text_and_fake_claims(execution_class: str) -> None:
    evidence_level = "verified" if execution_class == "model_text" else "synthetic"
    evidence_verdict = "verified" if execution_class == "model_text" else "unknown"
    evidence = _evidence(execution_class=execution_class)
    service, session_id = _create_service_with_verified_task(
        evidence=evidence,
        execution_class=execution_class,
        evidence_level=evidence_level,
        evidence_verdict=evidence_verdict,
    )

    bundle = service.prepare_merge_bundle(session_id=session_id, user_id="user-1")

    assert bundle.recommended_next_action == AgentTeamRecommendedAction.REQUEST_CHANGES
    assert any(f"execution_class is {execution_class}" in item for item in bundle.risk_items)
    assert bundle.final_answer_status != AgentTeamFinalAnswerStatus.READY


def test_strong_evidence_gate_rejects_explicit_fake_contract_without_metadata_evidence() -> None:
    service, session_id = _create_service_with_verified_task(
        evidence={},
        execution_class="fake",
        evidence_level="synthetic",
        evidence_verdict="unknown",
    )

    bundle = service.prepare_merge_bundle(session_id=session_id, user_id="user-1")

    assert bundle.recommended_next_action == AgentTeamRecommendedAction.REQUEST_CHANGES
    assert any("execution_class is fake" in item for item in bundle.risk_items)


def test_strong_evidence_gate_rejects_declared_evidence_without_execution_class() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(user_id="user-1", goal="Require an execution class")
    task = AgentTeamTask(
        task_id="undeclared-class-task",
        session_id=session.session_id,
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Implement the evidence-gated change",
        status=AgentTeamTaskStatus.DONE,
        created_at="2026-07-13T00:00:00+00:00",
        updated_at="2026-07-13T00:00:00+00:00",
    )
    output = AgentTeamTaskOutput(
        output_id="undeclared-class-output",
        task_id=task.task_id,
        kind=AgentTeamArtifactKind.PATCH_SUMMARY,
        summary="Implemented the evidence-gated change.",
        metadata={"evidence": {"sandbox_backend": "docker", "fallback_used": False}},
        created_at="2026-07-13T00:01:00+00:00",
    )
    service.repository.create_task(task)
    service.repository.add_task_output(output)
    _add_legacy_verifier(service=service, session_id=session.session_id)

    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert bundle.recommended_next_action == AgentTeamRecommendedAction.REQUEST_CHANGES
    assert any("execution_class is required" in item for item in bundle.risk_items)


def test_legacy_outputs_remain_compatible_without_verified_upgrade() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(user_id="user-1", goal="Keep legacy merge behavior")
    task = AgentTeamTask(
        task_id="legacy-write-task",
        session_id=session.session_id,
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Implement the legacy change",
        status=AgentTeamTaskStatus.DONE,
        created_at="2026-07-13T00:00:00+00:00",
        updated_at="2026-07-13T00:00:00+00:00",
    )
    output = AgentTeamTaskOutput(
        output_id="legacy-write-output",
        task_id=task.task_id,
        kind=AgentTeamArtifactKind.PATCH_SUMMARY,
        summary="Implemented the legacy change.",
        created_at="2026-07-13T00:01:00+00:00",
    )
    service.repository.create_task(task)
    service.repository.add_task_output(output)
    _add_legacy_verifier(service=service, session_id=session.session_id)

    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert bundle.recommended_next_action == AgentTeamRecommendedAction.MERGE
    assert bundle.final_answer_status == AgentTeamFinalAnswerStatus.READY
    assert not any("Strong evidence gate" in item for item in bundle.risk_items)
