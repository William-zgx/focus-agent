from __future__ import annotations

import json
from typing import Any

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import tool
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.config import get_config
from langgraph.runtime import get_runtime
from pydantic import PrivateAttr

from focus_agent.capabilities.tool_registry import ToolRegistry
from focus_agent.config import Settings
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.graph.tool_execution import HarnessToolServices
from focus_agent.engine.graph_builder import build_graph
from focus_agent.engine.local_persistence import PersistentInMemorySaver
from focus_agent.harness.governance.permissions import (
    PermissionAction,
    PermissionManager,
    PermissionRule,
)
from focus_agent.memory import MemoryExtractor, MemoryRetriever
from focus_agent.transport.stream_events import (
    STREAM_VISIBILITY_QUARANTINE,
    STREAM_VISIBILITY_VISIBLE,
    stream_visibility_phase_from_metadata,
)


@tool
def lookup(name: str) -> str:
    """Look up a project fact by name."""
    return f"fact:{name}"


lookup.metadata = {"parallel_safe": True, "cacheable": False}


class _BoundModel:
    def __init__(self, model: _ScriptedModel, tool_names: list[str]):
        self._model = model
        self._tool_names = tool_names
        self._config: dict[str, Any] = {}

    def with_config(self, config):
        self._config = {**self._config, **dict(config)}
        return self

    def invoke(self, prompt_messages):
        return self._model.respond(prompt_messages, self._tool_names, self._config)


class _ScriptedModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self._config: dict[str, Any] = {}

    def bind_tools(self, tools, **_kwargs):
        return _BoundModel(self, sorted(str(getattr(item, "name", "")) for item in tools))

    def with_config(self, config):
        self._config = {**self._config, **dict(config)}
        return self

    def invoke(self, prompt_messages):
        return self.respond(prompt_messages, [], self._config)

    def respond(self, prompt_messages, tool_names, config):
        self.calls.append(
            {
                "messages": list(prompt_messages),
                "tool_names": list(tool_names),
                "config": dict(config),
            }
        )
        try:
            return self.next_response(prompt_messages, tool_names)
        except Exception as exc:
            self.calls[-1]["error"] = str(exc)
            raise

    def next_response(self, _prompt_messages, _tool_names):
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return response


def _v2_graph(
    monkeypatch,
    model,
    tmp_path,
    *,
    tools=(lookup,),
    harness_services=None,
    **settings,
):
    monkeypatch.setattr(
        "focus_agent.engine.graph_builder.create_chat_model",
        lambda *args, **kwargs: model,
    )
    return build_graph(
        settings=Settings(**settings),
        checkpointer=PersistentInMemorySaver(tmp_path / "checkpoints.pkl"),
        memory_retriever=MemoryRetriever(store=None),
        memory_extractor=MemoryExtractor(mode="off"),
        tool_registry=ToolRegistry(tools=tuple(tools)),
        harness_services=harness_services,
    )


def _invoke(
    graph,
    payload,
    thread_id: str,
    *,
    configurable: dict[str, str] | None = None,
):
    return graph.invoke(
        payload,
        config={"configurable": {"thread_id": thread_id, **(configurable or {})}},
        context=RequestContext(user_id="user-1", root_thread_id=thread_id),
        version="v2",
    )


def _ask(text: str, *, model: str = "openai:gpt-4.1-mini") -> dict:
    return {
        "messages": [HumanMessage(content=text)],
        "selected_model": model,
        "selected_thinking_mode": "deep",
    }


def _is_subtask_call(call: dict[str, Any]) -> bool:
    return any(
        isinstance(message, SystemMessage) and "fresh sub-agent" in message.content
        for message in call["messages"]
    )


def _subtask_call() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "id": "delegate-1",
                "name": "run_subtask",
                "args": {
                    "description": "Research alpha",
                    "prompt": "Research alpha with web_search and report the result.",
                },
            }
        ],
    )


def test_v2_subtask_returns_answer_sources_and_trusted_context(monkeypatch, tmp_path):
    contexts: list[dict[str, Any]] = []

    @tool
    def web_search(query: str) -> str:
        """Search the web."""
        runtime = get_runtime(RequestContext)
        configurable = get_config().get("configurable") or {}
        contexts.append(
            {
                "user_id": runtime.context.user_id,
                "root_thread_id": runtime.context.root_thread_id,
                "thread_id": str(configurable.get("thread_id") or ""),
                "config_user_id": str(configurable.get("user_id") or ""),
                "branch_id": str(configurable.get("branch_id") or ""),
                "has_parent_checkpointer": configurable.get("__pregel_checkpointer") is not None,
                "query": query,
            }
        )
        return json.dumps(
            {
                "results": [
                    {
                        "url": "https://example.com/alpha",
                        "title": "Alpha source",
                        "content": "Alpha is documented.",
                    }
                ]
            }
        )

    web_search.metadata = {"parallel_safe": True, "cacheable": False}

    @tool
    def risky_lookup(name: str) -> str:
        """Look up a fact only after approval."""
        return name

    risky_lookup.metadata = {"requires_approval": True, "parallel_safe": True}

    @tool
    def ask_user_question(questions: list[dict]) -> str:
        """Ask the user questions."""
        return json.dumps(questions)

    model = _ScriptedModel(
        [
            _subtask_call(),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "sub-search-1",
                        "name": "web_search",
                        "args": {"query": "alpha"},
                    }
                ],
            ),
            AIMessage(content="Alpha is documented by the source."),
            AIMessage(content="Parent finished with the sub-agent result."),
        ]
    )
    graph = _v2_graph(
        monkeypatch,
        model,
        tmp_path,
        tools=(web_search, risky_lookup, ask_user_question),
    )

    result = _invoke(
        graph,
        _ask("Delegate alpha research."),
        "thread-subtask",
        configurable={"user_id": "user-1", "branch_id": "branch-parent"},
    )

    tool_message = next(
        message
        for message in result.value["messages"]
        if isinstance(message, ToolMessage) and message.tool_call_id == "delegate-1"
    )
    payload = json.loads(tool_message.content)
    assert tool_message.status == "success"
    assert payload["answer"] == "Alpha is documented by the source."
    assert payload["sources"] == [{"title": "Alpha source", "url": "https://example.com/alpha"}]
    assert contexts == [
        {
            "user_id": "user-1",
            "root_thread_id": "thread-subtask",
            "thread_id": "thread-subtask:subtask:delegate-1",
            "config_user_id": "user-1",
            "branch_id": "branch-parent",
            "has_parent_checkpointer": False,
            "query": "alpha",
        }
    ]
    subtask_calls = [call for call in model.calls if _is_subtask_call(call)]
    assert len(subtask_calls) == 2
    assert all(call["tool_names"] == ["todo_write", "web_search"] for call in subtask_calls)
    assert all(
        call["config"].get("metadata", {}).get("stream_phase") == STREAM_VISIBILITY_QUARANTINE
        for call in subtask_calls
    )
    assert all(
        [message.content for message in call["messages"] if isinstance(message, HumanMessage)]
        == ["Research alpha with web_search and report the result."]
        for call in subtask_calls
    )
    parent_calls = [call for call in model.calls if not _is_subtask_call(call)]
    assert parent_calls[0]["tool_names"] == [
        "ask_user_question",
        "risky_lookup",
        "run_subtask",
        "todo_write",
        "web_search",
    ]
    assert parent_calls[0]["config"]["metadata"]["stream_phase"] == STREAM_VISIBILITY_VISIBLE
    assert any(
        isinstance(message, SystemMessage)
        and "Use run_subtask for broad research" in message.content
        for message in parent_calls[0]["messages"]
    )
    assert all(
        not (
            isinstance(message, SystemMessage)
            and "Use run_subtask for broad research" in message.content
        )
        for call in subtask_calls
        for message in call["messages"]
    )
    assert result.value["messages"][-1].content == "Parent finished with the sub-agent result."
    checkpoint_threads = {
        str(item.config.get("configurable", {}).get("thread_id") or "")
        for item in graph.checkpointer.list(None)
    }
    assert "thread-subtask" in checkpoint_threads
    assert not any(":subtask:" in thread_id for thread_id in checkpoint_threads)


class _ParallelDelegatingModel(_ScriptedModel):
    def __init__(self):
        super().__init__([AIMessage(content="unused")])

    def next_response(self, prompt_messages, _tool_names):
        if not _is_subtask_call({"messages": prompt_messages}):
            if any(isinstance(message, ToolMessage) for message in prompt_messages):
                return AIMessage(content="Both subtasks finished.")
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "parallel-1",
                        "name": "run_subtask",
                        "args": {"description": "First", "prompt": "First independent task"},
                    },
                    {
                        "id": "parallel-2",
                        "name": "run_subtask",
                        "args": {"description": "Second", "prompt": "Second independent task"},
                    },
                ],
            )
        human_text = next(
            message.content for message in prompt_messages if isinstance(message, HumanMessage)
        )
        if human_text == "First independent task":
            if not any(isinstance(message, ToolMessage) for message in prompt_messages):
                return AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "parallel-lookup", "name": "lookup", "args": {"name": "one"}}
                    ],
                )
            return AIMessage(content="First answer: fact:one")
        return AIMessage(content="Second answer")


def test_v2_two_subtasks_run_in_one_parallel_step(monkeypatch, tmp_path):
    model = _ParallelDelegatingModel()
    graph = _v2_graph(monkeypatch, model, tmp_path)

    result = _invoke(graph, _ask("Delegate two tasks."), "thread-parallel")

    messages = {
        message.tool_call_id: message
        for message in result.value["messages"]
        if isinstance(message, ToolMessage) and message.tool_call_id.startswith("parallel-")
    }
    assert set(messages) == {"parallel-1", "parallel-2"}
    assert json.loads(messages["parallel-1"].content)["answer"] == "First answer: fact:one", [
        {
            "subtask": _is_subtask_call(call),
            "human": [
                message.content for message in call["messages"] if isinstance(message, HumanMessage)
            ],
            "error": call.get("error"),
        }
        for call in model.calls
    ]
    assert json.loads(messages["parallel-2"].content)["answer"] == "Second answer"
    assert all(
        message.artifact["runtime"]["parallel_batch_size"] == 2 for message in messages.values()
    )
    assert result.value["messages"][-1].content == "Both subtasks finished."


def test_v2_subtask_exception_becomes_error_tool_message(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            _subtask_call(),
            RuntimeError("sub-agent boom"),
            RuntimeError("sub-agent boom"),
            AIMessage(content="Parent handled the failed delegation."),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path)

    result = _invoke(graph, _ask("Delegate alpha research."), "thread-subtask-error")

    message = next(
        item
        for item in result.value["messages"]
        if isinstance(item, ToolMessage) and item.tool_call_id == "delegate-1"
    )
    assert message.status == "error"
    payload = json.loads(message.content)
    assert payload["status"] == "error"
    assert "sub-agent boom" in payload["error"]
    assert result.value["messages"][-1].content == "Parent handled the failed delegation."


def test_v2_subtask_empty_answer_becomes_error_tool_message(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            _subtask_call(),
            AIMessage(content=""),
            AIMessage(content=""),
            AIMessage(content="Parent handled the empty result."),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path)

    result = _invoke(graph, _ask("Delegate alpha research."), "thread-subtask-empty")

    message = next(
        item
        for item in result.value["messages"]
        if isinstance(item, ToolMessage) and item.tool_call_id == "delegate-1"
    )
    assert message.status == "error"
    assert "empty answer" in json.loads(message.content)["error"]


def test_v2_subtask_round_budget_becomes_error_tool_message(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            _subtask_call(),
            AIMessage(
                content="",
                tool_calls=[{"id": "budget-lookup", "name": "lookup", "args": {"name": "alpha"}}],
            ),
            AIMessage(content="Partial answer at the budget boundary."),
            AIMessage(
                content="",
                tool_calls=[{"id": "budget-lookup", "name": "lookup", "args": {"name": "alpha"}}],
            ),
            AIMessage(content="Partial answer at the budget boundary."),
            AIMessage(content="Parent handled the exhausted subtask."),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path, agent_max_tool_rounds=1)

    result = _invoke(graph, _ask("Delegate alpha research."), "thread-subtask-budget")

    message = next(
        item
        for item in result.value["messages"]
        if isinstance(item, ToolMessage) and item.tool_call_id == "delegate-1"
    )
    assert message.status == "error"
    assert "tool-round budget" in json.loads(message.content)["error"]
    assert result.value["messages"][-1].content == "Parent handled the exhausted subtask."


class _StreamDelegationModel(_ScriptedModel):
    def __init__(self):
        super().__init__([AIMessage(content="unused")])

    def next_response(self, prompt_messages, _tool_names):
        if not _is_subtask_call({"messages": prompt_messages}):
            if any(isinstance(message, ToolMessage) for message in prompt_messages):
                return AIMessage(content="PARENT_VISIBLE")
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "stream-delegate",
                        "name": "run_subtask",
                        "args": {"description": "Stream", "prompt": "Streaming subtask"},
                    }
                ],
            )
        if not any(isinstance(message, ToolMessage) for message in prompt_messages):
            return AIMessage(
                content="",
                tool_calls=[{"id": "stream-lookup", "name": "lookup", "args": {"name": "stream"}}],
            )
        return AIMessage(content="SUB_SECRET")


class _CallbackModel(BaseChatModel):
    _handler: _ScriptedModel = PrivateAttr()
    _tool_names: list[str] = PrivateAttr(default_factory=list)

    def __init__(self, *, handler: _ScriptedModel, tool_names=()):
        super().__init__()
        self._handler = handler
        self._tool_names = list(tool_names)

    @property
    def _llm_type(self) -> str:
        return "focus-agent-scripted-test"

    def bind_tools(self, tools, **_kwargs):
        return _CallbackModel(
            handler=self._handler,
            tool_names=[str(getattr(item, "name", "")) for item in tools],
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        callback_config = {
            "metadata": dict(getattr(run_manager, "metadata", {}) or {}),
            "tags": list(getattr(run_manager, "tags", []) or []),
        }
        response = self._handler.respond(messages, self._tool_names, callback_config)
        return ChatResult(generations=[ChatGeneration(message=response)])


def test_v2_nested_subtask_chunks_are_never_visible(monkeypatch, tmp_path):
    handler = _StreamDelegationModel()
    model = _CallbackModel(handler=handler)
    graph = _v2_graph(monkeypatch, model, tmp_path)
    subtask_chunks: list[tuple[tuple[str, ...], dict[str, Any]]] = []

    stream = graph.stream(
        _ask("Delegate streaming work."),
        config={"configurable": {"thread_id": "thread-subtask-stream"}},
        context=RequestContext(user_id="user-1", root_thread_id="thread-subtask-stream"),
        stream_mode="messages",
        subgraphs=True,
    )
    for namespace, (message, metadata) in stream:
        if not isinstance(message, AIMessage):
            continue
        text = message.content if isinstance(message.content, str) else ""
        if "SUB_SECRET" in text:
            subtask_chunks.append((namespace, metadata))

    assert subtask_chunks
    assert all(namespace for namespace, _metadata in subtask_chunks), subtask_chunks
    assert all(
        stream_visibility_phase_from_metadata(metadata) == STREAM_VISIBILITY_QUARANTINE
        for _namespace, metadata in subtask_chunks
    )
    subtask_model_calls = [call for call in handler.calls if _is_subtask_call(call)]
    assert len(subtask_model_calls) == 2
    assert all(
        call["config"].get("metadata", {}).get("stream_phase") == STREAM_VISIBILITY_QUARANTINE
        for call in subtask_model_calls
    )
    parent_model_calls = [call for call in handler.calls if not _is_subtask_call(call)]
    assert all(
        call["config"].get("metadata", {}).get("stream_phase") == STREAM_VISIBILITY_VISIBLE
        for call in parent_model_calls
    )


def test_v2_subtask_permission_ask_blocks_without_interrupt(monkeypatch, tmp_path):
    executed: list[str] = []

    @tool
    def guarded_lookup(name: str) -> str:
        """Lookup guarded by an ASK rule."""
        executed.append(name)
        return name

    guarded_lookup.metadata = {"parallel_safe": True, "cacheable": False}

    class DelegatingModel(_ScriptedModel):
        def next_response(self, prompt_messages, _tool_names):
            if any(
                isinstance(message, SystemMessage) and "fresh sub-agent" in message.content
                for message in prompt_messages
            ):
                if any(isinstance(message, ToolMessage) for message in prompt_messages):
                    return AIMessage(content="child finished without approval")
                return AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "child-ask", "name": "guarded_lookup", "args": {"name": "x"}}
                    ],
                )
            if any(isinstance(message, ToolMessage) for message in prompt_messages):
                return AIMessage(content="parent finished")
            return _subtask_call()

    manager = PermissionManager(
        rules=[
            PermissionRule(action=PermissionAction.ALLOW, tool_pattern="*"),
            PermissionRule(
                action=PermissionAction.ASK,
                tool_pattern="guarded_lookup",
                reason="child calls cannot request approval",
            ),
        ]
    )
    model = DelegatingModel([])
    graph = _v2_graph(
        monkeypatch,
        model,
        tmp_path,
        tools=(guarded_lookup,),
        harness_services=HarnessToolServices(permission_manager=manager),
    )

    result = _invoke(graph, _ask("Delegate guarded work."), "thread-subtask-permission-ask")

    assert executed == []
    assert not result.interrupts
    assert result.value["messages"][-1].content == "parent finished"
    child_calls = [call for call in model.calls if _is_subtask_call(call)]
    assert len(child_calls) == 2
    blocked = next(
        message
        for message in child_calls[-1]["messages"]
        if isinstance(message, ToolMessage) and message.tool_call_id == "child-ask"
    )
    payload = json.loads(str(blocked.content))
    assert payload["runtime"]["permission_ask"] is True
    assert "human approval is unavailable" in payload["error"]
