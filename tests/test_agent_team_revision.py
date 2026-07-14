from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from focus_agent.services.agent_team_dag_validator import (
    AgentTeamDAGValidationError,
    DAGValidationIssueCode,
    InvalidTaskStateTransitionError,
    propagate_downstream_failure,
    validate_agent_team_revision_dag,
    validate_task_state_transition,
)
from focus_agent.services.agent_team_revision import (
    AgentTeamRevision,
    AgentTeamRevisionTask,
    RevisionTaskStatus,
)


def _task(
    task_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    from_dependencies: tuple[str, ...] | None = None,
    task_kind: str | None = None,
    writes: bool = False,
    write_scope: tuple[str, ...] = (),
    resource_claims: tuple[str, ...] = (),
    status: RevisionTaskStatus = RevisionTaskStatus.PENDING,
) -> AgentTeamRevisionTask:
    return AgentTeamRevisionTask(
        task_id=task_id,
        dependencies=dependencies,
        input_contract={
            "from_dependencies": from_dependencies
            if from_dependencies is not None
            else dependencies
        },
        task_kind=task_kind,
        writes=writes,
        write_scope=write_scope,
        resource_claims=resource_claims,
        status=status,
    )


def _revision(*tasks: AgentTeamRevisionTask) -> AgentTeamRevision:
    return AgentTeamRevision(
        revision_id="rev-1",
        session_id="session-1",
        sequence=1,
        tasks=tasks,
        metadata={"source": {"planner": "v1"}},
    )


def test_revision_dto_deep_freezes_task_and_metadata_containers() -> None:
    mutable_contract = {"from_dependencies": ["plan"]}
    mutable_metadata = {"source": {"planner": "v1"}}
    task = AgentTeamRevisionTask(task_id="implement", input_contract=mutable_contract)
    revision = AgentTeamRevision(
        revision_id="rev-1",
        session_id="session-1",
        sequence=1,
        tasks=(task,),
        metadata=mutable_metadata,
    )

    mutable_contract["from_dependencies"].append("other")
    mutable_metadata["source"]["planner"] = "changed"

    assert revision.tasks[0].input_contract["from_dependencies"] == ("plan",)
    assert revision.metadata["source"]["planner"] == "v1"
    with pytest.raises(FrozenInstanceError):
        revision.sequence = 2  # type: ignore[misc]
    with pytest.raises(TypeError):
        revision.metadata["new"] = "value"  # type: ignore[index]


def test_validator_accepts_complete_acyclic_revision_and_returns_topological_order() -> None:
    revision = _revision(
        _task("plan"),
        _task(
            "implement",
            dependencies=("plan",),
            task_kind="implementation",
            write_scope=("src/**",),
            resource_claims=("file:src/**",),
        ),
        _task("verify", dependencies=("implement",)),
    )

    result = validate_agent_team_revision_dag(revision)

    assert result.is_valid
    assert result.topological_order == ("plan", "implement", "verify")
    assert result.raise_for_errors() is result


@pytest.mark.parametrize(
    ("task", "expected_code"),
    [
        (_task("consumer", dependencies=("missing",)), DAGValidationIssueCode.UNKNOWN_NODE),
        (_task("self", dependencies=("self",)), DAGValidationIssueCode.SELF_DEPENDENCY),
        (
            _task("duplicate-edge", dependencies=("plan", "plan")),
            DAGValidationIssueCode.DUPLICATE_EDGE,
        ),
        (
            _task(
                "mismatched-contract",
                dependencies=("plan",),
                from_dependencies=("other",),
            ),
            DAGValidationIssueCode.DEPENDENCY_CONTRACT_MISMATCH,
        ),
    ],
)
def test_validator_reports_local_dag_contract_violations(
    task: AgentTeamRevisionTask,
    expected_code: DAGValidationIssueCode,
) -> None:
    revision = _revision(_task("plan"), task)

    result = validate_agent_team_revision_dag(revision)

    assert expected_code in {issue.code for issue in result.issues}
    with pytest.raises(AgentTeamDAGValidationError) as exc_info:
        result.raise_for_errors()
    assert exc_info.value.result == result


def test_validator_reports_duplicate_task_ids_and_cycles() -> None:
    revision = _revision(
        _task("duplicate"),
        _task("duplicate"),
        _task("left", dependencies=("right",)),
        _task("right", dependencies=("left",)),
    )

    result = validate_agent_team_revision_dag(revision)

    codes = {issue.code for issue in result.issues}
    assert DAGValidationIssueCode.DUPLICATE_TASK_ID in codes
    cycle = next(issue for issue in result.issues if issue.code == DAGValidationIssueCode.CYCLE)
    assert cycle.cycle == ("left", "right")
    assert result.topological_order == ()


def test_validator_requires_scope_and_claim_for_write_tasks() -> None:
    revision = _revision(_task("write", task_kind="implementation"))

    result = validate_agent_team_revision_dag(revision)

    assert {issue.code for issue in result.issues} == {
        DAGValidationIssueCode.WRITE_SCOPE_REQUIRED,
        DAGValidationIssueCode.RESOURCE_CLAIM_REQUIRED,
    }


def test_task_state_transition_validation_is_explicit_and_conservative() -> None:
    pending = _task("task")

    queued = validate_task_state_transition(pending, RevisionTaskStatus.QUEUED)
    running = validate_task_state_transition(queued.task, RevisionTaskStatus.RUNNING)
    done = validate_task_state_transition(running.task, RevisionTaskStatus.DONE)

    assert queued.changed
    assert done.task.status == RevisionTaskStatus.DONE
    with pytest.raises(InvalidTaskStateTransitionError, match="done.*pending"):
        validate_task_state_transition(done.task, RevisionTaskStatus.PENDING)
    with pytest.raises(InvalidTaskStateTransitionError, match="pending.*done"):
        validate_task_state_transition(pending, RevisionTaskStatus.DONE)


def test_failure_propagation_blocks_unfinished_transitive_dependents_only() -> None:
    revision = _revision(
        _task("root", status=RevisionTaskStatus.RUNNING),
        _task("middle", dependencies=("root",)),
        _task("leaf", dependencies=("middle",)),
        _task("completed", dependencies=("root",), status=RevisionTaskStatus.DONE),
    )

    result = propagate_downstream_failure(revision, failed_task_id="root")

    assert revision.task_by_id("root").status == RevisionTaskStatus.RUNNING
    assert result.revision.task_by_id("root").status == RevisionTaskStatus.FAILED
    assert result.revision.task_by_id("middle").status == RevisionTaskStatus.BLOCKED
    assert result.revision.task_by_id("leaf").status == RevisionTaskStatus.BLOCKED
    assert result.revision.task_by_id("completed").status == RevisionTaskStatus.DONE
    assert result.blocked_task_ids == ("middle", "leaf")
