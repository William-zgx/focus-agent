from focus_agent.config import Settings
from focus_agent.capabilities.tool_registry import ToolRuntimeMeta
from focus_agent.capabilities.tool_runtime import ToolExecutionInput, execute_tool_calls
from focus_agent.core.types import ContextBudget
from focus_agent.observability.tracing import (
    build_trace_correlation,
    build_trace_metadata,
    build_trace_tags,
    start_trace_span,
)
from focus_agent.core.branching import BranchMeta, BranchRole, BranchStatus


def test_trace_metadata_contains_thread_fields():
    settings = Settings()
    meta = BranchMeta(
        branch_id="b1",
        root_thread_id="root-1",
        parent_thread_id="parent-1",
        return_thread_id="parent-1",
        branch_name="test-branch",
        branch_role=BranchRole.DEEP_DIVE,
        branch_status=BranchStatus.ACTIVE,
    )
    payload = build_trace_metadata(
        settings=settings,
        thread_id="thread-1",
        user_id="user-1",
        root_thread_id="root-1",
        branch_meta=meta,
    )
    assert payload["thread_id"] == "thread-1"
    assert payload["root_thread_id"] == "root-1"
    assert payload["branch_id"] == "b1"
    assert payload["branch_role"] == "deep_dive"


def test_trace_tags_include_root_and_thread():
    tags = build_trace_tags(root_thread_id="root-1", thread_id="thread-1")
    assert "root:root-1" in tags
    assert "thread:thread-1" in tags

def test_trace_tags_include_branch_status():
    tags = build_trace_tags(
        root_thread_id="root-1",
        thread_id="thread-1",
        branch_meta=BranchMeta(
            branch_id="b2",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            return_thread_id="root-1",
            branch_name="branch",
            branch_role=BranchRole.VERIFY,
            branch_status=BranchStatus.ACTIVE,
        ),
    )

    assert "status:active" in tags


def test_trace_span_facade_preserves_correlation_ids():
    settings = Settings(tracing_enabled=True, tracing_service_name="focus-agent-test")
    correlation = build_trace_correlation(settings=settings, request_id="req-123")

    with start_trace_span(
        name="focus_agent.turn",
        settings=settings,
        trace_correlation=correlation,
        span_id=correlation.root_span_id,
    ) as root_span:
        with start_trace_span(name="focus_agent.child") as child_span:
            child_payload = child_span.runtime_payload()

    assert root_span.runtime_payload()["trace_id"] == correlation.trace_id
    assert root_span.runtime_payload()["span_id"] == correlation.root_span_id
    assert root_span.span is not None
    assert root_span.span.attributes["service.name"] == "focus-agent-test"
    assert child_payload["trace_id"] == correlation.trace_id
    assert child_payload["parent_span_id"] == correlation.root_span_id
    assert len(child_payload["span_id"]) == 16


def test_disabled_trace_span_facade_is_noop():
    settings = Settings(tracing_enabled=False)
    correlation = build_trace_correlation(settings=settings, request_id="req-123")

    with start_trace_span(
        name="focus_agent.turn",
        settings=settings,
        trace_correlation=correlation,
        span_id=correlation.root_span_id,
    ) as span:
        assert span.runtime_payload() == {}


def test_tool_runtime_adds_span_metadata_when_tracing_enabled():
    class EchoTool:
        metadata = {"display_name": "Echo"}

        def invoke(self, args):
            return f"echo:{args['text']}"

    settings = Settings(tracing_enabled=True)
    correlation = build_trace_correlation(settings=settings, request_id="req-tool")
    item = ToolExecutionInput(
        index=0,
        tool_call_id="call-1",
        tool_name="echo",
        args={"text": "hello"},
        tool=EchoTool(),
        runtime=ToolRuntimeMeta(),
    )

    with start_trace_span(
        name="focus_agent.turn",
        settings=settings,
        trace_correlation=correlation,
        span_id=correlation.root_span_id,
    ):
        result = execute_tool_calls(
            [item],
            context_budget=ContextBudget(),
        )[0]

    runtime = result.message.artifact["runtime"]
    assert runtime["trace_id"] == correlation.trace_id
    assert runtime["parent_span_id"] == correlation.root_span_id
    assert len(runtime["span_id"]) == 16
    assert runtime["duration_ms"] >= 0
