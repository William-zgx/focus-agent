"""Eval harness: drive one EvalCase end-to-end against the agent graph.

Designed to be testable without provider keys. The default runtime
uses an in-memory checkpointer + an injectable model factory so we
can plug in fakes (the unit tests do).
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.capabilities import build_tool_registry
from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.graph_builder import build_graph
from focus_agent.skills import SkillRegistry

from ..judges import LLMJudge, RuleJudge, TrajectoryJudge
from ..schema import EvalCase, EvalResult, JudgeVerdict, TrajectoryStep


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
    started = time.perf_counter()
    try:
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
    if runtime.model_factory is not None:
        from unittest.mock import patch

        # Inject the fake model factory into graph_builder's create_chat_model.
        patcher = patch(
            "focus_agent.engine.graph_builder.create_chat_model",
            runtime.model_factory,
        )
        patcher.start()
        # Note: the patch lives for the lifetime of the test process, which is
        # acceptable for eval runs (test fixtures handle teardown).

    return build_graph(
        settings=runtime.settings,
        tool_registry=runtime.tool_registry,
    )


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
    """Pair AIMessage(tool_calls=...) with the matching ToolMessage observations."""
    pending_calls: dict[str, dict[str, Any]] = {}
    steps: list[TrajectoryStep] = []
    for msg in messages or []:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for call in msg.tool_calls:
                pending_calls[str(call["id"])] = {
                    "name": call["name"],
                    "args": call.get("args") or {},
                }
        elif isinstance(msg, ToolMessage):
            call = pending_calls.pop(str(msg.tool_call_id), None)
            if call is not None:
                steps.append(
                    TrajectoryStep(
                        tool=call["name"],
                        args=call["args"],
                        observation=str(msg.content)[:4000],
                    )
                )
    return steps


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
    if case.expected.get("optimal_tool_sequence") or case.expected.get("max_tool_calls") is not None:
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
    return {
        "latency_ms": latency_ms,
        "tool_calls": tool_calls,
        "llm_calls": llm_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
    }
