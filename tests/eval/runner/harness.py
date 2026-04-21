"""Eval harness: drive one EvalCase end-to-end against the agent graph.

Designed to be testable without provider keys. The default runtime
uses an in-memory checkpointer + an injectable model factory so we
can plug in fakes (the unit tests do).
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from langchain.messages import AIMessage, HumanMessage

from focus_agent.capabilities import build_tool_registry
from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.graph_builder import build_graph
from focus_agent.observability.trajectory import extract_trajectory_steps
from focus_agent.skills import SkillRegistry

from ..judges import LLMJudge, RuleJudge, TrajectoryJudge
from ..schema import EvalCase, EvalResult, JudgeVerdict, TrajectoryStep


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
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0


def build_default_runtime(
    *,
    settings: Settings | None = None,
    tools: Iterable[Any] | None = None,
    model_factory: Callable[..., Any] | None = None,
    llm_judge: LLMJudge | None = None,
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


def run_case(case: EvalCase, *, runtime: EvalRuntime, timeout_s: float = 120.0) -> EvalResult:
    del timeout_s  # reserved for a future process-level watchdog
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
            initial_state = case.input.get("initial_state") or {}
            if isinstance(initial_state, dict):
                payload.update(initial_state)

            result = graph.invoke(payload, context=context, version="v2")
        state = _state_from_result(result)
        answer = _last_ai_text(state.get("messages", []))
        trajectory = _extract_trajectory(state.get("messages", []))
        latency_ms = (time.perf_counter() - started) * 1000.0

        verdicts = _run_judges(case=case, answer=answer, trajectory=trajectory, runtime=runtime)
        passed = all(v.passed for v in verdicts)

        metrics = _build_metrics(
            state=state,
            trajectory=trajectory,
            latency_ms=latency_ms,
            runtime=runtime,
        )
        return EvalResult(
            case_id=case.id,
            passed=passed,
            answer=answer,
            verdicts=verdicts,
            trajectory=trajectory,
            metrics=metrics,
            tags=list(case.tags),
        )
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - started) * 1000.0
        return EvalResult(
            case_id=case.id,
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
            metrics={"latency_ms": latency_ms, "tool_calls": 0, "llm_calls": 0},
            error=repr(exc),
            tags=list(case.tags),
        )


def run_suite(
    cases: Iterable[EvalCase],
    *,
    runtime: EvalRuntime,
    concurrency: int = 4,
    progress: Callable[[EvalResult], None] | None = None,
) -> list[EvalResult]:
    cases = list(cases)
    if concurrency <= 1 or len(cases) <= 1:
        results = []
        for case in cases:
            r = run_case(case, runtime=runtime)
            if progress:
                progress(r)
            results.append(r)
        return results

    results_by_id: dict[str, EvalResult] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(run_case, case, runtime=runtime): case for case in cases}
        for fut in as_completed(futures):
            case = futures[fut]
            try:
                r = fut.result()
            except Exception as exc:  # noqa: BLE001
                r = EvalResult(
                    case_id=case.id,
                    passed=False,
                    answer="",
                    verdicts=[
                        JudgeVerdict(kind="harness", passed=False, reasoning=f"future failed: {exc!r}")
                    ],
                    error=repr(exc),
                    tags=list(case.tags),
                )
            results_by_id[r.case_id] = r
            if progress:
                progress(r)
    return [results_by_id[c.id] for c in cases]


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
        self._locked = False

    def __enter__(self):
        if self.factory is None:
            return self
        _BUILD_LOCK.acquire()
        self._locked = True
        from focus_agent.engine import graph_builder as _gb

        self._original = _gb.create_chat_model
        _gb.create_chat_model = self.factory
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._locked:
            from focus_agent.engine import graph_builder as _gb

            _gb.create_chat_model = self._original
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
) -> list[JudgeVerdict]:
    verdicts: list[JudgeVerdict] = []
    if case.judge.get("rule", True):
        verdicts.append(
            runtime.rule_judge.evaluate(case=case, answer=answer, trajectory=trajectory)
        )
    if (case.judge.get("llm") or {}).get("enabled"):
        verdicts.append(
            runtime.llm_judge.evaluate(case=case, answer=answer, trajectory=trajectory)
        )
    if _has_trajectory_expectations(case.expected):
        verdicts.append(
            runtime.trajectory_judge.evaluate(case=case, answer=answer, trajectory=trajectory)
        )
    return verdicts


def _build_metrics(
    *,
    state: dict[str, Any],
    trajectory: list[TrajectoryStep],
    latency_ms: float,
    runtime: EvalRuntime,
) -> dict[str, Any]:
    llm_calls = int(state.get("llm_calls") or 0)
    tool_calls = len(trajectory)
    # Token accounting: providers usage_metadata when available; otherwise zero.
    input_tokens = 0
    output_tokens = 0
    for msg in state.get("messages", []) or []:
        usage = getattr(msg, "usage_metadata", None) or {}
        if isinstance(usage, dict):
            input_tokens += int(usage.get("input_tokens", 0) or 0)
            output_tokens += int(usage.get("output_tokens", 0) or 0)

    cost_usd = (
        input_tokens / 1000.0 * runtime.cost_per_1k_input
        + output_tokens / 1000.0 * runtime.cost_per_1k_output
    )
    cache_hits = sum(1 for step in trajectory if step.cache_hit)
    fallback_uses = sum(1 for step in trajectory if step.fallback_used)
    parallel_tool_calls = sum(1 for step in trajectory if (step.parallel_batch_size or 0) > 1)
    return {
        "latency_ms": latency_ms,
        "tool_calls": tool_calls,
        "llm_calls": llm_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "cache_hits": cache_hits,
        "fallback_uses": fallback_uses,
        "parallel_tool_calls": parallel_tool_calls,
    }


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
    }
    return any(expected.get(key) is not None for key in keys)
