"""DAG wave scheduling for feature-flagged Agent Team execution."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable

import networkx as nx

from .contracts import DAGTaskNode
from .errors import DAGValidationError


class DAGScheduler:
    """Compute bounded, resource-safe execution waves for Agent Team tasks."""

    def __init__(self, tasks: Iterable[DAGTaskNode], *, max_parallel_runs: int = 2) -> None:
        self._tasks = {task.task_id: task for task in tasks}
        self.max_parallel_runs = max(1, int(max_parallel_runs or 1))
        self._children: dict[str, list[str]] = defaultdict(list)
        self._indegree: dict[str, int] = {task_id: 0 for task_id in self._tasks}
        self._graph = nx.DiGraph()
        self._graph.add_nodes_from(self._tasks)
        for task in self._tasks.values():
            for dependency in task.dependencies:
                if dependency not in self._tasks:
                    raise DAGValidationError(
                        f"Task {task.task_id} depends on unknown task {dependency}"
                    )
                self._children[dependency].append(task.task_id)
                self._indegree[task.task_id] += 1
                self._graph.add_edge(dependency, task.task_id)
        self.validate()

    def validate(self) -> None:
        if not nx.is_directed_acyclic_graph(self._graph):
            cyclic = sorted({node for cycle in nx.simple_cycles(self._graph) for node in cycle})
            raise DAGValidationError(f"Task dependency graph contains a cycle: {cyclic}")

    def compute_next_wave(
        self, *, completed: set[str], failed: set[str], in_progress: set[str]
    ) -> list[DAGTaskNode]:
        blocked_by_failure = self._blocked_by_failed_dependencies(failed)
        ready = [
            task
            for task in self._tasks.values()
            if task.task_id not in completed
            and task.task_id not in failed
            and task.task_id not in in_progress
            and task.task_id not in blocked_by_failure
            and all(dependency in completed for dependency in task.dependencies)
        ]
        ready.sort(key=lambda task: (task.priority, len(task.dependencies), task.task_id))

        selected: list[DAGTaskNode] = []
        claimed_resources: dict[str, str] = {}
        for task in ready:
            if len(selected) >= self.max_parallel_runs:
                break
            if _resource_conflicts(task.resource_claims, claimed_resources):
                continue
            for resource_id in task.resource_claims:
                claimed_resources[resource_id] = task.task_id
            selected.append(task)
        return selected

    def _blocked_by_failed_dependencies(self, failed: set[str]) -> set[str]:
        blocked: set[str] = set()
        queue = deque(failed)
        while queue:
            task_id = queue.popleft()
            for child_id in self._children.get(task_id, []):
                if child_id in blocked:
                    continue
                blocked.add(child_id)
                queue.append(child_id)
        return blocked


def _resource_conflicts(resource_claims: tuple[str, ...], claimed_resources: dict[str, str]) -> bool:
    return any(resource_id in claimed_resources for resource_id in resource_claims)


__all__ = ["DAGScheduler"]
