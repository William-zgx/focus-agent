import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.messages import AIMessage, HumanMessage, ToolMessage

from focus_agent.harness.agents import FocusAgentHarness
from focus_agent.harness.middleware import (
    BaseAgentMiddleware,
    CircuitBreaker,
    CircuitBreakerOpenError,
    DanglingToolCallMiddleware,
    LLMErrorHandlingMiddleware,
    LoopDetectedError,
    LoopDetectionMiddleware,
    MiddlewareStack,
)


def test_llm_error_middleware_retries_transient_failures():
    calls = 0

    def handler():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")
        return "ok"

    middleware = LLMErrorHandlingMiddleware(
        max_retries=2,
        initial_backoff_s=0,
        circuit_breaker=CircuitBreaker(failure_threshold=3),
        sleep=lambda _delay: None,
    )

    assert middleware.wrap(handler)() == "ok"
    assert calls == 2


def test_llm_error_middleware_opens_circuit_after_hard_failure():
    def handler():
        raise RuntimeError("provider down")

    middleware = LLMErrorHandlingMiddleware(
        max_retries=0,
        circuit_breaker=CircuitBreaker(failure_threshold=1, recovery_timeout_s=60),
        sleep=lambda _delay: None,
    )

    with pytest.raises(RuntimeError):
        middleware.wrap(handler)()
    with pytest.raises(CircuitBreakerOpenError):
        middleware.wrap(handler)()


def test_llm_error_middleware_bubbles_graph_control_flow_without_retry():
    class GraphBubbleUp(Exception):
        pass

    calls = 0

    def handler():
        nonlocal calls
        calls += 1
        raise GraphBubbleUp("interrupt")

    middleware = LLMErrorHandlingMiddleware(
        max_retries=3,
        initial_backoff_s=0,
        circuit_breaker=CircuitBreaker(failure_threshold=3),
        sleep=lambda _delay: None,
    )

    with pytest.raises(GraphBubbleUp):
        middleware.wrap(handler)()
    assert calls == 1


def test_dangling_tool_call_middleware_inserts_synthetic_tool_message():
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"id": "call-1", "name": "lookup", "args": {"query": "focus"}}],
        ),
        HumanMessage(content="next turn"),
    ]

    middleware = DanglingToolCallMiddleware()
    result = middleware.wrap(lambda state: state)({"messages": messages})

    repaired = result["messages"]
    assert repaired[0] is messages[0]
    assert isinstance(repaired[1], ToolMessage)
    assert repaired[1].tool_call_id == "call-1"
    assert repaired[1].status == "error"
    assert repaired[1].artifact["runtime"]["dangling_tool_call_repaired"] is True
    assert repaired[2] is messages[1]


def test_loop_detection_detects_repeated_tool_call_signature():
    messages = [
        HumanMessage(content="find it"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call-1", "name": "lookup", "args": {"query": "focus"}}],
        ),
        ToolMessage(content="{}", tool_call_id="call-1"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call-2", "name": "lookup", "args": {"query": "focus"}}],
        ),
    ]

    middleware = LoopDetectionMiddleware(max_repetitions=2)
    detected = middleware.detect(messages)

    assert detected is not None
    assert detected.reason == "repeated_message_signature"
    assert detected.repetitions == 2


def test_loop_detection_can_force_fallback_answer():
    middleware = LoopDetectionMiddleware(max_repetitions=2, on_detected="return_fallback")

    result = middleware.wrap(lambda state: {"messages": [AIMessage(content="again")]})(
        {"messages": [HumanMessage(content="say it"), AIMessage(content="again")]}
    )

    assert result["messages"][0].content == middleware.fallback_message


def test_loop_detection_raises_on_hard_stop():
    middleware = LoopDetectionMiddleware(max_repetitions=2)

    with pytest.raises(LoopDetectedError):
        middleware.wrap(lambda state: {"messages": [AIMessage(content="again")]})(
            {"messages": [HumanMessage(content="say it"), AIMessage(content="again")]}
        )


def test_focus_agent_harness_stream_chunks_applies_middleware(monkeypatch):
    graph = object()
    observed = {}

    async def fake_stream_graph_chunks(
        *,
        graph: Any,
        checkpointer: Any,
        settings: Any,
        payload: Any,
        config: dict[str, Any],
        context: Any,
    ):
        observed["graph"] = graph
        observed["payload"] = payload
        yield {"type": "messages", "data": (AIMessage(content="ok"), {"langgraph_node": "agent"}), "ns": ()}

    class MarkPayloadMiddleware(BaseAgentMiddleware):
        def wrap(self, handler):
            def wrapped(state, *args: Any, **kwargs: Any):
                updated = dict(state)
                updated["middleware_applied"] = True
                return handler(updated, *args, **kwargs)

            return wrapped

    monkeypatch.setattr(
        "focus_agent.services.chat_streaming.stream_graph_chunks",
        fake_stream_graph_chunks,
    )

    harness = FocusAgentHarness(
        config=None,
        graph=graph,
        run_manager=None,
        stream_bridge=None,
        middleware=MiddlewareStack((MarkPayloadMiddleware(),)),
        event_store=None,
    )

    async def collect() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        async for chunk in harness.stream_chunks(
            settings=SimpleNamespace(sse_heartbeat_seconds=0),
            payload={"messages": []},
            config={},
            context=SimpleNamespace(root_thread_id="root-1"),
            checkpointer=None,
        ):
            result.append(chunk)
        return result

    chunks = asyncio.run(collect())

    assert observed["graph"] is graph
    assert observed["payload"]["middleware_applied"] is True
    assert len(chunks) == 1
    assert chunks[0]["type"] == "messages"
    assert chunks[0]["data"][0].content == "ok"
