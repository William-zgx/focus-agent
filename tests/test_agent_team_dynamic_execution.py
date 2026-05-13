from __future__ import annotations

from focus_agent.agent_delegation_models import AgentArtifact, AgentTask
from focus_agent.agent_execution_types import SubagentConfig, SubagentRunResult
from focus_agent.agent_roles import AgentRole
from focus_agent.core.agent_team import (
    AgentTeamTaskRole,
    AgentTeamTaskStatus,
)
from focus_agent.services.agent_team import AgentTeamService


class MetadataExecutor:
    mode = "fake"

    def execute(self, task: AgentTask, config: SubagentConfig) -> SubagentRunResult:
        artifact = AgentArtifact(
            artifact_id=f"artifact-{task.task_id}",
            kind="evidence",
            title="Execution evidence",
            summary=f"completed {task.goal}",
            payload={
                "changed_files": [f"src/{task.task_id}.py"],
                "test_evidence": [f"pytest tests/{task.task_id}.py"],
                "risk_notes": [f"risk for {task.task_id}"],
            },
        )
        return SubagentRunResult(
            run_id=f"run-{task.task_id}",
            task_id=task.task_id,
            role=task.role,
            status="completed",
            summary=artifact.summary,
            artifacts=[artifact],
            execution_mode="fake",
        )


class FailingFirstExecutor:
    mode = "fake"

    def execute(self, task: AgentTask, config: SubagentConfig) -> SubagentRunResult:
        return SubagentRunResult(
            run_id=f"run-{task.task_id}",
            task_id=task.task_id,
            role=AgentRole.EXECUTOR,
            status="failed",
            summary="failed before dependents could run",
            error="root task failed",
            execution_mode="fake",
        )


class ContextCaptureExecutor:
    mode = "inline"

    def __init__(self) -> None:
        self.seen: dict[str, list[dict[str, object]]] = {}

    def execute(self, task: AgentTask, config: SubagentConfig) -> SubagentRunResult:
        self.seen[task.goal] = list(config.context_refs)
        artifact = AgentArtifact(
            artifact_id=f"artifact-{task.task_id}",
            kind="result",
            title=f"Result for {task.goal}",
            summary=f"completed {task.goal}",
            payload={"raw_text": f"result payload for {task.goal}"},
        )
        return SubagentRunResult(
            run_id=f"run-{task.task_id}",
            task_id=task.task_id,
            role=task.role,
            status="completed",
            summary=artifact.summary,
            artifacts=[artifact],
            execution_mode="inline",
        )
class ComplexDeliverableExecutor:
    mode = "inline"

    def execute(self, task: AgentTask, config: SubagentConfig) -> SubagentRunResult:
        payload_by_goal = {
            "plan checkout recovery": {
                "raw_text": "Internal execution plan: inspect checkout, add guardrails, then verify.",
                "parsed": {"summary": "Internal plan should stay out of the user deliverable."},
            },
            "implement checkout recovery": {
                "raw_text": "Checkout recovery now retries stale payment holds and records an audit event.",
                "parsed": {"final_answer": "Implemented checkout recovery with retry and audit coverage."},
            },
            "verify checkout recovery": {
                "raw_text": "Review rubric: payment hold retry was checked against regression risks.",
                "parsed": {"findings": ["pytest tests/checkout/test_recovery.py passed"]},
            },
        }
        payload = payload_by_goal[task.goal]
        artifact = AgentArtifact(
            artifact_id=f"artifact-{task.task_id}",
            kind="result",
            title=f"Result for {task.goal}",
            summary=f"completed {task.goal}",
            payload={
                **payload,
                "changed_files": ["src/checkout/recovery.py"],
                "test_evidence": ["pytest tests/checkout/test_recovery.py"],
            },
        )
        return SubagentRunResult(
            run_id=f"run-{task.task_id}",
            task_id=task.task_id,
            role=task.role,
            status="completed",
            summary=artifact.summary,
            artifacts=[artifact],
            execution_mode="inline",
        )




def test_dependent_task_receives_session_contract_and_dependency_outputs() -> None:
    executor = ContextCaptureExecutor()
    service = AgentTeamService(branch_service=None, executor=executor)
    session = service.create_session(
        user_id="user-1",
        goal="Build a DAG-aware mission result.",
    )
    producer = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.PLANNER,
        goal="produce upstream evidence",
        output_contract={"produces": ["evidence packet"]},
        create_branch=False,
    )
    service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.WRITER,
        goal="consume upstream evidence",
        dependencies=[producer.task_id],
        input_contract={"requires": ["evidence packet"]},
        output_contract={"produces": ["final answer"]},
        evidence_required=["dependency evidence used"],
        create_branch=False,
    )

    service.run_ready_tasks(session_id=session.session_id, user_id="user-1")

    context_refs = executor.seen["consume upstream evidence"]
    session_context = next(item for item in context_refs if item.get("type") == "agent_team_session")
    contract_context = next(item for item in context_refs if item.get("type") == "agent_team_task_contract")
    dependency_context = next(item for item in context_refs if item.get("type") == "agent_team_dependency_outputs")

    assert session_context["mission_goal"] == "Build a DAG-aware mission result."
    assert str(session_context["root_thread_id"]).startswith("agent-team-standalone-")
    assert contract_context["input_contract"] == {"requires": ["evidence packet"]}
    assert contract_context["output_contract"] == {"produces": ["final answer"]}
    assert contract_context["evidence_required"] == ["dependency evidence used"]
    assert dependency_context["dependency_task_ids"] == [producer.task_id]
    assert dependency_context["outputs"][0]["summary"] == "completed produce upstream evidence"


    service = AgentTeamService(branch_service=None, executor=ComplexDeliverableExecutor())
    session = service.create_session(
        root_thread_id="root-1",
        user_id="user-1",
        goal="Fix checkout recovery so stuck payment holds are retried and auditable.",
    )
    planner = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.PLANNER,
        goal="plan checkout recovery",
        create_branch=False,
    )
    implementer = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="implement checkout recovery",
        dependencies=[planner.task_id],
        create_branch=False,
    )
    service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.VERIFIER,
        goal="verify checkout recovery",
        dependencies=[implementer.task_id],
        create_branch=False,
    )

    _, tasks = service.run_ready_tasks(session_id=session.session_id, user_id="user-1")
    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert all(task.status == AgentTeamTaskStatus.DONE for task in tasks)
    assert bundle.final_answer_status == "ready"
    assert bundle.recommended_next_action == "merge"
    assert "Implemented checkout recovery with retry and audit coverage." in bundle.final_answer
    assert "Checkout recovery now retries stale payment holds" in bundle.final_answer
    assert "Internal execution plan" not in bundle.final_answer
    assert "Review rubric" not in bundle.final_answer
    assert bundle.test_evidence == ["pytest tests/checkout/test_recovery.py"]


def test_run_ready_tasks_advances_complete_dag_and_records_output_metadata() -> None:
    service = AgentTeamService(branch_service=None, executor=MetadataExecutor())
    session = service.create_session(root_thread_id="root-1", user_id="user-1", goal="Run DAG")
    root = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="root",
        create_branch=False,
    )
    left = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="left",
        dependencies=[root.task_id],
        create_branch=False,
    )
    right = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.TEST_ENGINEER,
        goal="right",
        dependencies=[root.task_id],
        create_branch=False,
    )
    leaf = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.REVIEWER,
        goal="leaf",
        dependencies=[left.task_id, right.task_id],
        create_branch=False,
    )

    _, tasks = service.run_ready_tasks(session_id=session.session_id, user_id="user-1")

    by_id = {task.task_id: task for task in tasks}
    assert all(task.status == AgentTeamTaskStatus.DONE for task in by_id.values())
    assert by_id[leaf.task_id].changed_files == [f"src/{leaf.task_id}.py"]
    assert by_id[leaf.task_id].risk_notes == [f"risk for {leaf.task_id}"]

    output = service.list_task_outputs(task_id=leaf.task_id, user_id="user-1")[0]
    assert output.changed_files == [f"src/{leaf.task_id}.py"]
    assert output.test_evidence == [
        f"delegated fake run run-{leaf.task_id}: completed",
        f"pytest tests/{leaf.task_id}.py",
    ]
    assert output.metadata["scheduler"]["wave"] == 3
    assert output.metadata["execution"]["execution_status"] == "completed"

    view = service.get_session_view(session_id=session.session_id, user_id="user-1")
    assert view["scheduler"]["ready_task_ids"] == []
    assert view["scheduler"]["waiting_task_ids"] == []


def test_run_ready_tasks_does_not_start_dependents_after_failed_dependency() -> None:
    service = AgentTeamService(branch_service=None, executor=FailingFirstExecutor())
    session = service.create_session(
        root_thread_id="root-1", user_id="user-1", goal="Stop failed DAG"
    )
    root = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="root",
        create_branch=False,
    )
    dependent = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.TEST_ENGINEER,
        goal="dependent",
        dependencies=[root.task_id],
        create_branch=False,
    )

    _, tasks = service.run_ready_tasks(session_id=session.session_id, user_id="user-1")

    by_id = {task.task_id: task for task in tasks}
    assert by_id[root.task_id].status == AgentTeamTaskStatus.FAILED
    assert by_id[dependent.task_id].status == AgentTeamTaskStatus.PENDING
    assert service.list_task_outputs(task_id=dependent.task_id, user_id="user-1") == []


def test_merge_bundle_requests_changes_without_review_or_verification_evidence() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(root_thread_id="root-1", user_id="user-1", goal="Gate merge")
    task = service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="backend only",
        create_branch=False,
    )
    service.record_task_output(
        task_id=task.task_id,
        user_id="user-1",
        summary="backend patch completed",
        metadata={"planning": {"risks": ["planner flagged rollout risk"]}},
    )
    service.update_task(
        task_id=task.task_id,
        user_id="user-1",
        status=AgentTeamTaskStatus.DONE,
    )

    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert bundle.recommended_next_action == "request_changes"
    assert "planner flagged rollout risk" in bundle.risk_items
    assert any("Missing review/verification evidence" in item for item in bundle.risk_items)


def test_merge_bundle_does_not_treat_synthetic_run_status_as_verification() -> None:
    service = AgentTeamService(branch_service=None)
    session = service.create_session(
        root_thread_id="root-1", user_id="user-1", goal="Backend only run"
    )
    service.create_task(
        session_id=session.session_id,
        user_id="user-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="backend only",
        create_branch=False,
    )

    service.run_ready_tasks(session_id=session.session_id, user_id="user-1")
    bundle = service.prepare_merge_bundle(session_id=session.session_id, user_id="user-1")

    assert bundle.test_evidence == []
    assert bundle.recommended_next_action == "request_changes"
    assert any("Missing review/verification evidence" in item for item in bundle.risk_items)
