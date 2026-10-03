"""Eval harness: drive one EvalCase end-to-end against the agent graph.

Designed to be testable without provider keys. The default runtime
uses an in-memory checkpointer + an injectable model factory so we
can plug in fakes (the unit tests do).
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from langchain.messages import AIMessage, HumanMessage

from focus_agent.capabilities import build_tool_registry
from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.core.request_context import RequestContext
from focus_agent.core.token_usage import message_token_usage
from focus_agent.engine.graph_builder import build_graph
from focus_agent.observability.trajectory import extract_trajectory_steps
from focus_agent.skills import SkillRegistry

from ..judges import EnvironmentJudge, LLMJudge, RuleJudge, TrajectoryJudge
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


def _build_isolated_graph(runtime: EvalRuntime) -> Any:
    """Build a fresh graph per case so checkpointer state is isolated."""
    return build_graph(
        settings=runtime.settings,
        tool_registry=runtime.tool_registry,
    )


class _model_factory_patch:  # noqa: N801 - context-manager style, lowercase on purpose
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


def _build_metrics(
    *,
    case: EvalCase,
    state: dict[str, Any],
    trajectory: list[TrajectoryStep],
    latency_ms: float,
    runtime: EvalRuntime,
    verdicts: list[JudgeVerdict],
    model_label: str | None,
    model_name: str,
    base_case_id: str,
    attempt: int,
    attempts: int,
) -> dict[str, Any]:
    llm_calls = int(state.get("llm_calls") or 0)
    tool_calls = len(trajectory)
    # Token accounting is only authoritative when the provider reports both
    # prompt and completion usage. Missing usage must not become a fake $0.
    input_tokens = 0
    output_tokens = 0
    usage_messages = 0
    messages = state.get("messages", []) or []
    ai_messages = sum(isinstance(msg, AIMessage) for msg in messages)
    for msg in messages:
        usage = message_token_usage(msg)
        if usage is not None and _has_complete_usage(msg):
            input_tokens += int(usage.get("input_tokens", 0) or 0)
            output_tokens += int(usage.get("output_tokens", 0) or 0)
            usage_messages += 1

    prices_configured = (
        runtime.cost_per_1k_input is not None and runtime.cost_per_1k_output is not None
    )
    usage_complete = bool(usage_messages and usage_messages >= max(llm_calls, ai_messages))
    cost_known = usage_complete and prices_configured
    cost_usd = (
        input_tokens / 1000.0 * float(runtime.cost_per_1k_input)
        + output_tokens / 1000.0 * float(runtime.cost_per_1k_output)
        if cost_known
        else None
    )
    runtime_kind = _runtime_kind(runtime)
    is_harness_stability = "harness" in case.tags and "stability" in case.tags
    cache_hits = sum(1 for step in trajectory if step.cache_hit)
    fallback_uses = sum(1 for step in trajectory if step.fallback_used)
    parallel_tool_calls = sum(1 for step in trajectory if (step.parallel_batch_size or 0) > 1)
    role_hits = _delegation_role_hits(trajectory)
    handoff_hits = _handoff_hits(trajectory)
    critic_gate_hits = _critic_gate_hits(state, trajectory)
    environment_failures = sum(
        len(verdict.details.get("failures", []))
        for verdict in verdicts
        if verdict.kind == "environment"
    )
    metrics = {
        "latency_ms": latency_ms,
        "tool_calls": tool_calls,
        "llm_calls": llm_calls,
        "input_tokens": input_tokens if usage_complete else None,
        "output_tokens": output_tokens if usage_complete else None,
        "cost_usd": cost_usd,
        "cost_status": "measured" if cost_known else "unknown",
        "cost_unknown_reason": (
            None
            if cost_known
            else "usage_metadata_missing"
            if not usage_messages
            else "usage_metadata_incomplete"
            if not usage_complete
            else "price_missing"
        ),
        "usage_messages": usage_messages,
        "runtime_kind": runtime_kind,
        "provider_evaluation": runtime_kind == "provider",
        "model_quality_evidence": runtime_kind == "provider" and not is_harness_stability,
        "eval_layer": (
            "harness_stability"
            if is_harness_stability
            else "model_quality"
            if runtime_kind == "provider"
            else "fake_runtime"
        ),
        "acceptance_policy": dict(case.acceptance or {}),
        "cache_hits": cache_hits,
        "fallback_uses": fallback_uses,
        "parallel_tool_calls": parallel_tool_calls,
        "delegation_role_hits": role_hits,
        "handoff_hits": handoff_hits,
        "critic_gate_hits": critic_gate_hits,
        "environment_assertions_failed": environment_failures,
        "model_label": model_label,
        "model": model_name,
        "base_case_id": base_case_id,
        "attempt": attempt,
        "attempts": attempts,
        "capability": case.capability,
        "risk_level": case.risk_level,
    }
    metrics["acceptance"] = _initial_acceptance_checks(case.acceptance, metrics)
    return metrics


def _runtime_kind(runtime: EvalRuntime) -> str:
    configured = str(runtime.runtime_kind or "").strip().lower()
    if configured in {"fake", "provider"}:
        return configured
    return "fake" if runtime.model_factory is not None else "provider"


def _has_complete_usage(message: Any) -> bool:
    input_keys = {"input_tokens", "prompt_tokens", "prompt_token_count"}
    output_keys = {"output_tokens", "completion_tokens", "completion_token_count"}
    seen_keys: set[str] = set()
    for payload in _usage_payloads(message):
        seen_keys.update(payload)
    return bool(seen_keys & input_keys and seen_keys & output_keys)


def _usage_payloads(message: Any) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for value in (
        getattr(message, "usage_metadata", None),
        getattr(message, "response_metadata", None),
        getattr(message, "additional_kwargs", None),
    ):
        if not isinstance(value, Mapping):
            continue
        payloads.append(dict(value))
        for key in ("token_usage", "usage", "usage_metadata"):
            nested = value.get(key)
            if isinstance(nested, Mapping):
                payloads.append(dict(nested))
    return payloads


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _initial_acceptance_checks(
    acceptance: Mapping[str, Any] | None,
    metrics: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    for key, raw_threshold in dict(acceptance or {}).items():
        if key not in {"max_cost_usd", "max_p95_latency_ms", "min_success_rate"}:
            continue
        threshold = _finite_number(raw_threshold)
        check: dict[str, Any] = {"threshold": raw_threshold}
        if threshold is None:
            check.update({"status": "invalid", "reason": "threshold_not_numeric"})
        elif key == "max_cost_usd":
            actual = metrics.get("cost_usd")
            check["actual"] = actual
            if actual is None:
                check.update({"status": "unknown", "reason": metrics.get("cost_unknown_reason")})
            else:
                check["status"] = "pass" if float(actual) <= threshold else "fail"
        else:
            check.update({"status": "deferred", "scope": "suite"})
        checks[key] = check
    return checks


def _evaluate_case_acceptance(
    *,
    case: EvalCase,
    metrics: dict[str, Any],
) -> JudgeVerdict | None:
    checks = dict(metrics.get("acceptance") or {})
    cost_check = checks.get("max_cost_usd")
    if not isinstance(cost_check, dict):
        return None
    status = str(cost_check.get("status") or "unknown")
    passed = status == "pass"
    if status == "unknown":
        reason = "max_cost_usd cannot be verified: billing evidence is unknown"
    elif status == "invalid":
        reason = "max_cost_usd threshold is invalid"
    elif status == "fail":
        reason = (
            f"cost_usd={cost_check.get('actual')} exceeded "
            f"max_cost_usd={cost_check.get('threshold')}"
        )
    else:
        reason = "case acceptance checks passed"
    return JudgeVerdict(
        kind="acceptance",
        passed=passed,
        reasoning=reason,
        confidence=1.0,
        details={
            "scope": "case",
            "checks": checks,
            "runtime_kind": metrics.get("runtime_kind"),
            "provider_evaluation": metrics.get("provider_evaluation", False),
        },
    )


def _failure_metrics(
    *,
    case: EvalCase,
    runtime: EvalRuntime,
    latency_ms: float,
    model_label: str | None,
    model_name: str,
    base_case_id: str,
    attempt: int,
    attempts: int,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "latency_ms": latency_ms,
        "tool_calls": 0,
        "llm_calls": 0,
        "input_tokens": None,
        "output_tokens": None,
        "cost_usd": None,
        "cost_status": "unknown",
        "cost_unknown_reason": "runtime_failed",
        "usage_messages": 0,
        "runtime_kind": _runtime_kind(runtime),
        "provider_evaluation": _runtime_kind(runtime) == "provider",
        "model_quality_evidence": False,
        "eval_layer": (
            "harness_stability"
            if "harness" in case.tags and "stability" in case.tags
            else "model_quality"
            if _runtime_kind(runtime) == "provider"
            else "fake_runtime"
        ),
        "acceptance_policy": dict(case.acceptance or {}),
        "model_label": model_label,
        "model": model_name,
        "base_case_id": base_case_id,
        "attempt": attempt,
        "attempts": attempts,
        "capability": case.capability,
        "risk_level": case.risk_level,
    }
    metrics["acceptance"] = _initial_acceptance_checks(case.acceptance, metrics)
    return metrics


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


def _delegation_role_hits(trajectory: list[TrajectoryStep]) -> int:
    roles: set[str] = set()
    for step in trajectory:
        for key in ("role", "agent_role", "branch_role"):
            value = step.args.get(key) or step.runtime.get(key)
            if value:
                roles.add(str(value))
    return len(roles)


def _handoff_hits(trajectory: list[TrajectoryStep]) -> int:
    hits = 0
    for step in trajectory:
        runtime = step.runtime or {}
        if runtime.get("handoff_to") or runtime.get("handoff_from"):
            hits += 1
        if step.args.get("handoff_to") or step.args.get("handoff_from"):
            hits += 1
    return hits


def _critic_gate_hits(state: dict[str, Any], trajectory: list[TrajectoryStep]) -> int:
    hits = 0
    records = state.get("agent_review_queue") or state.get("critic_gate_records") or []
    if isinstance(records, list):
        hits += len(records)
    for step in trajectory:
        role = step.args.get("role") or step.runtime.get("role") or step.runtime.get("branch_role")
        if str(role or "").lower() == "critic":
            hits += 1
    return hits
