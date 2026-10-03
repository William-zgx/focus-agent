"""Eval harness: drive one EvalCase end-to-end against the agent graph.

Designed to be testable without provider keys. The default runtime
uses an in-memory checkpointer + an injectable model factory so we
can plug in fakes (the unit tests do).
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain.messages import AIMessage, HumanMessage

from focus_agent.capabilities import build_tool_registry
from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.graph_builder import build_graph
from focus_agent.observability.trajectory import extract_trajectory_steps
from focus_agent.skills import SkillRegistry

from ..judges import EnvironmentJudge, LLMJudge, RuleJudge, TrajectoryJudge
from ..schema import EvalCase, EvalResult, JudgeVerdict, TrajectoryStep
from .metrics import (
    _apply_suite_acceptance,
    _build_metrics,
    _evaluate_case_acceptance,
    _failure_metrics,
)
from .stability import harness_stability_tools, make_harness_stability_model

# The graph builder caches model instances internally; when we monkey-patch
# `create_chat_model` we must serialize graph construction across threads so
# different fake models don't stomp each other.
_BUILD_LOCK = threading.Lock()


@dataclass(slots=True)
class EvalRuntime:
    """Bundles everything `run_case` needs.

    `model_factory` lets tests inject a fake LLM. In production, leave
    it None and the harness will use `create_chat_model` via build_graph.
    """

    settings: Settings
    tool_registry: ToolRegistry
    model_factory: Callable[..., Any] | None = None
    rule_judge: RuleJudge = field(default_factory=RuleJudge)
    llm_judge: LLMJudge = field(default_factory=LLMJudge)
    trajectory_judge: TrajectoryJudge = field(default_factory=TrajectoryJudge)
    environment_judge: EnvironmentJudge = field(default_factory=EnvironmentJudge)
    runtime_kind: str | None = None
    cost_per_1k_input: float | None = None
    cost_per_1k_output: float | None = None


def build_default_runtime(
    *,
    settings: Settings | None = None,
    tools: Iterable[Any] | None = None,
    model_factory: Callable[..., Any] | None = None,
    llm_judge: LLMJudge | None = None,
    runtime_kind: str | None = None,
    cost_per_1k_input: float | None = None,
    cost_per_1k_output: float | None = None,
) -> EvalRuntime:
    settings = settings or Settings()
    if tools is None:
        tool_registry = build_tool_registry(
            settings=settings,
            skill_registry=SkillRegistry.from_settings(settings),
        )
    else:
        tool_registry = ToolRegistry(tools=tuple(tools))
    return EvalRuntime(
        settings=settings,
        tool_registry=tool_registry,
        model_factory=model_factory,
        llm_judge=llm_judge or LLMJudge(),
        runtime_kind=runtime_kind or ("fake" if model_factory is not None else "provider"),
        cost_per_1k_input=cost_per_1k_input,
        cost_per_1k_output=cost_per_1k_output,
    )


def build_harness_stability_runtime(
    *,
    settings: Settings | None = None,
    cost_per_1k_input: float | None = None,
    cost_per_1k_output: float | None = None,
) -> EvalRuntime:
    """Build an offline runtime for the harness_stability release-gate suite."""

    return build_default_runtime(
        settings=settings,
        tools=harness_stability_tools(),
        model_factory=make_harness_stability_model,
        cost_per_1k_input=cost_per_1k_input,
        cost_per_1k_output=cost_per_1k_output,
    )


def load_dataset(path: str | Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"dataset not found: {p}")
    for line_no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{p}:{line_no} invalid JSON: {exc}") from exc
        cases.append(EvalCase.from_dict(obj))
    return cases


def run_case(
    case: EvalCase,
    *,
    runtime: EvalRuntime,
    timeout_s: float = 120.0,
    model_label: str | None = None,
    model_name: str | None = None,
    base_case_id: str | None = None,
    attempt: int = 1,
    attempts: int = 1,
) -> EvalResult:
    if timeout_s and timeout_s > 0:
        return _run_case_with_timeout(
            case,
            runtime=runtime,
            timeout_s=float(timeout_s),
            model_label=model_label,
            model_name=model_name,
            base_case_id=base_case_id,
            attempt=attempt,
            attempts=attempts,
        )
    return _run_case_inner(
        case,
        runtime=runtime,
        model_label=model_label,
        model_name=model_name,
        base_case_id=base_case_id,
        attempt=attempt,
        attempts=attempts,
    )


def _run_case_inner(
    case: EvalCase,
    *,
    runtime: EvalRuntime,
    model_label: str | None = None,
    model_name: str | None = None,
    base_case_id: str | None = None,
    attempt: int = 1,
    attempts: int = 1,
) -> EvalResult:
    started = time.perf_counter()
    try:
        with _model_factory_patch(runtime.model_factory):
            graph = _build_isolated_graph(runtime)
            context = RequestContext(
                user_id=f"eval-{case.id}",
                root_thread_id=f"eval-thread-{case.id}",
                scene=case.scene,
                skill_hints=tuple(case.skill_hints),
            )
            if case.setup:
                for turn in case.setup:
                    graph.invoke(
                        {
                            "messages": [HumanMessage(content=turn.get("user", ""))],
                            "task_brief": (turn.get("user") or "")[:200],
                            "selected_model": runtime.settings.model,
                        },
                        context=context,
                        version="v2",
                    )

            user_message = (case.input.get("user_message") or "").strip()
            payload: dict[str, Any] = {
                "messages": [HumanMessage(content=user_message)],
                "task_brief": user_message[:200],
                "selected_model": runtime.settings.model,
            }
            if case.agent_topology:
                payload.update(_topology_initial_state(case.agent_topology))
            initial_state = case.input.get("initial_state") or {}
            if isinstance(initial_state, dict):
                payload.update(initial_state)
            if case.prompt_id:
                payload.setdefault(
                    "prompt_registry",
                    {
                        "prompt_id": case.prompt_id,
                        "prompt_version": case.prompt_version or "latest",
                    },
                )
            before_state = dict(payload)

            result = graph.invoke(payload, context=context, version="v2")
        state = _state_from_result(result)
        answer = _last_ai_text(state.get("messages", []))
        trajectory = _extract_trajectory(state.get("messages", []))
        latency_ms = (time.perf_counter() - started) * 1000.0

        verdicts = _run_judges(
            case=case,
            answer=answer,
            trajectory=trajectory,
            runtime=runtime,
            state=state,
            before_state=before_state,
        )

        metrics = _build_metrics(
            case=case,
            state=state,
            trajectory=trajectory,
            latency_ms=latency_ms,
            runtime=runtime,
            verdicts=verdicts,
            model_label=model_label,
            model_name=model_name or runtime.settings.model,
            base_case_id=base_case_id or case.id,
            attempt=attempt,
            attempts=attempts,
        )
        acceptance_verdict = _evaluate_case_acceptance(case=case, metrics=metrics)
        if acceptance_verdict is not None:
            verdicts.append(acceptance_verdict)
        passed = all(v.passed for v in verdicts)
        result_case_id = _result_case_id(
            case.id,
            model_label=model_label,
            attempt=attempt,
            attempts=attempts,
        )
        return EvalResult(
            case_id=result_case_id,
            passed=passed,
            answer=answer,
            verdicts=verdicts,
            trajectory=trajectory,
            metrics=metrics,
            tags=list(case.tags),
        )
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - started) * 1000.0
        result_case_id = _result_case_id(
            case.id,
            model_label=model_label,
            attempt=attempt,
            attempts=attempts,
        )
        metrics = _failure_metrics(
            case=case,
            runtime=runtime,
            latency_ms=latency_ms,
            model_label=model_label,
            model_name=model_name or runtime.settings.model,
            base_case_id=base_case_id or case.id,
            attempt=attempt,
            attempts=attempts,
        )
        return EvalResult(
            case_id=result_case_id,
            passed=False,
            answer="",
            verdicts=[
                JudgeVerdict(
                    kind="harness",
                    passed=False,
                    reasoning=f"runtime error: {exc!r}",
                    confidence=1.0,
                )
            ],
            trajectory=[],
            metrics=metrics,
            error=repr(exc),
            tags=list(case.tags),
        )


def _run_case_with_timeout(
    case: EvalCase,
    *,
    runtime: EvalRuntime,
    timeout_s: float,
    model_label: str | None,
    model_name: str | None,
    base_case_id: str | None,
    attempt: int,
    attempts: int,
) -> EvalResult:
    started = time.perf_counter()
    results: queue.Queue[EvalResult] = queue.Queue(maxsize=1)

    def _target() -> None:
        result = _run_case_inner(
            case,
            runtime=runtime,
            model_label=model_label,
            model_name=model_name,
            base_case_id=base_case_id,
            attempt=attempt,
            attempts=attempts,
        )
        try:
            results.put_nowait(result)
        except queue.Full:
            pass

    thread = threading.Thread(
        target=_target,
        name=f"eval-case-{case.id}",
        daemon=True,
    )
    thread.start()
    try:
        return results.get(timeout=timeout_s)
    except queue.Empty:
        latency_ms = (time.perf_counter() - started) * 1000.0
        result_case_id = _result_case_id(
            case.id,
            model_label=model_label,
            attempt=attempt,
            attempts=attempts,
        )
        metrics = _failure_metrics(
            case=case,
            runtime=runtime,
            latency_ms=latency_ms,
            model_label=model_label,
            model_name=model_name or runtime.settings.model,
            base_case_id=base_case_id or case.id,
            attempt=attempt,
            attempts=attempts,
        )
        metrics["timeout_s"] = timeout_s
        return EvalResult(
            case_id=result_case_id,
            passed=False,
            answer="",
            verdicts=[
                JudgeVerdict(
                    kind="harness",
                    passed=False,
                    reasoning=f"case timed out after {timeout_s:g}s",
                    confidence=1.0,
                    details={"timeout_s": timeout_s},
                )
            ],
            trajectory=[],
            metrics=metrics,
            error=f"case timed out after {timeout_s:g}s",
            tags=list(case.tags),
        )


def run_suite(
    cases: Iterable[EvalCase],
    *,
    runtime: EvalRuntime,
    concurrency: int = 4,
    retries: int | None = None,
    model_label: str | None = None,
    model_name: str | None = None,
    timeout_s: float = 120.0,
    progress: Callable[[EvalResult], None] | None = None,
) -> list[EvalResult]:
    cases = list(cases)
    work_items = _expand_attempts(cases, retries=retries)
    if concurrency <= 1 or len(work_items) <= 1:
        results = []
        for case, attempt, attempts in work_items:
            r = run_case(
                case,
                runtime=runtime,
                timeout_s=timeout_s,
                model_label=model_label,
                model_name=model_name,
                base_case_id=case.id,
                attempt=attempt,
                attempts=attempts,
            )
            results.append(r)
        results = _apply_suite_acceptance(results)
        if progress:
            for result in results:
                progress(result)
        return results

    results_by_id: dict[str, EvalResult] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(
                run_case,
                case,
                runtime=runtime,
                timeout_s=timeout_s,
                model_label=model_label,
                model_name=model_name,
                base_case_id=case.id,
                attempt=attempt,
                attempts=attempts,
            ): (case, attempt, attempts)
            for case, attempt, attempts in work_items
        }
        for fut in as_completed(futures):
            case, attempt, attempts = futures[fut]
            try:
                r = fut.result()
            except Exception as exc:  # noqa: BLE001
                metrics = _failure_metrics(
                    case=case,
                    runtime=runtime,
                    latency_ms=None,
                    model_label=model_label,
                    model_name=model_name or runtime.settings.model,
                    base_case_id=case.id,
                    attempt=attempt,
                    attempts=attempts,
                )
                r = EvalResult(
                    case_id=_result_case_id(
                        case.id,
                        model_label=model_label,
                        attempt=attempt,
                        attempts=attempts,
                    ),
                    passed=False,
                    answer="",
                    verdicts=[
                        JudgeVerdict(
                            kind="harness", passed=False, reasoning=f"future failed: {exc!r}"
                        )
                    ],
                    metrics=metrics,
                    error=repr(exc),
                    tags=list(case.tags),
                )
            results_by_id[r.case_id] = r
    ordered_results = [
        results_by_id[
            _result_case_id(
                case.id,
                model_label=model_label,
                attempt=attempt,
                attempts=attempts,
            )
        ]
        for case, attempt, attempts in work_items
    ]
    ordered_results = _apply_suite_acceptance(ordered_results)
    if progress:
        for result in ordered_results:
            progress(result)
    return ordered_results


def _build_isolated_graph(runtime: EvalRuntime) -> Any:
    """Build a fresh graph per case so checkpointer state is isolated."""
    return build_graph(
        settings=runtime.settings,
        tool_registry=runtime.tool_registry,
    )


class _model_factory_patch:  # noqa: N801 — context-manager style, lowercase on purpose
    """Temporarily swap `graph_builder.create_chat_model` for a fake factory.

    Must wrap the entire graph.invoke() call: model instantiation happens
    lazily inside graph nodes, not at build time. Serialized across threads
    by `_BUILD_LOCK` because the module attribute is process-global.
    """

    def __init__(self, factory: Callable[..., Any] | None):
        self.factory = factory
        self._original: Any = None
        self._builder_original: Any = None
        self._locked = False

    def __enter__(self):
        if self.factory is None:
            return self
        _BUILD_LOCK.acquire()
        self._locked = True
        from focus_agent.engine import graph_builder as _gb
        from focus_agent.engine.graph import builder as _graph_builder

        self._original = _gb.create_chat_model
        self._builder_original = _graph_builder.create_chat_model
        _gb.create_chat_model = self.factory
        _graph_builder.create_chat_model = self.factory
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._locked:
            from focus_agent.engine import graph_builder as _gb
            from focus_agent.engine.graph import builder as _graph_builder

            _gb.create_chat_model = self._original
            _graph_builder.create_chat_model = self._builder_original
            _BUILD_LOCK.release()
            self._locked = False
        return False


def _state_from_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "value") and isinstance(result.value, dict):
        return result.value
    if isinstance(result, dict):
        return result
    return {}


def _last_ai_text(messages: list[Any]) -> str:
    for msg in reversed(messages or []):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            content = msg.content
            if isinstance(content, list):
                return " ".join(str(c) for c in content)
            return str(content)
    return ""


def _extract_trajectory(messages: list[Any]) -> list[TrajectoryStep]:
    return extract_trajectory_steps(messages, observation_max_chars=4000)


def _run_judges(
    *,
    case: EvalCase,
    answer: str,
    trajectory: list[TrajectoryStep],
    runtime: EvalRuntime,
    state: dict[str, Any],
    before_state: dict[str, Any],
) -> list[JudgeVerdict]:
    verdicts: list[JudgeVerdict] = []
    if case.judge.get("rule", True):
        verdicts.append(
            runtime.rule_judge.evaluate(case=case, answer=answer, trajectory=trajectory)
        )
    if (case.judge.get("llm") or {}).get("enabled"):
        verdicts.append(runtime.llm_judge.evaluate(case=case, answer=answer, trajectory=trajectory))
    if _has_trajectory_expectations(case.expected):
        verdicts.append(
            runtime.trajectory_judge.evaluate(case=case, answer=answer, trajectory=trajectory)
        )
    if _has_environment_expectations(case.environment):
        verdicts.append(
            runtime.environment_judge.evaluate(
                case=case,
                answer=answer,
                trajectory=trajectory,
                state=state,
                before_state=before_state,
            )
        )
    return verdicts


def _has_trajectory_expectations(expected: dict[str, Any]) -> bool:
    keys = {
        "optimal_tool_sequence",
        "max_tool_calls",
        "min_cache_hits",
        "max_cache_hits",
        "min_fallback_uses",
        "max_fallback_uses",
        "min_parallel_tool_calls",
        "max_parallel_tool_calls",
        "must_hit_cache_tools_any_order",
        "must_use_fallback_tools_any_order",
        "must_parallelize_tools_any_order",
        "must_delegate_to_roles_any_order",
        "must_delegate_to_roles_sequence",
        "must_not_delegate_to_roles",
        "must_record_handoffs_any_order",
        "max_duplicate_tool_calls",
        "max_repeated_role_runs",
    }
    return any(expected.get(key) is not None for key in keys)


def _has_environment_expectations(environment: dict[str, Any]) -> bool:
    return bool((environment or {}).get("assertions"))


def _expand_attempts(
    cases: list[EvalCase],
    *,
    retries: int | None,
) -> list[tuple[EvalCase, int, int]]:
    work_items: list[tuple[EvalCase, int, int]] = []
    for case in cases:
        retry_count = case.retries if retries is None else max(0, int(retries))
        attempts = max(1, retry_count + 1)
        for attempt in range(1, attempts + 1):
            work_items.append((case, attempt, attempts))
    return work_items


def _result_case_id(
    case_id: str,
    *,
    model_label: str | None,
    attempt: int,
    attempts: int,
) -> str:
    result_id = case_id
    if model_label:
        result_id = f"{result_id}::{model_label}"
    if attempts > 1:
        result_id = f"{result_id}::attempt-{attempt}"
    return result_id


def _topology_initial_state(topology: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"agent_topology": dict(topology)}
    roles = list(topology.get("roles") or [])
    if roles:
        payload["agent_team_tasks"] = [{"role": str(role), "status": "planned"} for role in roles]
    if topology.get("critic_required"):
        payload.setdefault("agent_governance_requirements", {})["critic_required"] = True
    if topology.get("handoff_required"):
        payload.setdefault("agent_governance_requirements", {})["handoff_required"] = True
    return payload
