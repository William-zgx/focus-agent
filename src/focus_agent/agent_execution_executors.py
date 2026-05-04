from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .agent_delegation_models import AgentArtifact, AgentTask
from .agent_execution_modes import DelegationExecutionMode, ModelFactory
from .agent_execution_model_task import (
    artifact_kind,
    blocked_result_with_reason,
    execute_model_task,
    failed_result,
    utc_now,
)
from .agent_execution_registry import SubagentRegistry
from .agent_execution_types import DelegatedRunExecutor, SubagentConfig, SubagentRunResult
from .config import Settings


class FakeDelegatedRunExecutor:
    mode: DelegationExecutionMode = "fake"

    def execute(self, task: AgentTask, config: SubagentConfig) -> SubagentRunResult:
        started = utc_now()
        run_id = f"run-{task.task_id}"
        artifact = AgentArtifact(
            artifact_id=f"artifact-{task.task_id}-fake-result",
            kind=artifact_kind(task.role),
            title=f"{task.role.value} fake delegated result",
            summary=_fake_summary(task),
            payload={
                "goal": task.goal,
                "acceptance_criteria": list(task.acceptance_criteria),
                "constraints": list(task.constraints),
                "allowed_tools": list(config.allowed_tools),
                "run_isolation_key": config.run_isolation_key,
                "context_refs": list(config.context_refs),
                "deterministic": True,
            },
        )
        return SubagentRunResult(
            run_id=run_id,
            task_id=task.task_id,
            role=task.role,
            status="completed",
            summary=artifact.summary,
            artifacts=[artifact],
            tool_calls=0,
            cost=0.0,
            model_id=config.model_id,
            started_at=started,
            finished_at=utc_now(),
            execution_mode=self.mode,
        )


class InlineDelegatedRunExecutor:
    mode: DelegationExecutionMode = "inline"

    def __init__(
        self,
        *,
        model: Any | None = None,
        model_factory: ModelFactory | None = None,
        settings: Settings | None = None,
        max_result_chars: int = 4000,
    ):
        self._model = model
        self._model_factory = model_factory
        self._settings = settings
        self._max_result_chars = max(256, int(max_result_chars or 4000))

    def execute(self, task: AgentTask, config: SubagentConfig) -> SubagentRunResult:
        return execute_model_task(
            task=task,
            config=config,
            mode=self.mode,
            model=self._model,
            model_factory=self._model_factory,
            settings=self._settings,
            max_result_chars=self._max_result_chars,
        )


class BackgroundDelegatedRunExecutor(InlineDelegatedRunExecutor):
    mode: DelegationExecutionMode = "background"

    def __init__(self, *, max_workers: int | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.max_workers = max(1, min(8, int(max_workers or 4)))

    def execute_many(
        self, items: list[tuple[AgentTask, SubagentConfig]], *, max_parallel_runs: int = 1
    ) -> list[SubagentRunResult]:
        if not items:
            return []
        workers = max(1, min(self.max_workers, max(1, int(max_parallel_runs or 1)), len(items)))
        ordered: list[SubagentRunResult | None] = [None] * len(items)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="delegated-agent") as pool:
            futures = {
                pool.submit(self.execute, task, config): index
                for index, (task, config) in enumerate(items)
            }
            for future in as_completed(futures):
                index = futures[future]
                task, config = items[index]
                try:
                    ordered[index] = future.result()
                except Exception as exc:  # noqa: BLE001
                    ordered[index] = failed_result(
                        task, config, self.mode, str(exc), started_at=utc_now()
                    )
        return [item for item in ordered if item is not None]


def run_delegated_tasks(
    *,
    tasks: list[AgentTask],
    registry: SubagentRegistry,
    executor: DelegatedRunExecutor | None,
    max_parallel_runs: int = 1,
) -> list[SubagentRunResult]:
    if executor is None:
        return []
    if isinstance(executor, BackgroundDelegatedRunExecutor):
        return _run_background_delegated_tasks(
            tasks=tasks,
            registry=registry,
            executor=executor,
            max_parallel_runs=max_parallel_runs,
        )

    indexed_results: dict[int, SubagentRunResult] = {}
    for index, task in enumerate(tasks):
        config = registry.config_for(task)
        blocked = _preflight_result(task, config, executor.mode)
        if blocked is not None:
            indexed_results[index] = blocked
            continue
        try:
            indexed_results[index] = executor.execute(task, config)
        except Exception as exc:  # noqa: BLE001
            indexed_results[index] = failed_result(
                task, config, executor.mode, str(exc), started_at=utc_now()
            )
    return [indexed_results[index] for index in sorted(indexed_results)]


def _run_background_delegated_tasks(
    *,
    tasks: list[AgentTask],
    registry: SubagentRegistry,
    executor: BackgroundDelegatedRunExecutor,
    max_parallel_runs: int,
) -> list[SubagentRunResult]:
    indexed_results: dict[int, SubagentRunResult] = {}
    runnable: list[tuple[int, AgentTask, SubagentConfig]] = []
    for index, task in enumerate(tasks):
        config = registry.config_for(task)
        blocked = _preflight_result(task, config, executor.mode)
        if blocked is None:
            runnable.append((index, task, config))
        else:
            indexed_results[index] = blocked

    run_results = executor.execute_many(
        [(task, config) for _, task, config in runnable], max_parallel_runs=max_parallel_runs
    )
    for (index, _, _), result in zip(runnable, run_results, strict=False):
        indexed_results[index] = result
    return [indexed_results[index] for index in sorted(indexed_results)]


def _preflight_result(
    task: AgentTask, config: SubagentConfig, mode: DelegationExecutionMode
) -> SubagentRunResult | None:
    if task.requires_network and not _has_network_tool(config.allowed_tools):
        return blocked_result_with_reason(
            task,
            config,
            mode,
            "Delegated run requires network access but no network tool is allowed.",
        )
    if task.requires_workspace_write and not _has_workspace_write_tool(config.allowed_tools):
        return blocked_result_with_reason(
            task,
            config,
            mode,
            "Delegated run requires workspace write access but no write tool is allowed.",
        )
    return _blocked_result(task, config, mode)


def _blocked_result(
    task: AgentTask,
    config: SubagentConfig,
    mode: DelegationExecutionMode,
) -> SubagentRunResult | None:
    reason = ""
    if task.max_depth < 0 or config.max_depth < 0:
        reason = "Delegated run blocked because max_depth budget is exhausted."
    elif task.max_turns <= 0 or config.max_turns <= 0:
        reason = "Delegated run blocked because max_turns budget is exhausted."
    elif task.timeout_seconds <= 0 or config.timeout_seconds <= 0:
        reason = "Delegated run blocked because timeout_seconds budget is exhausted."
    elif task.budget.max_llm_calls <= 0:
        reason = "Delegated run blocked because LLM call budget is exhausted."

    if not reason:
        return None
    return blocked_result_with_reason(task, config, mode, reason)


def _has_network_tool(allowed_tools: list[str]) -> bool:
    return bool(set(allowed_tools).intersection({"web_search", "web_fetch", "current_utc_time"}))


def _has_workspace_write_tool(allowed_tools: list[str]) -> bool:
    return bool(
        set(allowed_tools).intersection({"write_text_artifact", "artifact_update", "search_code"})
    )


def _fake_summary(task: AgentTask) -> str:
    criteria = "; ".join(task.acceptance_criteria[:2]) or "traceable fake execution"
    return (
        f"Fake delegated {task.role.value} run completed for {task.goal}. Acceptance: {criteria}."
    )


__all__ = [
    "BackgroundDelegatedRunExecutor",
    "FakeDelegatedRunExecutor",
    "InlineDelegatedRunExecutor",
    "run_delegated_tasks",
]
