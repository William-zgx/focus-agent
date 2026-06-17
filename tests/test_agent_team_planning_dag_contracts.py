from focus_agent.core.agent_team import AgentTeamTaskRole
from focus_agent.services.agent_team_planning_dag_contracts import (
    _resource_claims_for_deliverable,
)
from focus_agent.services.agent_team_planning_models import MissionDeliverable


def _deliverable(
    *,
    task_type: str = "execution",
    task_kind: str | None = None,
    capability_requirements: list[str] | None = None,
    resource_claims: list[str] | None = None,
    write_scope: list[str] | None = None,
) -> MissionDeliverable:
    return MissionDeliverable(
        key="task",
        title="Task",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Do the task",
        task_type=task_type,
        task_kind=task_kind,
        capability_requirements=capability_requirements or [],
        resource_claims=resource_claims or [],
        write_scope=write_scope or [],
        planning_rationale="Test fixture.",
    )


def test_execution_deliverable_claims_thread_sandbox_resource() -> None:
    claims = _resource_claims_for_deliverable(
        _deliverable(
            task_type="verification",
            capability_requirements=["pytest execution"],
            write_scope=["src/**"],
        ),
        sandbox_id="thread-thread-1",
    )

    assert claims == ["file:src/**", "sandbox:thread-thread-1"]


def test_explicit_deliverable_claims_are_preserved_and_sandbox_claim_is_added() -> None:
    claims = _resource_claims_for_deliverable(
        _deliverable(
            task_type="execution",
            resource_claims=["file:src/app.py"],
        ),
        sandbox_id="thread-thread-1",
    )

    assert claims == ["file:src/app.py", "sandbox:thread-thread-1"]


def test_non_execution_deliverable_does_not_claim_sandbox() -> None:
    claims = _resource_claims_for_deliverable(
        _deliverable(
            task_type="research",
            capability_requirements=["synthesis"],
            write_scope=[],
        ),
        sandbox_id="thread-thread-1",
    )

    assert claims == []
