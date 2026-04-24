from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import uuid
from typing import Any

from langchain.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel

from .tracing import TraceCorrelation


SCHEMA_VERSION = 1


@dataclass(slots=True)
class TrajectoryStep:
    tool: str
    args: dict[str, Any]
    observation: str
    duration_ms: float = 0.0
    error: str | None = None
    cache_hit: bool = False
    fallback_used: bool = False
    fallback_group: str | None = None
    parallel_batch_size: int | None = None
    runtime: dict[str, Any] = field(default_factory=dict)
    observation_truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "args": self.args,
            "observation": self.observation[:2000],
            "duration_ms": self.duration_ms,
            "error": self.error,
            "cache_hit": self.cache_hit,
            "fallback_used": self.fallback_used,
            "fallback_group": self.fallback_group,
            "parallel_batch_size": self.parallel_batch_size,
        }


@dataclass(slots=True)
class TurnTrajectoryRecord:
    id: str
    schema_version: int
    kind: str
    status: str
    thread_id: str
    root_thread_id: str
    user_id_hash: str
    scene: str
    started_at: datetime
    finished_at: datetime
    request_id: str | None = None
    trace_id: str | None = None
    root_span_id: str | None = None
    environment: str | None = None
    deployment: str | None = None
    app_version: str | None = None
    parent_thread_id: str | None = None
    branch_id: str | None = None
    branch_role: str | None = None
    turn_index: int | None = None
    task_brief: str | None = None
    user_message: str | None = None
    answer: str | None = None
    selected_model: str | None = None
    selected_thinking_mode: str | None = None
    plan: Any = None
    reflection: Any = None
    plan_meta: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    trajectory: list[TrajectoryStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "schema_version": self.schema_version,
            "kind": self.kind,
            "status": self.status,
            "thread_id": self.thread_id,
            "root_thread_id": self.root_thread_id,
            "parent_thread_id": self.parent_thread_id,
            "branch_id": self.branch_id,
            "branch_role": self.branch_role,
            "user_id_hash": self.user_id_hash,
            "scene": self.scene,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "root_span_id": self.root_span_id,
            "environment": self.environment,
            "deployment": self.deployment,
            "app_version": self.app_version,
            "turn_index": self.turn_index,
            "task_brief": self.task_brief,
            "user_message": self.user_message,
            "answer": self.answer,
            "selected_model": self.selected_model,
            "selected_thinking_mode": self.selected_thinking_mode,
            "plan": self.plan,
            "reflection": self.reflection,
            "plan_meta": self.plan_meta,
            "metrics": self.metrics,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "trajectory": [step.to_dict() for step in self.trajectory],
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def extract_trajectory_steps(
    messages: list[Any],
    *,
    observation_max_chars: int = 4000,
) -> list[TrajectoryStep]:
    """Pair AI tool calls with matching ToolMessage observations."""
    pending_calls: dict[str, dict[str, Any]] = {}
    steps: list[TrajectoryStep] = []
    max_chars = max(int(observation_max_chars), 0)

    for msg in messages or []:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for call in msg.tool_calls:
                call_id = str(call.get("id") or "")
                if not call_id:
                    continue
                pending_calls[call_id] = {
                    "name": str(call.get("name") or ""),
                    "args": dict(call.get("args") or {}),
                }
            continue

        if not isinstance(msg, ToolMessage):
            continue

        call = pending_calls.pop(str(msg.tool_call_id), None)
        if call is None:
            continue

        artifact = getattr(msg, "artifact", None)
        runtime_info = {}
        if isinstance(artifact, dict) and isinstance(artifact.get("runtime"), dict):
            runtime_info = dict(artifact.get("runtime") or {})

        observation = str(getattr(msg, "content", ""))
        truncated = len(observation) > max_chars if max_chars else bool(observation)
        if max_chars:
            observation = observation[:max_chars]
        else:
            observation = ""
        is_error = getattr(msg, "status", "success") == "error"
        steps.append(
            TrajectoryStep(
                tool=call["name"],
                args=call["args"],
                observation=observation,
                duration_ms=float(runtime_info.get("duration_ms") or 0.0),
                error=observation if is_error else None,
                cache_hit=bool(runtime_info.get("cache_hit", False)),
                fallback_used=bool(runtime_info.get("fallback_used", False)),
                fallback_group=(
                    str(runtime_info.get("fallback_group"))
                    if runtime_info.get("fallback_group")
                    else None
                ),
                parallel_batch_size=(
                    int(runtime_info["parallel_batch_size"])
                    if runtime_info.get("parallel_batch_size") is not None
                    else None
                ),
                runtime=runtime_info,
                observation_truncated=truncated,
            )
        )

    return steps


def build_turn_trajectory_record(
    *,
    thread_id: str,
    user_id: str,
    root_thread_id: str,
    kind: str,
    status: str,
    final_values: dict[str, Any],
    initial_message_count: int,
    initial_llm_calls: int,
    started_at: datetime,
    finished_at: datetime,
    branch_meta: Any = None,
    trace_correlation: TraceCorrelation | None = None,
    input_messages: list[Any] | None = None,
    answer: str | None = None,
    error: str | None = None,
    scene: str = "long_dialog_research",
    observation_max_chars: int = 4000,
    answer_max_chars: int = 4000,
    hash_user_id: bool = True,
) -> TurnTrajectoryRecord:
    final_messages = list(final_values.get("messages", []) or [])
    appended_messages = (
        final_messages[initial_message_count:]
        if len(final_messages) >= initial_message_count
        else final_messages
    )
    fallback_messages = list(input_messages or [])
    trajectory_messages = appended_messages or fallback_messages
    steps = extract_trajectory_steps(
        trajectory_messages,
        observation_max_chars=observation_max_chars,
    )
    selected_answer = answer or _latest_final_ai_text(appended_messages) or _latest_final_ai_text(final_messages)
    if selected_answer is not None:
        selected_answer = selected_answer[: max(answer_max_chars, 0)]

    final_llm_calls = int(final_values.get("llm_calls") or 0)
    metrics = _build_metrics(
        messages=trajectory_messages,
        trajectory=steps,
        latency_ms=(finished_at - started_at).total_seconds() * 1000.0,
        llm_calls=max(0, final_llm_calls - int(initial_llm_calls or 0)),
    )
    branch_role = getattr(getattr(branch_meta, "branch_role", None), "value", None)
    if branch_role is None:
        branch_role = getattr(branch_meta, "branch_role", None)
    correlation = trace_correlation

    plan_meta = dict(_json_safe(final_values.get("plan_meta")) or {})
    role_route_plan = _json_safe(final_values.get("role_route_plan"))
    if role_route_plan:
        plan_meta["role_route_plan"] = role_route_plan

    return TurnTrajectoryRecord(
        id=str(uuid.uuid4()),
        schema_version=SCHEMA_VERSION,
        kind=kind,
        status=status,
        thread_id=thread_id,
        root_thread_id=root_thread_id,
        parent_thread_id=getattr(branch_meta, "parent_thread_id", None),
        branch_id=getattr(branch_meta, "branch_id", None),
        branch_role=str(branch_role) if branch_role else None,
        user_id_hash=_user_id_value(user_id, hash_user_id=hash_user_id),
        scene=scene,
        request_id=correlation.request_id if correlation else None,
        trace_id=correlation.trace_id if correlation else None,
        root_span_id=correlation.root_span_id if correlation else None,
        environment=correlation.environment if correlation else None,
        deployment=correlation.deployment if correlation else None,
        app_version=correlation.app_version if correlation else None,
        turn_index=_count_human_messages(final_messages),
        task_brief=_truncate_optional(final_values.get("task_brief"), 2000),
        user_message=_last_human_text(appended_messages) or _last_human_text(fallback_messages),
        answer=selected_answer,
        selected_model=_truncate_optional(final_values.get("selected_model"), 500),
        selected_thinking_mode=_truncate_optional(final_values.get("selected_thinking_mode"), 100),
        plan=_json_safe(final_values.get("plan")),
        reflection=_json_safe(final_values.get("reflection")),
        plan_meta=plan_meta,
        metrics=metrics,
        error=error,
        started_at=started_at,
        finished_at=finished_at,
        trajectory=steps,
    )


def _build_metrics(
    *,
    messages: list[Any],
    trajectory: list[TrajectoryStep],
    latency_ms: float,
    llm_calls: int,
) -> dict[str, Any]:
    input_tokens = 0
    output_tokens = 0
    for msg in messages or []:
        usage = getattr(msg, "usage_metadata", None) or {}
        if isinstance(usage, dict):
            input_tokens += int(usage.get("input_tokens", 0) or 0)
            output_tokens += int(usage.get("output_tokens", 0) or 0)
    return {
        "latency_ms": latency_ms,
        "tool_calls": len(trajectory),
        "llm_calls": llm_calls,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_hits": sum(1 for step in trajectory if step.cache_hit),
        "fallback_uses": sum(1 for step in trajectory if step.fallback_used),
        "parallel_tool_calls": sum(1 for step in trajectory if (step.parallel_batch_size or 0) > 1),
    }


def _latest_final_ai_text(messages: list[Any]) -> str | None:
    for message in reversed(messages or []):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            return _message_content_to_text(getattr(message, "content", ""))
    return None


def _last_human_text(messages: list[Any]) -> str | None:
    for message in reversed(messages or []):
        if isinstance(message, HumanMessage):
            return _message_content_to_text(getattr(message, "content", ""))
    return None


def _count_human_messages(messages: list[Any]) -> int:
    return sum(1 for message in messages or [] if isinstance(message, HumanMessage))


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, list):
        return " ".join(str(item) for item in content)
    return str(content)


def _truncate_optional(value: Any, max_chars: int) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[: max(max_chars, 0)]


def _user_id_value(user_id: str, *, hash_user_id: bool) -> str:
    if not hash_user_id:
        return user_id
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)
