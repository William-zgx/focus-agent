"""Validation and pure state-transition helpers for Agent Team revisions."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

import networkx as nx

from .agent_team_revision import (
    AgentTeamRevision,
    AgentTeamRevisionTask,
    RevisionTaskStatus,
)


class DAGValidationIssueCode(StrEnum):
    """Stable codes for revision DAG validation failures."""

    DUPLICATE_TASK_ID = "duplicate_task_id"
    UNKNOWN_NODE = "unknown_node"
    SELF_DEPENDENCY = "self_dependency"
    DUPLICATE_EDGE = "duplicate_edge"
    CYCLE = "cycle"
    DEPENDENCY_CONTRACT_MISMATCH = "dependency_contract_mismatch"
    WRITE_SCOPE_REQUIRED = "write_scope_required"
    RESOURCE_CLAIM_REQUIRED = "resource_claim_required"


@dataclass(frozen=True, slots=True)
class DAGValidationIssue:
    """One actionable DAG validation problem."""

    code: DAGValidationIssueCode
    message: str
    task_id: str | None = None
    dependency_id: str | None = None
    cycle: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DAGValidationResult:
    """Structured result returned by :func:`validate_agent_team_revision_dag`."""

    revision_id: str
    issues: tuple[DAGValidationIssue, ...] = ()
    topological_order: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.issues

    def raise_for_errors(self) -> DAGValidationResult:
        """Raise a typed exception if the revision has invalid DAG semantics."""
        if not self.is_valid:
            raise AgentTeamDAGValidationError(self)
        return self


class AgentTeamDAGValidationError(ValueError):
    """Raised when a revision fails Agent Team DAG validation."""

    def __init__(self, result: DAGValidationResult) -> None:
        self.result = result
        messages = "; ".join(issue.message for issue in result.issues)
        super().__init__(
            f"Agent Team revision {result.revision_id!r} has invalid DAG semantics: {messages}"
        )


class InvalidTaskStateTransitionError(ValueError):
    """Raised when a requested revision task state transition is not legal."""


@dataclass(frozen=True, slots=True)
class TaskStateTransitionResult:
    """A requested state transition and its resulting immutable task snapshot."""

    task_id: str
    previous_status: RevisionTaskStatus
    status: RevisionTaskStatus
    task: AgentTeamRevisionTask

    @property
    def changed(self) -> bool:
        return self.previous_status != self.status


@dataclass(frozen=True, slots=True)
class FailurePropagationResult:
    """The direct and transitive downstream tasks blocked by a terminal failure."""

    failed_task_id: str
    failed_status: RevisionTaskStatus
    blocked_task_ids: tuple[str, ...]
    revision: AgentTeamRevision


_WRITABLE_TASK_KINDS = frozenset({"implementation", "write", "writing", "code_change"})
_FAILURE_STATUSES = frozenset(
    {
        RevisionTaskStatus.BLOCKED,
        RevisionTaskStatus.CANCELLED,
        RevisionTaskStatus.FAILED,
    }
)
_ALLOWED_TRANSITIONS: Mapping[RevisionTaskStatus, frozenset[RevisionTaskStatus]] = {
    RevisionTaskStatus.PENDING: frozenset(
        {
            RevisionTaskStatus.QUEUED,
            RevisionTaskStatus.BLOCKED,
            RevisionTaskStatus.CANCELLED,
        }
    ),
    RevisionTaskStatus.QUEUED: frozenset(
        {
            RevisionTaskStatus.PENDING,
            RevisionTaskStatus.RUNNING,
            RevisionTaskStatus.BLOCKED,
            RevisionTaskStatus.CANCELLED,
        }
    ),
    RevisionTaskStatus.RUNNING: frozenset(
        {
            RevisionTaskStatus.DONE,
            RevisionTaskStatus.FAILED,
            RevisionTaskStatus.BLOCKED,
            RevisionTaskStatus.CANCELLED,
        }
    ),
    RevisionTaskStatus.BLOCKED: frozenset(
        {RevisionTaskStatus.PENDING, RevisionTaskStatus.CANCELLED}
    ),
    RevisionTaskStatus.DONE: frozenset(),
    RevisionTaskStatus.FAILED: frozenset(
        {RevisionTaskStatus.PENDING, RevisionTaskStatus.CANCELLED}
    ),
    RevisionTaskStatus.CANCELLED: frozenset(),
}


def validate_agent_team_revision_dag(revision: AgentTeamRevision) -> DAGValidationResult:
    """Validate a revision DAG without modifying its tasks or integration paths."""
    issues: list[DAGValidationIssue] = []
    tasks_by_id: dict[str, AgentTeamRevisionTask] = {}
    duplicate_ids: set[str] = set()
    for task in revision.tasks:
        if task.task_id in tasks_by_id:
            duplicate_ids.add(task.task_id)
        else:
            tasks_by_id[task.task_id] = task
    for task_id in sorted(duplicate_ids):
        issues.append(
            DAGValidationIssue(
                code=DAGValidationIssueCode.DUPLICATE_TASK_ID,
                task_id=task_id,
                message=f"Task {task_id!r} appears more than once in the revision.",
            )
        )

    graph = nx.DiGraph()
    graph.add_nodes_from(tasks_by_id)
    for task in tasks_by_id.values():
        _validate_task_contract(task, issues)
        seen_dependencies: set[str] = set()
        for dependency_id in task.dependencies:
            if dependency_id in seen_dependencies:
                issues.append(
                    DAGValidationIssue(
                        code=DAGValidationIssueCode.DUPLICATE_EDGE,
                        task_id=task.task_id,
                        dependency_id=dependency_id,
                        message=(
                            f"Task {task.task_id!r} declares dependency {dependency_id!r} more than once."
                        ),
                    )
                )
                continue
            seen_dependencies.add(dependency_id)
            if dependency_id == task.task_id:
                issues.append(
                    DAGValidationIssue(
                        code=DAGValidationIssueCode.SELF_DEPENDENCY,
                        task_id=task.task_id,
                        dependency_id=dependency_id,
                        message=f"Task {task.task_id!r} cannot depend on itself.",
                    )
                )
                continue
            if dependency_id not in tasks_by_id:
                issues.append(
                    DAGValidationIssue(
                        code=DAGValidationIssueCode.UNKNOWN_NODE,
                        task_id=task.task_id,
                        dependency_id=dependency_id,
                        message=(
                            f"Task {task.task_id!r} depends on unknown task {dependency_id!r}."
                        ),
                    )
                )
                continue
            graph.add_edge(dependency_id, task.task_id)

    if nx.is_directed_acyclic_graph(graph):
        topological_order = tuple(nx.topological_sort(graph))
    else:
        topological_order = ()
        for cycle in _normalized_cycles(graph):
            issues.append(
                DAGValidationIssue(
                    code=DAGValidationIssueCode.CYCLE,
                    cycle=cycle,
                    message=f"Task dependency graph contains a cycle: {list(cycle)!r}.",
                )
            )
    return DAGValidationResult(
        revision_id=revision.revision_id,
        issues=tuple(issues),
        topological_order=topological_order,
    )


def assert_valid_agent_team_revision_dag(revision: AgentTeamRevision) -> DAGValidationResult:
    """Validate a revision and raise :class:`AgentTeamDAGValidationError` on failure."""
    return validate_agent_team_revision_dag(revision).raise_for_errors()


def validate_task_state_transition(
    task: AgentTeamRevisionTask,
    next_status: RevisionTaskStatus | str,
) -> TaskStateTransitionResult:
    """Validate one immutable task status transition and return its replacement."""
    status = _as_status(next_status)
    if status == task.status:
        return TaskStateTransitionResult(
            task_id=task.task_id,
            previous_status=task.status,
            status=status,
            task=task,
        )
    if status not in _ALLOWED_TRANSITIONS[task.status]:
        raise InvalidTaskStateTransitionError(
            f"Task {task.task_id!r} cannot transition from {task.status.value!r} "
            f"to {status.value!r}."
        )
    updated = AgentTeamRevisionTask(
        task_id=task.task_id,
        dependencies=task.dependencies,
        input_contract=task.input_contract,
        write_scope=task.write_scope,
        resource_claims=task.resource_claims,
        task_kind=task.task_kind,
        writes=task.writes,
        status=status,
        last_error=task.last_error,
    )
    return TaskStateTransitionResult(
        task_id=task.task_id,
        previous_status=task.status,
        status=status,
        task=updated,
    )


def propagate_downstream_failure(
    revision: AgentTeamRevision,
    *,
    failed_task_id: str,
    failed_status: RevisionTaskStatus | str = RevisionTaskStatus.FAILED,
) -> FailurePropagationResult:
    """Return a new revision that blocks all unfinished transitive dependents."""
    status = _as_status(failed_status)
    if status not in _FAILURE_STATUSES:
        raise InvalidTaskStateTransitionError(
            "Failure propagation requires a blocked, cancelled, or failed source status."
        )
    source = revision.task_by_id(failed_task_id)
    source_transition = validate_task_state_transition(source, status)
    children = _children_by_dependency(revision.tasks)
    dependent_ids = _transitive_children(failed_task_id, children)
    blocked_ids: list[str] = []
    updated_tasks: list[AgentTeamRevisionTask] = []
    for task in revision.tasks:
        if task.task_id == failed_task_id:
            updated_tasks.append(source_transition.task)
            continue
        if task.task_id not in dependent_ids or task.status in {
            RevisionTaskStatus.DONE,
            RevisionTaskStatus.CANCELLED,
            RevisionTaskStatus.FAILED,
        }:
            updated_tasks.append(task)
            continue
        transition = validate_task_state_transition(task, RevisionTaskStatus.BLOCKED)
        updated_tasks.append(transition.task)
        if transition.changed:
            blocked_ids.append(task.task_id)
    return FailurePropagationResult(
        failed_task_id=failed_task_id,
        failed_status=status,
        blocked_task_ids=tuple(blocked_ids),
        revision=AgentTeamRevision(
            revision_id=revision.revision_id,
            session_id=revision.session_id,
            sequence=revision.sequence,
            tasks=tuple(updated_tasks),
            parent_revision_id=revision.parent_revision_id,
            metadata=revision.metadata,
        ),
    )


def _validate_task_contract(task: AgentTeamRevisionTask, issues: list[DAGValidationIssue]) -> None:
    from_dependencies = _contract_dependencies(task.input_contract)
    if from_dependencies != task.dependencies:
        issues.append(
            DAGValidationIssue(
                code=DAGValidationIssueCode.DEPENDENCY_CONTRACT_MISMATCH,
                task_id=task.task_id,
                message=(
                    f"Task {task.task_id!r} input_contract.from_dependencies "
                    f"{list(from_dependencies)!r} does not match dependencies "
                    f"{list(task.dependencies)!r}."
                ),
            )
        )
    if not _is_write_task(task):
        return
    if not task.write_scope:
        issues.append(
            DAGValidationIssue(
                code=DAGValidationIssueCode.WRITE_SCOPE_REQUIRED,
                task_id=task.task_id,
                message=f"Write task {task.task_id!r} requires a non-empty write_scope.",
            )
        )
    if not task.resource_claims:
        issues.append(
            DAGValidationIssue(
                code=DAGValidationIssueCode.RESOURCE_CLAIM_REQUIRED,
                task_id=task.task_id,
                message=f"Write task {task.task_id!r} requires at least one resource claim.",
            )
        )


def _contract_dependencies(contract: Mapping[str, object]) -> tuple[str, ...]:
    raw_dependencies = contract.get("from_dependencies")
    if raw_dependencies is None:
        return ()
    if isinstance(raw_dependencies, str):
        return (raw_dependencies.strip(),) if raw_dependencies.strip() else ()
    if isinstance(raw_dependencies, Iterable):
        return tuple(str(value).strip() for value in raw_dependencies if str(value).strip())
    return (str(raw_dependencies).strip(),) if str(raw_dependencies).strip() else ()


def _is_write_task(task: AgentTeamRevisionTask) -> bool:
    return task.is_write_task or str(task.task_kind or "").strip().lower() in _WRITABLE_TASK_KINDS


def _normalized_cycles(graph: nx.DiGraph) -> tuple[tuple[str, ...], ...]:
    cycles = {
        _normalize_cycle(tuple(str(node) for node in cycle))
        for cycle in nx.simple_cycles(graph)
        if cycle
    }
    return tuple(sorted(cycles))


def _normalize_cycle(cycle: tuple[str, ...]) -> tuple[str, ...]:
    smallest_index = min(range(len(cycle)), key=cycle.__getitem__)
    return cycle[smallest_index:] + cycle[:smallest_index]


def _as_status(status: RevisionTaskStatus | str) -> RevisionTaskStatus:
    try:
        return RevisionTaskStatus(status)
    except ValueError as exc:
        raise InvalidTaskStateTransitionError(f"Unsupported task status: {status!r}.") from exc


def _children_by_dependency(
    tasks: Iterable[AgentTeamRevisionTask],
) -> dict[str, tuple[str, ...]]:
    children: dict[str, list[str]] = {}
    for task in tasks:
        for dependency_id in task.dependencies:
            children.setdefault(dependency_id, []).append(task.task_id)
    return {task_id: tuple(task_ids) for task_id, task_ids in children.items()}


def _transitive_children(
    task_id: str,
    children: Mapping[str, tuple[str, ...]],
) -> set[str]:
    blocked: set[str] = set()
    queue = deque(children.get(task_id, ()))
    while queue:
        child_id = queue.popleft()
        if child_id in blocked:
            continue
        blocked.add(child_id)
        queue.extend(children.get(child_id, ()))
    return blocked


__all__ = [
    "AgentTeamDAGValidationError",
    "DAGValidationIssue",
    "DAGValidationIssueCode",
    "DAGValidationResult",
    "FailurePropagationResult",
    "InvalidTaskStateTransitionError",
    "TaskStateTransitionResult",
    "assert_valid_agent_team_revision_dag",
    "propagate_downstream_failure",
    "validate_agent_team_revision_dag",
    "validate_task_state_transition",
]
