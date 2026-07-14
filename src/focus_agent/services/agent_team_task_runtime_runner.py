"""Bounded model and tool execution loop for one Agent Team task."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any
from uuid import uuid4

from .agent_team_task_runtime_protocol import (
    CancellationToken,
    CheckpointSink,
    EvidenceSink,
    TaskAgentMessage,
    TaskAgentModel,
    TaskApprovalDecider,
    TaskApprovalRequest,
    TaskExecutionCancelled,
    TaskExecutionCheckpoint,
    TaskExecutionEventType,
    TaskExecutionEvidence,
    TaskExecutionScope,
    TaskModelResponse,
    TaskRunResult,
    TaskRunStatus,
    TaskScopedTool,
    TaskToolCall,
    TaskToolDefinition,
    TaskToolResult,
    _call_compatible,
    _json_safe,
    _optional_identifier,
    _required_identifier,
)


class TaskAgentRunner:
    """Run a model -> tool-calls -> observations loop inside one task scope."""

    def __init__(
        self,
        *,
        model: TaskAgentModel | Callable[..., Any],
        tools: Sequence[TaskScopedTool],
        max_rounds: int = 8,
        approval_decider: TaskApprovalDecider | None = None,
        checkpoint_sink: CheckpointSink | None = None,
        evidence_sink: EvidenceSink | None = None,
    ) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be at least 1.")
        tools_by_name = {tool.name: tool for tool in tools}
        if len(tools_by_name) != len(tools):
            raise ValueError("Task scoped tool names must be unique.")
        self._model = model
        self._tools_by_name = tools_by_name
        self._max_rounds = max_rounds
        self._approval_decider = approval_decider
        self._checkpoint_sink = checkpoint_sink
        self._evidence_sink = evidence_sink

    def run(
        self,
        *,
        scope: TaskExecutionScope,
        prompt: str,
        cancellation_token: CancellationToken | None = None,
        run_id: str | None = None,
    ) -> TaskRunResult:
        token = cancellation_token or CancellationToken()
        identifier = run_id or f"task-run-{uuid4().hex}"
        messages: list[TaskAgentMessage] = [TaskAgentMessage.user(prompt)]
        checkpoints: list[TaskExecutionCheckpoint] = []
        evidence: list[TaskExecutionEvidence] = []
        exposed_tools = tuple(
            tool.definition for tool in self._tools_by_name.values() if scope.allows_tool(tool.name)
        )

        def record_checkpoint(
            event: TaskExecutionEventType,
            round_number: int,
            payload: Mapping[str, Any] | None = None,
        ) -> None:
            checkpoint = TaskExecutionCheckpoint(
                run_id=identifier,
                task_id=scope.task_id,
                session_id=scope.session_id,
                round_number=round_number,
                event=event,
                payload=_json_safe(payload or {}),
            )
            checkpoints.append(checkpoint)
            if self._checkpoint_sink is not None:
                self._checkpoint_sink(checkpoint)

        def record_evidence(
            *,
            round_number: int,
            kind: str,
            value: Any,
            tool_call_id: str | None = None,
            tool_name: str | None = None,
        ) -> None:
            item = TaskExecutionEvidence(
                run_id=identifier,
                task_id=scope.task_id,
                round_number=round_number,
                kind=kind,
                value=_json_safe(value),
                tool_call_id=tool_call_id,
                tool_name=tool_name,
            )
            evidence.append(item)
            if self._evidence_sink is not None:
                self._evidence_sink(item)

        def finish(
            *,
            status: TaskRunStatus,
            rounds_completed: int,
            final_answer: str | None = None,
            pending_approval: TaskApprovalRequest | None = None,
            error: str | None = None,
        ) -> TaskRunResult:
            return TaskRunResult(
                run_id=identifier,
                scope=scope,
                status=status,
                rounds_completed=rounds_completed,
                final_answer=final_answer,
                messages=tuple(messages),
                checkpoints=tuple(checkpoints),
                evidence=tuple(evidence),
                pending_approval=pending_approval,
                error=error,
            )

        if token.is_cancelled:
            reason = token.reason or "Task execution was cancelled."
            record_checkpoint(TaskExecutionEventType.CANCELLED, 0, {"reason": reason})
            return finish(
                status=TaskRunStatus.CANCELLED,
                rounds_completed=0,
                error=reason,
            )

        for round_number in range(1, self._max_rounds + 1):
            if token.is_cancelled:
                reason = token.reason or "Task execution was cancelled."
                record_checkpoint(
                    TaskExecutionEventType.CANCELLED, round_number - 1, {"reason": reason}
                )
                return finish(
                    status=TaskRunStatus.CANCELLED,
                    rounds_completed=round_number - 1,
                    error=reason,
                )
            try:
                response = _normalize_model_response(
                    _invoke_task_model(
                        self._model,
                        messages=tuple(messages),
                        tools=exposed_tools,
                        scope=scope,
                        cancellation_token=token,
                    )
                )
            except TaskExecutionCancelled as exc:
                token.cancel(str(exc))
                record_checkpoint(
                    TaskExecutionEventType.CANCELLED,
                    round_number - 1,
                    {"reason": token.reason},
                )
                return finish(
                    status=TaskRunStatus.CANCELLED,
                    rounds_completed=round_number - 1,
                    error=token.reason,
                )
            except Exception as exc:  # noqa: BLE001
                error = f"Model invocation failed: {exc}"
                record_checkpoint(
                    TaskExecutionEventType.FAILED,
                    round_number,
                    {"stage": "model", "error": error},
                )
                return finish(
                    status=TaskRunStatus.FAILED,
                    rounds_completed=round_number - 1,
                    error=error,
                )

            messages.append(TaskAgentMessage.assistant(response))
            record_checkpoint(
                TaskExecutionEventType.MODEL_RESPONSE,
                round_number,
                {
                    "content": response.content,
                    "tool_calls": [
                        {
                            "id": call.call_id,
                            "name": call.name,
                            "arguments": dict(call.arguments),
                        }
                        for call in response.tool_calls
                    ],
                },
            )
            record_evidence(
                round_number=round_number,
                kind="model_response",
                value={"content": response.content, "tool_call_count": len(response.tool_calls)},
            )

            if not response.tool_calls:
                record_checkpoint(
                    TaskExecutionEventType.COMPLETED,
                    round_number,
                    {"final_answer": response.content},
                )
                return finish(
                    status=TaskRunStatus.COMPLETED,
                    rounds_completed=round_number,
                    final_answer=response.content,
                )

            approved_tool_call_ids: set[str] = set()
            approval = self._approval_to_pause(
                scope=scope,
                calls=response.tool_calls,
                round_number=round_number,
                approved_tool_call_ids=approved_tool_call_ids,
            )
            if approval is not None:
                record_evidence(
                    round_number=round_number,
                    kind="approval_request",
                    value={
                        "request_id": approval.request_id,
                        "risk_level": approval.risk_level,
                        "arguments": dict(approval.arguments),
                    },
                    tool_call_id=approval.tool_call_id,
                    tool_name=approval.tool_name,
                )
                record_checkpoint(
                    TaskExecutionEventType.AWAITING_APPROVAL,
                    round_number,
                    {
                        "request_id": approval.request_id,
                        "tool_call_id": approval.tool_call_id,
                        "tool_name": approval.tool_name,
                        "risk_level": approval.risk_level,
                    },
                )
                return finish(
                    status=TaskRunStatus.PAUSED_FOR_APPROVAL,
                    rounds_completed=round_number,
                    pending_approval=approval,
                )

            for call in response.tool_calls:
                if token.is_cancelled:
                    reason = token.reason or "Task execution was cancelled."
                    record_checkpoint(
                        TaskExecutionEventType.CANCELLED,
                        round_number,
                        {"reason": reason, "stage": "before_tool"},
                    )
                    return finish(
                        status=TaskRunStatus.CANCELLED,
                        rounds_completed=round_number,
                        error=reason,
                    )
                result = self._execute_tool_call(
                    scope=scope,
                    call=call,
                    cancellation_token=token,
                    approval_granted=call.call_id in approved_tool_call_ids,
                )
                messages.append(TaskAgentMessage.tool(result))
                record_evidence(
                    round_number=round_number,
                    kind="tool_result",
                    value={
                        "status": result.status,
                        "output": result.output,
                        "error": result.error,
                    },
                    tool_call_id=result.call_id,
                    tool_name=result.tool_name,
                )
                record_checkpoint(
                    TaskExecutionEventType.TOOL_RESULT,
                    round_number,
                    {
                        "tool_call_id": result.call_id,
                        "tool_name": result.tool_name,
                        "status": result.status,
                        "error": result.error,
                    },
                )
                if token.is_cancelled:
                    reason = token.reason or "Task execution was cancelled."
                    record_checkpoint(
                        TaskExecutionEventType.CANCELLED,
                        round_number,
                        {"reason": reason, "stage": "after_tool"},
                    )
                    return finish(
                        status=TaskRunStatus.CANCELLED,
                        rounds_completed=round_number,
                        error=reason,
                    )
                if not result.succeeded:
                    error = result.error or f"Tool '{result.tool_name}' failed."
                    record_checkpoint(
                        TaskExecutionEventType.FAILED,
                        round_number,
                        {
                            "stage": "tool",
                            "tool_call_id": result.call_id,
                            "tool_name": result.tool_name,
                            "error": error,
                        },
                    )
                    return finish(
                        status=TaskRunStatus.FAILED,
                        rounds_completed=round_number,
                        error=error,
                    )

        error = f"Task execution reached the maximum of {self._max_rounds} model rounds."
        record_checkpoint(
            TaskExecutionEventType.MAX_ROUNDS_REACHED,
            self._max_rounds,
            {"max_rounds": self._max_rounds},
        )
        return finish(
            status=TaskRunStatus.MAX_ROUNDS_REACHED,
            rounds_completed=self._max_rounds,
            error=error,
        )

    def _approval_to_pause(
        self,
        *,
        scope: TaskExecutionScope,
        calls: Sequence[TaskToolCall],
        round_number: int,
        approved_tool_call_ids: set[str],
    ) -> TaskApprovalRequest | None:
        for call in calls:
            tool = self._tools_by_name.get(call.name)
            if tool is None or not tool.requires_approval:
                continue
            request = TaskApprovalRequest(
                request_id=(f"task-approval:{scope.task_id}:{call.call_id}:{uuid4().hex[:12]}"),
                task_id=scope.task_id,
                session_id=scope.session_id,
                tool_call_id=call.call_id,
                tool_name=tool.name,
                arguments=tool.redact_arguments(call.arguments),
                risk_level=tool.risk_level,
                round_number=round_number,
            )
            decision = self._approval_decider(request) if self._approval_decider else None
            if decision is True:
                approved_tool_call_ids.add(call.call_id)
                continue
            return request
        return None

    def _execute_tool_call(
        self,
        *,
        scope: TaskExecutionScope,
        call: TaskToolCall,
        cancellation_token: CancellationToken,
        approval_granted: bool,
    ) -> TaskToolResult:
        if not scope.allows_tool(call.name):
            return TaskToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                status="failed",
                error=f"Tool '{call.name}' is not allowed in task scope.",
            )
        tool = self._tools_by_name.get(call.name)
        if tool is None:
            return TaskToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                status="failed",
                error=f"Tool '{call.name}' is not registered for task execution.",
            )
        if tool.requires_approval and not approval_granted:
            return TaskToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                status="failed",
                error=f"Tool '{call.name}' requires approval.",
            )
        try:
            output = tool.invoke(
                call.arguments,
                scope=scope,
                cancellation_token=cancellation_token,
            )
        except TaskExecutionCancelled as exc:
            cancellation_token.cancel(str(exc))
            return TaskToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                status="cancelled",
                error=cancellation_token.reason,
            )
        except Exception as exc:  # noqa: BLE001
            return TaskToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                status="failed",
                error=f"Tool '{call.name}' failed: {exc}",
            )
        if isinstance(output, TaskToolResult):
            if output.call_id == call.call_id and output.tool_name == call.name:
                return output
            return TaskToolResult(
                call_id=call.call_id,
                tool_name=call.name,
                status=output.status,
                output=output.output,
                error=output.error,
            )
        return TaskToolResult(
            call_id=call.call_id,
            tool_name=call.name,
            status="completed",
            output=output,
        )


class TaskRunCoordinator:
    """Translate an Agent Team task-like object into an independent runtime call."""

    def __init__(self, runner: TaskAgentRunner) -> None:
        self._runner = runner

    def build_scope(
        self,
        task: Any,
        *,
        user_id: str,
        allowed_tool_names: Sequence[str] | None = None,
        workspace_path: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> TaskExecutionScope:
        task_id = _required_identifier(getattr(task, "task_id", None), "task.task_id")
        session_id = _required_identifier(getattr(task, "session_id", None), "task.session_id")
        resolved_workspace_path = (
            workspace_path if workspace_path is not None else getattr(task, "workspace_path", None)
        )
        resolved_tools = (
            allowed_tool_names
            if allowed_tool_names is not None
            else getattr(task, "scope", ()) or ()
        )
        task_metadata = {
            "role": _optional_identifier(getattr(task, "role", None)),
            "goal": _optional_identifier(getattr(task, "goal", None)),
            **dict(metadata or {}),
        }
        return TaskExecutionScope(
            task_id=task_id,
            session_id=session_id,
            user_id=user_id,
            workspace_path=resolved_workspace_path,
            allowed_tool_names=frozenset(resolved_tools),
            write_scope=tuple(getattr(task, "write_scope", ()) or ()),
            metadata=task_metadata,
        )

    def run_task(
        self,
        task: Any,
        *,
        user_id: str,
        prompt: str | None = None,
        allowed_tool_names: Sequence[str] | None = None,
        workspace_path: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        cancellation_token: CancellationToken | None = None,
        run_id: str | None = None,
    ) -> TaskRunResult:
        scope = self.build_scope(
            task,
            user_id=user_id,
            allowed_tool_names=allowed_tool_names,
            workspace_path=workspace_path,
            metadata=metadata,
        )
        return self._runner.run(
            scope=scope,
            prompt=prompt if prompt is not None else str(getattr(task, "goal", "") or ""),
            cancellation_token=cancellation_token,
            run_id=run_id,
        )


def _invoke_task_model(
    model: TaskAgentModel | Callable[..., Any],
    *,
    messages: Sequence[TaskAgentMessage],
    tools: Sequence[TaskToolDefinition],
    scope: TaskExecutionScope,
    cancellation_token: CancellationToken,
) -> Any:
    target = getattr(model, "invoke", None)
    if not callable(target):
        target = model
    if not callable(target):
        raise TypeError("Task model must be callable or expose an invoke method.")
    return _call_compatible(
        target,
        (
            (
                (),
                {
                    "messages": messages,
                    "tools": tools,
                    "scope": scope,
                    "cancellation_token": cancellation_token,
                },
            ),
            (
                (messages,),
                {
                    "tools": tools,
                    "scope": scope,
                    "cancellation_token": cancellation_token,
                },
            ),
            ((messages, tools, scope, cancellation_token), {}),
            ((messages, tools, scope), {}),
            ((messages, tools), {}),
            ((messages,), {}),
        ),
    )


def _normalize_model_response(value: Any) -> TaskModelResponse:
    if isinstance(value, TaskModelResponse):
        return value
    if isinstance(value, str):
        return TaskModelResponse(content=value)
    content = _read_response_value(value, "content", "")
    raw_calls = _read_response_value(value, "tool_calls", ()) or ()
    metadata = _read_response_value(value, "metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        metadata = {}
    return TaskModelResponse(
        content=str(content or ""),
        tool_calls=tuple(
            _normalize_tool_call(raw_call, index=index) for index, raw_call in enumerate(raw_calls)
        ),
        metadata=metadata,
    )


def _normalize_tool_call(value: Any, *, index: int) -> TaskToolCall:
    raw_id = _read_response_value(value, "id", None)
    if raw_id is None:
        raw_id = _read_response_value(value, "call_id", None)
    raw_name = _read_response_value(value, "name", None)
    raw_arguments = _read_response_value(value, "arguments", None)
    if raw_arguments is None:
        raw_arguments = _read_response_value(value, "args", {})
    if not isinstance(raw_arguments, Mapping):
        raise TypeError(f"Tool call arguments for {raw_name!r} must be a mapping.")
    return TaskToolCall(
        call_id=str(raw_id or f"task-tool-call-{index + 1}"),
        name=str(raw_name or ""),
        arguments=raw_arguments,
    )


def _read_response_value(value: Any, name: str, default: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)
