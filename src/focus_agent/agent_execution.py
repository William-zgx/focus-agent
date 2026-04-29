from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from typing import Any, Callable, Literal, Protocol

from langchain.messages import HumanMessage, SystemMessage
from pydantic import Field

from .agent_delegation import AgentArtifact, AgentRun, AgentTask
from .agent_roles import AgentRole, RoleModelResolver
from .config import Settings
from .core.types import StateModel


DelegationExecutionMode = Literal["observe", "fake", "inline", "background"]
ModelFactory = Callable[..., Any]


class SubagentConfig(StateModel):
    role: AgentRole
    model_id: str
    allowed_tools: list[str] = Field(default_factory=list)
    max_turns: int = 1
    timeout_seconds: int = 30
    max_depth: int = 1
    requires_workspace_write: bool = False
    requires_network: bool = False
    context_refs: list[dict[str, Any]] = Field(default_factory=list)
    run_isolation_key: str = ""


class SubagentRunResult(StateModel):
    run_id: str
    task_id: str
    role: AgentRole
    status: Literal["completed", "failed", "skipped", "needs_review"] = "completed"
    summary: str = ""
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    error: str | None = None
    tool_calls: int = 0
    cost: float = 0.0
    model_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    execution_mode: DelegationExecutionMode = "fake"

    def to_agent_run(self) -> AgentRun:
        return AgentRun(
            run_id=self.run_id,
            task_id=self.task_id,
            role=self.role,
            status=self.status,
            model_id=self.model_id,
            started_at=self.started_at,
            finished_at=self.finished_at,
            tool_calls=self.tool_calls,
            cost=self.cost,
            artifacts=list(self.artifacts),
            error=self.error,
            execution_mode=self.execution_mode,
        )


class DelegatedRunExecutor(Protocol):
    mode: DelegationExecutionMode

    def execute(self, task: AgentTask, config: SubagentConfig) -> SubagentRunResult: ...


class SubagentRegistry(StateModel):
    configs: dict[AgentRole, SubagentConfig] = Field(default_factory=dict)

    @classmethod
    def from_settings(
        cls, settings: Settings | Any, *, context_refs: list[dict[str, Any]] | None = None
    ) -> "SubagentRegistry":
        resolver = RoleModelResolver(settings)
        refs = list(context_refs or [])
        configs = {
            role: SubagentConfig(
                role=role,
                model_id=resolver.resolve(role),
                max_turns=_safe_positive_int(
                    getattr(settings, "agent_subagent_max_turns", 1), default=1
                ),
                timeout_seconds=_safe_positive_int(
                    getattr(settings, "agent_subagent_timeout_seconds", 30),
                    default=30,
                ),
                max_depth=_safe_non_negative_int(
                    getattr(settings, "agent_subagent_max_depth", 1), default=1
                ),
                context_refs=refs,
                run_isolation_key=f"role:{role.value}",
            )
            for role in AgentRole
        }
        return cls(configs=configs)

    def config_for(self, task: AgentTask) -> SubagentConfig:
        base = self.configs.get(task.role) or SubagentConfig(
            role=task.role, model_id="", run_isolation_key=f"role:{task.role.value}"
        )
        return base.model_copy(
            update={
                "allowed_tools": list(task.allowed_tools),
                "max_turns": task.max_turns,
                "timeout_seconds": task.timeout_seconds,
                "max_depth": task.max_depth,
                "requires_workspace_write": task.requires_workspace_write,
                "requires_network": task.requires_network,
                "context_refs": list(task.context_refs),
                "run_isolation_key": task.run_isolation_key or base.run_isolation_key,
            }
        )


class FakeDelegatedRunExecutor:
    mode: DelegationExecutionMode = "fake"

    def execute(self, task: AgentTask, config: SubagentConfig) -> SubagentRunResult:
        started = _utc_now()
        run_id = f"run-{task.task_id}"
        artifact = AgentArtifact(
            artifact_id=f"artifact-{task.task_id}-fake-result",
            kind=_artifact_kind(task.role),
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
            finished_at=_utc_now(),
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
        return _execute_model_task(
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
                    ordered[index] = _failed_result(
                        task, config, self.mode, str(exc), started_at=_utc_now()
                    )
        return [item for item in ordered if item is not None]


def normalize_delegation_execution_mode(value: str | None) -> DelegationExecutionMode:
    normalized = str(value or "observe").strip().lower()
    if normalized in {"fake", "inline", "background"}:
        return normalized  # type: ignore[return-value]
    return "observe"


def executor_for_mode(
    mode: DelegationExecutionMode,
    *,
    model: Any | None = None,
    model_factory: ModelFactory | None = None,
    settings: Settings | None = None,
    max_workers: int | None = None,
) -> DelegatedRunExecutor | None:
    if mode == "observe":
        return None
    if mode == "fake":
        return FakeDelegatedRunExecutor()
    if mode == "inline":
        return InlineDelegatedRunExecutor(
            model=model, model_factory=model_factory, settings=settings
        )
    return BackgroundDelegatedRunExecutor(
        model=model, model_factory=model_factory, settings=settings, max_workers=max_workers
    )


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
            indexed_results[index] = _failed_result(
                task, config, executor.mode, str(exc), started_at=_utc_now()
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
        return _blocked_result_with_reason(
            task,
            config,
            mode,
            "Delegated run requires network access but no network tool is allowed.",
        )
    if task.requires_workspace_write and not _has_workspace_write_tool(config.allowed_tools):
        return _blocked_result_with_reason(
            task,
            config,
            mode,
            "Delegated run requires workspace write access but no write tool is allowed.",
        )
    return _blocked_result(task, config, mode)


def _execute_model_task(
    *,
    task: AgentTask,
    config: SubagentConfig,
    mode: DelegationExecutionMode,
    model: Any | None,
    model_factory: ModelFactory | None,
    settings: Settings | None,
    max_result_chars: int,
) -> SubagentRunResult:
    started = _utc_now()
    try:
        runnable = _model_for_task(
            model=model, model_factory=model_factory, config=config, settings=settings
        )
        if hasattr(runnable, "with_config"):
            runnable = runnable.with_config(
                {"run_name": f"delegated-{task.role.value}", "tags": ["agent_delegation", mode]}
            )
        response = runnable.invoke(_prompt_messages(task, config))
        raw_text = _message_text(response)[:max_result_chars]
        if not raw_text.strip():
            return _failed_result(
                task, config, mode, "Delegated run produced an empty response.", started_at=started
            )
        parsed = _parse_json_object(raw_text)
        summary = str(parsed.get("summary") or raw_text).strip()[:max_result_chars]
        status, error = _status_from_output(task, parsed)
        artifact = AgentArtifact(
            artifact_id=f"artifact-{task.task_id}-{mode}-result",
            kind=_artifact_kind(task.role),
            title=f"{task.role.value} {mode} delegated result",
            summary=summary,
            payload={
                "goal": task.goal,
                "acceptance_criteria": list(task.acceptance_criteria),
                "constraints": list(task.constraints),
                "allowed_tools": list(config.allowed_tools),
                "run_isolation_key": config.run_isolation_key,
                "context_refs": list(config.context_refs),
                "raw_text": raw_text,
                **({"parsed": parsed} if parsed else {}),
            },
        )
        return SubagentRunResult(
            run_id=f"run-{task.task_id}",
            task_id=task.task_id,
            role=task.role,
            status=status,
            summary=summary,
            artifacts=[artifact] if status != "failed" else [],
            error=error,
            tool_calls=0,
            cost=0.0,
            model_id=config.model_id,
            started_at=started,
            finished_at=_utc_now(),
            execution_mode=mode,
        )
    except Exception as exc:  # noqa: BLE001
        return _failed_result(task, config, mode, str(exc), started_at=started)


def _model_for_task(
    *,
    model: Any | None,
    model_factory: ModelFactory | None,
    config: SubagentConfig,
    settings: Settings | None,
) -> Any:
    if model is not None:
        return model
    factory = model_factory
    if factory is None:
        from .model_registry import create_chat_model

        factory = create_chat_model
    return factory(
        config.model_id or getattr(settings, "model", ""), temperature=0.0, settings=settings
    )


def _prompt_messages(task: AgentTask, config: SubagentConfig) -> list[Any]:
    context_refs = json.dumps(config.context_refs[:8], ensure_ascii=False, default=str)
    payload = {
        "task_id": task.task_id,
        "role": task.role.value,
        "goal": task.goal,
        "constraints": list(task.constraints),
        "acceptance_criteria": list(task.acceptance_criteria),
        "allowed_tools": list(config.allowed_tools),
        "run_isolation_key": config.run_isolation_key,
        "context_refs": context_refs[:4000],
    }
    return [
        SystemMessage(
            content=(
                f"You are the delegated {task.role.value} subagent. Use only the provided task context. "
                "Do not call tools, run commands, or modify files. Return a concise result; JSON with "
                "summary, findings, risks, acceptance_checklist, and verdict is preferred."
            )
        ),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False, default=str)),
    ]


def _message_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _status_from_output(
    task: AgentTask, parsed: dict[str, Any]
) -> tuple[Literal["completed", "failed", "needs_review"], str | None]:
    verdict = str(parsed.get("verdict") or "").strip().lower()
    if verdict in {"needs_review", "needs-review"}:
        return "needs_review", "Delegated run requested review."
    if task.role == AgentRole.CRITIC and verdict in {
        "reject",
        "rejected",
        "retry",
        "fail",
        "failed",
    }:
        return "failed", f"Critic delegated run returned verdict={verdict}."
    return "completed", None


def _failed_result(
    task: AgentTask,
    config: SubagentConfig,
    mode: DelegationExecutionMode,
    error: str,
    *,
    started_at: str,
) -> SubagentRunResult:
    return SubagentRunResult(
        run_id=f"run-{task.task_id}",
        task_id=task.task_id,
        role=task.role,
        status="failed",
        summary=error,
        error=error,
        model_id=config.model_id,
        started_at=started_at,
        finished_at=_utc_now(),
        execution_mode=mode,
    )


def _skipped_result(
    task: AgentTask,
    config: SubagentConfig,
    mode: DelegationExecutionMode,
    reason: str,
) -> SubagentRunResult:
    now = _utc_now()
    return SubagentRunResult(
        run_id=f"run-{task.task_id}",
        task_id=task.task_id,
        role=task.role,
        status="skipped",
        summary=reason,
        error=reason,
        model_id=config.model_id,
        started_at=now,
        finished_at=now,
        execution_mode=mode,
    )


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
    return _blocked_result_with_reason(task, config, mode, reason)


def _blocked_result_with_reason(
    task: AgentTask,
    config: SubagentConfig,
    mode: DelegationExecutionMode,
    reason: str,
) -> SubagentRunResult:
    now = _utc_now()
    return SubagentRunResult(
        run_id=f"run-{task.task_id}",
        task_id=task.task_id,
        role=task.role,
        status="needs_review",
        summary=reason,
        error=reason,
        model_id=config.model_id,
        started_at=now,
        finished_at=now,
        execution_mode=mode,
    )


def _has_network_tool(allowed_tools: list[str]) -> bool:
    return bool(set(allowed_tools).intersection({"web_search", "web_fetch", "current_utc_time"}))


def _has_workspace_write_tool(allowed_tools: list[str]) -> bool:
    return bool(
        set(allowed_tools).intersection({"write_text_artifact", "artifact_update", "search_code"})
    )


def _artifact_kind(role: AgentRole) -> str:
    if role == AgentRole.PLANNER:
        return "plan"
    if role == AgentRole.CRITIC:
        return "critic_verdict"
    if role == AgentRole.MEMORY_CURATOR:
        return "memory_candidate"
    if role == AgentRole.SKILL_SCOUT:
        return "tool_route_evidence"
    if role == AgentRole.EXECUTOR:
        return "patch_summary"
    return "evidence"


def _fake_summary(task: AgentTask) -> str:
    criteria = "; ".join(task.acceptance_criteria[:2]) or "traceable fake execution"
    return (
        f"Fake delegated {task.role.value} run completed for {task.goal}. Acceptance: {criteria}."
    )


def _safe_positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _safe_non_negative_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "BackgroundDelegatedRunExecutor",
    "DelegatedRunExecutor",
    "DelegationExecutionMode",
    "FakeDelegatedRunExecutor",
    "InlineDelegatedRunExecutor",
    "SubagentConfig",
    "SubagentRegistry",
    "SubagentRunResult",
    "executor_for_mode",
    "normalize_delegation_execution_mode",
    "run_delegated_tasks",
]
