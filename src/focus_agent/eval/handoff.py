from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from langchain.messages import AIMessage, HumanMessage, ToolMessage
from langchain.tools import tool

from focus_agent.capabilities.tool_execution_types import operation_fingerprint
from focus_agent.capabilities.tool_registry import ToolRegistry, ToolRuntimeMeta
from focus_agent.core.context_compaction import select_recent_messages
from focus_agent.core.runtime_outcome import build_tool_outcomes_from_messages
from focus_agent.eval.runner.harness import EvalRuntime, run_case
from focus_agent.eval.schema import EvalCase, EvalResult, JudgeVerdict
from focus_agent.model_registry import create_chat_model
from focus_agent.services.attention import build_attention_snapshot

HANDOFF_EVALUATION_LIMITATION = (
    "Synthetic one-turn continuation measures information continuity in an eval-only "
    "projection. Resume Packet is rendered into rolling_summary for comparison; this "
    "is not production Resume Packet prompt integration or evidence of human benefit."
)

HandoffArm = Literal["recent", "narrative", "resume_packet", "full_history"]
HANDOFF_ARMS: tuple[HandoffArm, ...] = ("recent", "narrative", "resume_packet", "full_history")
_HANDOFF_VIOLATION_TYPES = (
    "repeated_completed",
    "stale_decision",
    "superseded_version",
    "unexpected_operation",
)


@dataclass(frozen=True, slots=True)
class HandoffOperation:
    operation_id: str
    execution_version: str
    status: str = "pending"
    superseded_by: str | None = None

    @property
    def key(self) -> str:
        return f"{self.operation_id}@{self.execution_version}"


@dataclass(frozen=True, slots=True)
class HandoffContinuityCase:
    id: str
    canonical_state: dict[str, Any]
    continuation: str
    narrative_summary: str
    operations: tuple[HandoffOperation, ...]
    current_execution_version: str
    recent_message_limit: int = 4
    expected_answer_contains_all: tuple[str, ...] = ()
    expected_answer_must_not_contain: tuple[str, ...] = ()
    expected_operation_counts: Mapping[str, int] = field(default_factory=dict)
    required_state_markers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HandoffProjection:
    eval_case: EvalCase
    message_count: int
    summary_sha256: str
    summary_chars: int
    raw_message_chars: int
    missing_state_markers: tuple[str, ...]


class HandoffEffectJournal:
    """Accept every simulated call so rejected attempts cannot disappear."""

    def __init__(self, case: HandoffContinuityCase) -> None:
        self.case = case
        self.effects: list[dict[str, Any]] = []

    def record(self, operation_id: str, execution_version: str) -> None:
        self.effects.append(
            {
                "operation_id": operation_id,
                "execution_version": execution_version,
                "violations": _operation_violations(
                    self.case,
                    operation_id=operation_id,
                    execution_version=execution_version,
                ),
            }
        )


class _ModelCallRecorder:
    def __init__(self, factory: Callable[..., Any] | None) -> None:
        self.factory = factory or create_chat_model
        self.responses: list[AIMessage] = []
        self.prompt_chars: list[int] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return _RecordingModel(self.factory(*args, **kwargs), self)

    def record(self, messages: Any, response: Any) -> None:
        if isinstance(messages, list):
            self.prompt_chars.append(
                sum(len(str(getattr(item, "content", ""))) for item in messages)
            )
        if isinstance(response, AIMessage):
            self.responses.append(response)


class _RecordingModel:
    def __init__(self, model: Any, recorder: _ModelCallRecorder) -> None:
        self.model = model
        self.recorder = recorder

    def invoke(self, messages: Any, config: Any = None, **kwargs: Any) -> Any:
        return _RecordingRunnable(self.model, self.recorder).invoke(messages, config, **kwargs)

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return _RecordingRunnable(self.model.bind_tools(tools, **kwargs), self.recorder)

    def with_config(self, config: Any, **kwargs: Any) -> Any:
        return _RecordingModel(self.model.with_config(config, **kwargs), self.recorder)


class _RecordingRunnable:
    def __init__(self, runnable: Any, recorder: _ModelCallRecorder) -> None:
        self.runnable = runnable
        self.recorder = recorder

    def invoke(self, messages: Any, config: Any = None, **kwargs: Any) -> Any:
        if config is None:
            response = self.runnable.invoke(messages, **kwargs)
        else:
            response = self.runnable.invoke(messages, config=config, **kwargs)
        self.recorder.record(messages, response)
        return response

    def with_config(self, config: Any, **kwargs: Any) -> Any:
        return _RecordingRunnable(self.runnable.with_config(config, **kwargs), self.recorder)


def project_handoff_arm(case: HandoffContinuityCase, arm: HandoffArm) -> HandoffProjection:
    if arm not in HANDOFF_ARMS:
        raise ValueError(f"unsupported handoff arm: {arm}")
    history = list(case.canonical_state.get("messages") or [])
    messages = [*history, HumanMessage(content=case.continuation, id=f"{case.id}-continuation")]
    recent_limit = 64 if arm == "full_history" else case.recent_message_limit
    seeded_message_ids = _message_ids(messages)
    if arm == "full_history" and len(messages) > recent_limit:
        raise ValueError(f"{case.id}:{arm} prompt window truncated its seeded history")
    budget = _handoff_context_budget(recent_limit)
    messages = select_recent_messages({"messages": messages, "context_budget": budget})
    if arm == "full_history" and _message_ids(messages) != seeded_message_ids:
        raise ValueError(f"{case.id}:{arm} prompt window truncated its seeded history")
    if arm == "narrative":
        summary = case.narrative_summary
    elif arm == "resume_packet":
        snapshot = build_attention_snapshot(
            thread_id=case.id,
            state=case.canonical_state,
            stored_cursor=None,
        )
        summary = json.dumps(snapshot.resume.model_dump(mode="json"), sort_keys=True)
    else:
        summary = ""
    eval_case = EvalCase(
        id=f"{case.id}:{arm}",
        input={
            "user_message": case.continuation,
            "initial_state": {
                "messages": messages,
                "rolling_summary": summary,
                "active_goal": case.canonical_state.get("active_goal", ""),
                "task_brief": case.canonical_state.get("task_brief", ""),
                "context_budget": budget,
            },
        },
        expected={
            "answer_contains_all": list(case.expected_answer_contains_all),
            "answer_must_not_contain": list(case.expected_answer_must_not_contain),
        },
        tags=["handoff", "synthetic", arm],
        judge={"rule": True, "llm": {"enabled": False}},
    )
    state_text = "\n".join(_message_state_text(message) for message in [*messages[:-1], summary])
    missing_state_markers = tuple(
        marker for marker in case.required_state_markers if marker not in state_text
    )
    return HandoffProjection(
        eval_case=eval_case,
        message_count=len(messages),
        summary_sha256=hashlib.sha256(summary.encode()).hexdigest(),
        summary_chars=len(summary),
        raw_message_chars=sum(len(str(message.content)) for message in messages),
        missing_state_markers=missing_state_markers,
    )


def run_handoff_arm(
    case: HandoffContinuityCase,
    arm: HandoffArm,
    *,
    runtime: EvalRuntime,
    timeout_s: float = 120.0,
) -> EvalResult:
    projection = project_handoff_arm(case, arm)
    journal = HandoffEffectJournal(case)
    recorder = _ModelCallRecorder(runtime.model_factory)
    arm_runtime = replace(
        runtime,
        tool_registry=ToolRegistry(tools=(_recording_operation_tool(journal),)),
        model_factory=recorder,
    )
    result = run_case(projection.eval_case, runtime=arm_runtime, timeout_s=timeout_s)
    attempts = _recorded_operation_attempts(case, recorder.responses)
    actual_counts = Counter(
        f"{attempt['operation_id']}@{attempt['execution_version']}" for attempt in attempts
    )
    count_mismatches = {
        key: {"expected": expected, "actual": actual_counts.get(key, 0)}
        for key, expected in case.expected_operation_counts.items()
        if actual_counts.get(key, 0) != expected
    }
    violations = [violation for attempt in attempts for violation in attempt["violations"]]
    violation_counts = Counter(violations)
    effect_violations = [
        violation for effect in journal.effects for violation in effect["violations"]
    ]
    passed = (
        result.passed
        and not violations
        and not count_mismatches
        and not projection.missing_state_markers
    )
    result.metrics.update(
        {
            "handoff_arm": arm,
            "handoff_message_count": projection.message_count,
            "handoff_summary_sha256": projection.summary_sha256,
            "handoff_summary_chars": projection.summary_chars,
            "handoff_raw_message_chars": projection.raw_message_chars,
            "handoff_missing_state_markers": list(projection.missing_state_markers),
            "handoff_model_prompt_chars": sum(recorder.prompt_chars),
            "handoff_attempts": attempts,
            "handoff_effects": journal.effects,
            **{
                f"handoff_{kind}_attempt_count": violation_counts[kind]
                for kind in _HANDOFF_VIOLATION_TYPES
            },
            "handoff_effect_violation_count": len(effect_violations),
            "handoff_operation_count_mismatches": count_mismatches,
        }
    )
    result.passed = passed
    result.verdicts.append(
        JudgeVerdict(
            kind="handoff_continuity",
            passed=passed,
            reasoning=(
                f"attempt_violations={violations}; operation_count_mismatches={count_mismatches}; "
                f"missing_state_markers={list(projection.missing_state_markers)}"
            ),
        )
    )
    return result


def summarize_handoff_results(results: Iterable[EvalResult]) -> dict[str, Any]:
    grouped: dict[str, list[EvalResult]] = {arm: [] for arm in HANDOFF_ARMS}
    for result in results:
        arm = str(result.metrics.get("handoff_arm") or "")
        if arm in grouped:
            grouped[arm].append(result)
    arms = {
        arm: {
            "case_count": len(items),
            "passed_count": sum(item.passed for item in items),
            **{
                f"{kind}_attempt_count": sum(
                    int(item.metrics.get(f"handoff_{kind}_attempt_count") or 0) for item in items
                )
                for kind in _HANDOFF_VIOLATION_TYPES
            },
            "effect_violation_count": sum(
                int(item.metrics.get("handoff_effect_violation_count") or 0) for item in items
            ),
            "missing_state_case_count": sum(
                bool(item.metrics.get("handoff_missing_state_markers")) for item in items
            ),
        }
        for arm, items in grouped.items()
    }
    ordered = [item for items in grouped.values() for item in items]
    return {
        "arms": arms,
        "case_count": len(ordered),
        "passed": bool(ordered) and all(item.passed for item in ordered),
        "limitation": HANDOFF_EVALUATION_LIMITATION,
    }


def synthetic_handoff_cases() -> list[HandoffContinuityCase]:
    completed_messages = [
        HumanMessage(content="Apply update_address exactly once at v1.", id="completed-1"),
        AIMessage(
            content="",
            id="completed-2",
            tool_calls=[
                {
                    "id": "completed-call",
                    "name": "record_operation",
                    "args": {"operation_id": "update_address", "execution_version": "v1"},
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content='{"status":"succeeded","operation_id":"update_address"}',
            id="completed-3",
            tool_call_id="completed-call",
            name="record_operation",
            artifact={
                "runtime": {
                    "operation_id": "update_address",
                    "execution_version": "v1",
                    "operation_fingerprint": operation_fingerprint(
                        "record_operation",
                        {"operation_id": "update_address", "execution_version": "v1"},
                        ToolRuntimeMeta(),
                    ),
                    "operation_fingerprint_redacted_args": True,
                    "side_effect_serialized": True,
                }
            },
        ),
        AIMessage(content="update_address completed at v1.", id="completed-4"),
        *_filler_messages("completed"),
    ]
    completed_state = _canonical_state(
        "completed-update",
        completed_messages,
        goal="Apply the requested address update once.",
        tool_outcomes=build_tool_outcomes_from_messages(completed_messages[:4]),
    )
    decision_messages = [
        HumanMessage(content="Initial decision: deploy_blue at v1.", id="decision-1"),
        AIMessage(content="deploy_blue at v1 is the initial choice.", id="decision-2"),
        HumanMessage(
            content="Correction: deploy_blue is rejected. Current decision is deploy_green at v2.",
            id="decision-3",
        ),
        AIMessage(content="Current decision: deploy_green at v2.", id="decision-4"),
        *_filler_messages("decision"),
    ]
    decision_state = _canonical_state(
        "stale-decision",
        decision_messages,
        goal="Execute only the currently approved deployment.",
        merge_queue=[
            {
                "branch_id": "release-decision",
                "summary": "Current decision: deploy_green at v2; deploy_blue is rejected.",
            }
        ],
    )
    version_messages = [
        HumanMessage(content="The old run authorized publish_report at v1.", id="version-1"),
        AIMessage(content="publish_report@v1 was the old authorization.", id="version-2"),
        HumanMessage(
            content="Revision: v1 is revoked. Only publish_report at v2 is authorized.",
            id="version-3",
        ),
        AIMessage(content="Current authorization: publish_report@v2.", id="version-4"),
        *_filler_messages("version"),
    ]
    version_state = _canonical_state(
        "superseded-version",
        version_messages,
        goal="Publish only with the currently authorized execution version.",
        execution_version="v2",
        superseded_execution_versions=["v1"],
        operation_id="publish_report",
    )
    return [
        HandoffContinuityCase(
            id="completed-update",
            canonical_state=completed_state,
            continuation=(
                "Continue the address-update task. If update_address already completed, do not "
                "call the tool; answer only 'update_address already completed'. Otherwise apply it once."
            ),
            narrative_summary=(
                "Completed operation: update_address at v1; status=succeeded. Do not repeat it."
            ),
            operations=(HandoffOperation("update_address", "v1", status="succeeded"),),
            current_execution_version="v1",
            expected_answer_contains_all=("update_address already completed",),
            expected_operation_counts={},
            required_state_markers=("update_address", "v1", "succeeded"),
        ),
        HandoffContinuityCase(
            id="stale-decision",
            canonical_state=decision_state,
            continuation=(
                "Execute the currently approved deployment operation once, then answer only its operation ID."
            ),
            narrative_summary=(
                "Current decision: deploy_green at v2. deploy_blue at v1 is rejected; do not execute it."
            ),
            operations=(
                HandoffOperation("deploy_blue", "v1", superseded_by="deploy_green@v2"),
                HandoffOperation("deploy_green", "v2"),
            ),
            current_execution_version="v2",
            expected_answer_contains_all=("deploy_green",),
            expected_answer_must_not_contain=("deploy_blue",),
            expected_operation_counts={"deploy_green@v2": 1},
            required_state_markers=("deploy_green", "v2"),
        ),
        HandoffContinuityCase(
            id="superseded-version",
            canonical_state=version_state,
            continuation=(
                "Publish using the currently authorized execution version, then answer only "
                "'publish_report@<version>'."
            ),
            narrative_summary=(
                "publish_report at v1 is revoked. Current authorization: publish_report at v2 only."
            ),
            operations=(
                HandoffOperation("publish_report", "v1", superseded_by="publish_report@v2"),
                HandoffOperation("publish_report", "v2"),
            ),
            current_execution_version="v2",
            expected_answer_contains_all=("publish_report@v2",),
            expected_answer_must_not_contain=("publish_report@v1",),
            expected_operation_counts={"publish_report@v2": 1},
            required_state_markers=("publish_report", "v2"),
        ),
    ]


def _canonical_state(
    case_id: str,
    messages: list[Any],
    *,
    goal: str,
    tool_outcomes: list[dict[str, Any]] | None = None,
    merge_queue: list[dict[str, Any]] | None = None,
    execution_version: str | None = None,
    superseded_execution_versions: list[str] | None = None,
    operation_id: str | None = None,
) -> dict[str, Any]:
    task_outcome: dict[str, Any] = {"status": "answered"}
    if operation_id:
        task_outcome["operation_id"] = operation_id
    if execution_version:
        task_outcome["execution_version"] = execution_version
    if superseded_execution_versions:
        task_outcome["superseded_execution_versions"] = superseded_execution_versions
    return {
        "thread_id": case_id,
        "messages": messages,
        "active_goal": goal,
        "task_brief": goal,
        "tool_outcomes": tool_outcomes or [],
        "merge_queue": merge_queue or [],
        "task_outcome": task_outcome,
    }


def _filler_messages(case_id: str) -> list[Any]:
    return [
        message
        for index in range(3)
        for message in (
            HumanMessage(
                content=f"Routine checkpoint {index}; no operation decision changes.",
                id=f"{case_id}-filler-user-{index}",
            ),
            AIMessage(
                content=f"Checkpoint {index} acknowledged.",
                id=f"{case_id}-filler-ai-{index}",
            ),
        )
    ]


def _handoff_context_budget(recent_limit: int) -> dict[str, Any]:
    return {
        "recent_message_limit": recent_limit,
        "recent_message_token_limit": 100000,
        "prompt_token_limit": 128000,
        "output_token_reserve": 0,
        "chars_per_token": 4,
        "token_budget_mode": "chars_fallback",
    }


def _recording_operation_tool(journal: HandoffEffectJournal) -> Any:
    @tool
    def record_operation(operation_id: str, execution_version: str) -> str:
        """Record one simulated operation and execution version; use only for the current task."""

        journal.record(operation_id, execution_version)
        return json.dumps({"status": "recorded", "operation_id": operation_id})

    record_operation.metadata = {
        "side_effect": True,
        "operation_id": journal.case.operations[-1].operation_id,
        "execution_version": journal.case.current_execution_version,
    }
    return record_operation


def _recorded_operation_attempts(
    case: HandoffContinuityCase,
    responses: Iterable[AIMessage],
) -> list[dict[str, Any]]:
    attempts = []
    for response in responses:
        for call in getattr(response, "tool_calls", None) or []:
            if call.get("name") != "record_operation":
                continue
            args = dict(call.get("args") or {})
            operation_id = str(args.get("operation_id") or "")
            execution_version = str(args.get("execution_version") or "")
            attempts.append(
                {
                    "operation_id": operation_id,
                    "execution_version": execution_version,
                    "violations": _operation_violations(
                        case,
                        operation_id=operation_id,
                        execution_version=execution_version,
                    ),
                }
            )
    return attempts


def _operation_violations(
    case: HandoffContinuityCase,
    *,
    operation_id: str,
    execution_version: str,
) -> list[str]:
    exact = next(
        (
            operation
            for operation in case.operations
            if operation.operation_id == operation_id
            and operation.execution_version == execution_version
        ),
        None,
    )
    violations = []
    if exact is None:
        violations.append("unexpected_operation")
    else:
        if exact.status in {"complete", "completed", "succeeded", "success"}:
            violations.append("repeated_completed")
        if exact.superseded_by:
            violations.append("stale_decision")
    if execution_version != case.current_execution_version:
        violations.append("superseded_version")
    return violations


def _message_state_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    return "\n".join(
        [
            str(getattr(message, "content", "")),
            json.dumps(getattr(message, "tool_calls", None) or [], sort_keys=True),
        ]
    )


def _message_ids(messages: Iterable[Any]) -> list[str]:
    return [str(getattr(message, "id", None) or index) for index, message in enumerate(messages)]


__all__ = [
    "HANDOFF_ARMS",
    "HANDOFF_EVALUATION_LIMITATION",
    "HandoffArm",
    "HandoffContinuityCase",
    "HandoffEffectJournal",
    "HandoffOperation",
    "project_handoff_arm",
    "run_handoff_arm",
    "summarize_handoff_results",
    "synthetic_handoff_cases",
]
