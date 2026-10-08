import asyncio
import time
from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from focus_agent.config import Settings
from focus_agent.engine.model_factory import (
    GraphModelFactory,
    ModelInvocationTimeoutError,
)
from focus_agent.services.chat import streaming, turns


class _FakeModel:
    def __init__(self, *, sleep_seconds: float = 0.0):
        self.sleep_seconds = sleep_seconds
        self.bound_tools = None
        self.config = None

    def bind_tools(self, tools, **_kwargs):
        self.bound_tools = list(tools)
        return self

    def with_config(self, config):
        self.config = config
        return self

    def invoke(self, _input, config=None, **_kwargs):
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
        return AIMessage(content="completed", response_metadata={"config": config})


def test_graph_model_factory_enforces_hard_invoke_timeout():
    model = _FakeModel(sleep_seconds=0.2)
    factory = GraphModelFactory(
        settings=Settings(model_request_timeout_seconds=0.02),
        chat_model_factory=lambda *_args, **_kwargs: model,
    )

    started_at = time.monotonic()
    with pytest.raises(ModelInvocationTimeoutError, match="exceeded 0.02 seconds"):
        factory.model_for("openai:fake", "").invoke("blocked")

    assert time.monotonic() - started_at < 0.15


def test_graph_model_factory_preserves_tool_binding_and_invoke_result():
    model = _FakeModel()
    factory = GraphModelFactory(
        settings=Settings(model_request_timeout_seconds=5),
        chat_model_factory=lambda *_args, **_kwargs: model,
    )

    result = factory.model_with_tools_for(
        "openai:fake",
        "",
        default_tools=["default"],
        available_tools=["web_search"],
    ).invoke("prompt", config={"trace": "test"})

    assert model.bound_tools == ["web_search"]
    assert model.config == {"run_name": "focus_agent_model"}
    assert result.content == "completed"
    assert result.response_metadata["config"] == {"trace": "test"}


def test_graph_stream_survives_serial_model_calls_with_progress(monkeypatch):
    monkeypatch.setattr(turns, "_STREAM_SHUTDOWN_TIMEOUT_SECONDS", 0.01)
    model_timeout = 0.05
    model = _FakeModel(sleep_seconds=0.04)
    factory = GraphModelFactory(
        settings=Settings(model_request_timeout_seconds=model_timeout),
        chat_model_factory=lambda *_args, **_kwargs: model,
    )

    builder = StateGraph(dict)

    def model_node(_state):
        model_for_node = factory.model_for("openai:fake", "")
        first = model_for_node.invoke("first")
        second = model_for_node.invoke("second")
        return {"answer": f"{first.content}:{second.content}"}

    builder.add_node("model_node", model_node)
    builder.add_edge(START, "model_node")
    builder.add_edge("model_node", END)
    graph = builder.compile()

    async def consume():
        chunks = []
        async for chunk in streaming.stream_graph_chunks(
            graph=graph,
            checkpointer=None,
            settings=SimpleNamespace(
                model_request_timeout_seconds=model_timeout,
                sse_heartbeat_seconds=0.005,
            ),
            payload={},
            config={},
            context=None,
        ):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(consume())
    model_progress = [
        chunk["data"]
        for chunk in chunks
        if isinstance(chunk, dict)
        and chunk.get("type") == "custom"
        and isinstance(chunk.get("data"), dict)
        and chunk["data"].get("event") == "model"
    ]
    updates = [
        chunk["data"]
        for chunk in chunks
        if isinstance(chunk, dict)
        and chunk.get("type") == "updates"
        and isinstance(chunk.get("data"), dict)
    ]

    assert len(model_progress) == 2
    assert any(
        update.get("model_node", {}).get("answer") == "completed:completed" for update in updates
    )


def test_graph_stream_still_times_out_for_single_unresponsive_model(monkeypatch):
    monkeypatch.setattr(turns, "_STREAM_SHUTDOWN_TIMEOUT_SECONDS", 0.01)
    model_timeout = 0.05
    model = _FakeModel(sleep_seconds=0.2)
    factory = GraphModelFactory(
        settings=Settings(model_request_timeout_seconds=model_timeout),
        chat_model_factory=lambda *_args, **_kwargs: model,
    )

    builder = StateGraph(dict)

    def model_node(_state):
        factory.model_for("openai:fake", "").invoke("blocked")
        return {"answer": "unreachable"}

    builder.add_node("model_node", model_node)
    builder.add_edge(START, "model_node")
    builder.add_edge("model_node", END)
    graph = builder.compile()

    async def consume():
        async for _chunk in streaming.stream_graph_chunks(
            graph=graph,
            checkpointer=None,
            settings=SimpleNamespace(
                model_request_timeout_seconds=model_timeout,
                sse_heartbeat_seconds=0.005,
            ),
            payload={},
            config={},
            context=None,
        ):
            pass

    started = time.perf_counter()
    with pytest.raises(ModelInvocationTimeoutError, match="exceeded 0.05 seconds"):
        asyncio.run(consume())
    assert time.perf_counter() - started < 0.15
