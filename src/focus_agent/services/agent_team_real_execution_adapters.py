"""Model and tool adapters for guarded Agent Team task execution."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.capabilities.sandbox_execution import default_sandbox_execution_service
from focus_agent.config import Settings
from focus_agent.core.agent_team import AgentTeamTask, agent_role_for_team_task_role
from focus_agent.delegation.roles import RoleModelResolver
from focus_agent.model_registry import create_chat_model

from .agent_team_execution_runtime import (
    CancellationToken,
    TaskAgentMessage,
    TaskExecutionScope,
    TaskModelResponse,
    TaskScopedTool,
    TaskToolCall,
)


class _LangChainTaskModelAdapter:
    """Convert the independent task-loop messages to a bound LangChain model."""

    def __init__(self, model: Any) -> None:
        self._model = model

    def invoke(
        self,
        messages: Sequence[TaskAgentMessage],
        *,
        tools: Sequence[Any],
        scope: TaskExecutionScope,
        cancellation_token: CancellationToken,
    ) -> TaskModelResponse:
        del tools, scope
        cancellation_token.raise_if_cancelled()
        response = self._model.invoke(_to_langchain_messages(messages))
        tool_calls = tuple(
            {
                "id": str(item.get("id") or f"task-tool-{index + 1}"),
                "name": str(item.get("name") or ""),
                "args": dict(item.get("args") or {}),
            }
            for index, item in enumerate(getattr(response, "tool_calls", []) or [])
            if isinstance(item, Mapping) and str(item.get("name") or "").strip()
        )
        return TaskModelResponse(
            content=_content_text(getattr(response, "content", "")),
            tool_calls=tuple(
                _task_tool_call(item, index=index) for index, item in enumerate(tool_calls)
            ),
            metadata={
                "model_response_id": str(getattr(response, "id", "") or ""),
                "provider": "configured_model",
            },
        )


def task_model_for_service(
    service: Any,
    *,
    task: AgentTeamTask,
    langchain_tools: Sequence[Any],
    settings: Any,
) -> Any:
    """Build the task-loop model without coupling it to the chat runtime."""
    factory = getattr(service, "task_agent_model_factory", None)
    if callable(factory):
        model = _call_model_factory(factory, task=task, tools=langchain_tools, settings=settings)
        return _adapt_task_model(model, langchain_tools=langchain_tools)
    resolver = RoleModelResolver(settings or Settings())
    model_id = resolver.resolve(agent_role_for_team_task_role(task.role))
    model = create_chat_model(
        model_id,
        temperature=0.0,
        settings=settings if isinstance(settings, Settings) else None,
    )
    if not callable(getattr(model, "bind_tools", None)):
        raise TypeError("Configured Agent Team model does not support tool binding.")
    return _LangChainTaskModelAdapter(model.bind_tools(list(langchain_tools)))


def sandbox_runner_for_service(service: Any) -> Any:
    """Use the injected sandbox runner when present, otherwise Docker-only default."""
    runner = getattr(service, "agent_team_sandbox_runner", None)
    if runner is not None:
        return runner
    return default_sandbox_execution_service(allow_fallback=False)


def allowed_scoped_tool_names(task: AgentTeamTask) -> list[str]:
    """Return the fixed task-scoped tool set allowed for this task."""
    names = {"read_file", "search_code"}
    requested = {str(name).strip() for name in task.scope if str(name).strip()}
    names.update(requested.intersection({"read_file", "search_code"}))
    if task.write_scope:
        names.update({"apply_patch", "run_workspace_command"})
    return sorted(names)


def task_scoped_tools(
    tools_by_name: Mapping[str, Any],
    allowed_names: Sequence[str],
) -> list[TaskScopedTool]:
    """Adapt concrete scoped LangChain tools to the task execution kernel."""
    result: list[TaskScopedTool] = []
    for name in allowed_names:
        tool = tools_by_name.get(name)
        if tool is None:
            continue

        def handler(
            arguments: Mapping[str, Any],
            *,
            tool: Any = tool,
            tool_name: str = name,
        ) -> Any:
            invoke = getattr(tool, "invoke", None)
            if not callable(invoke):
                raise TypeError(f"Scoped tool {tool_name!r} does not expose invoke().")
            return invoke(dict(arguments))

        result.append(
            TaskScopedTool(
                name=name,
                handler=handler,
                description=str(getattr(tool, "description", "") or ""),
                requires_approval=name in {"apply_patch", "run_workspace_command"},
                risk_level="medium" if name in {"apply_patch", "run_workspace_command"} else "low",
                sensitive_argument_names=sensitive_argument_names_for_tool(name),
            )
        )
    return result


def task_prompt(service: Any, task: AgentTeamTask, *, user_id: str) -> str:
    """Build a task-scoped prompt with declared scope and evidence requirements."""
    session = service.get_session(task.session_id, user_id=user_id)
    return "\n\n".join(
        item
        for item in (
            task.goal.strip(),
            f"Mission goal: {session.goal}",
            (
                "Acceptance criteria: " + "; ".join(task.acceptance_criteria)
                if task.acceptance_criteria
                else ""
            ),
            (
                "Required evidence: " + "; ".join(task.evidence_required)
                if task.evidence_required
                else ""
            ),
            (
                "Write scope: " + ", ".join(task.write_scope)
                if task.write_scope
                else "This task is read-only unless an approved scoped write tool is available."
            ),
            "Use only the provided task-scoped tools. Report concrete evidence, not unsupported claims.",
        )
        if item
    )


def sensitive_argument_names_for_tool(tool_name: str) -> frozenset[str]:
    """Declare the command and patch fields that must not persist verbatim."""
    if tool_name == "apply_patch":
        return frozenset({"patch"})
    if tool_name == "run_workspace_command":
        return frozenset({"command"})
    return frozenset()


def _adapt_task_model(model: Any, *, langchain_tools: Sequence[Any]) -> Any:
    bind_tools = getattr(model, "bind_tools", None)
    if not callable(bind_tools):
        return model
    return _LangChainTaskModelAdapter(bind_tools(list(langchain_tools)))


def _call_model_factory(
    factory: Callable[..., Any],
    *,
    task: AgentTeamTask,
    tools: Sequence[Any],
    settings: Any,
) -> Any:
    candidates = (
        ((), {"task": task, "tools": tools, "settings": settings}),
        ((task, tools, settings), {}),
        ((task, tools), {}),
        ((task,), {}),
        ((), {}),
    )
    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError):
        return _call_model_factory_without_signature(factory, candidates)
    for args, kwargs in candidates:
        try:
            signature.bind(*args, **kwargs)
        except TypeError:
            continue
        return factory(*args, **kwargs)
    raise TypeError("task_agent_model_factory has no supported signature.")


def _call_model_factory_without_signature(
    factory: Callable[..., Any],
    candidates: Sequence[tuple[tuple[Any, ...], Mapping[str, Any]]],
) -> Any:
    for args, kwargs in candidates:
        try:
            return factory(*args, **kwargs)
        except TypeError:
            continue
    raise TypeError("task_agent_model_factory has no supported signature.")


def _task_tool_call(payload: Mapping[str, Any], *, index: int) -> TaskToolCall:
    return TaskToolCall(
        call_id=str(payload.get("id") or f"task-tool-{index + 1}"),
        name=str(payload.get("name") or ""),
        arguments=dict(payload.get("args") or {}),
    )


def _to_langchain_messages(messages: Sequence[TaskAgentMessage]) -> list[Any]:
    converted: list[Any] = []
    for message in messages:
        if message.role == "user":
            converted.append(HumanMessage(content=message.content))
        elif message.role == "assistant":
            converted.append(
                AIMessage(
                    content=message.content,
                    tool_calls=[
                        {
                            "id": call.call_id,
                            "name": call.name,
                            "args": dict(call.arguments),
                        }
                        for call in message.tool_calls
                    ],
                )
            )
        elif message.role == "tool":
            converted.append(
                ToolMessage(
                    content=message.content,
                    tool_call_id=str(message.tool_call_id or "task-tool"),
                )
            )
    return converted


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            str(item.get("text") or item.get("content") or "")
            if isinstance(item, Mapping)
            else str(item)
            for item in value
        ).strip()
    return str(value or "")
