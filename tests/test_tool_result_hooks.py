import json
from types import SimpleNamespace

from focus_agent.capabilities.tool_messages import build_tool_message
from focus_agent.capabilities.tool_runtime import ToolExecutionResult
from focus_agent.engine.graph import tool_execution, tool_result_hooks
from focus_agent.harness.extensions import ToolResultInterception as ExtensionInterception
from focus_agent.harness.middleware import ToolResultInterception as MiddlewareInterception


def _result(
    content: str = '{"answer":"original"}',
    *,
    status: str = "success",
    cache_hit: bool = True,
) -> ToolExecutionResult:
    return ToolExecutionResult(
        index=3,
        cache_hit=cache_hit,
        message=build_tool_message(
            content=content,
            tool_call_id="call-3",
            tool_name="lookup",
            prompt_observation="original observation",
            status=status,
            runtime_info={"duration_ms": 12},
        ),
    )


def test_tool_execution_keeps_compatibility_exports():
    assert tool_execution._apply_result_hooks is tool_result_hooks._apply_result_hooks
    assert (
        tool_execution._patch_tool_message_content is tool_result_hooks._patch_tool_message_content
    )
    assert tool_execution._patch_tool_message_error is tool_result_hooks._patch_tool_message_error


def test_patch_tool_message_content_preserves_metadata_without_mutating_source():
    source = _result()

    patched = tool_result_hooks._patch_tool_message_content(
        source.message,
        {"answer": "patched"},
    )

    assert json.loads(str(patched.content)) == {"answer": "patched"}
    assert patched.tool_call_id == "call-3"
    assert patched.status == "success"
    assert patched.artifact == {
        "runtime": {"duration_ms": 12, "content_patched": True},
        "tool_name": "lookup",
        "prompt_observation": "original observation",
    }
    assert source.message.content == '{"answer":"original"}'
    assert source.message.artifact["runtime"] == {"duration_ms": 12}


def test_patch_tool_message_error_preserves_args_and_runtime():
    source = _result(
        '{"status":"error","args":{"query":"focus"},"error":"original"}',
        status="error",
    )

    patched = tool_result_hooks._patch_tool_message_error(source.message, "patched failure")

    payload = json.loads(str(patched.content))
    assert payload["status"] == "error"
    assert payload["tool"] == "lookup"
    assert payload["args"] == {"query": "focus"}
    assert payload["error"] == "patched failure"
    assert patched.status == "error"
    assert patched.artifact["runtime"] == {
        "cache_hit": False,
        "fallback_used": False,
        "duration_ms": 12,
        "error_patched": True,
    }
    assert source.message.content.endswith('"error":"original"}')


def test_apply_result_hooks_runs_middleware_before_extensions_and_returns_new_result():
    calls: list[tuple[str, str, object]] = []

    class MiddlewareStack:
        def intercept_tool_result(self, tool_name, result, *, ctx):
            calls.append(("middleware", tool_name, ctx))
            assert result.content == '{"answer":"original"}'
            return MiddlewareInterception(patched_content={"answer": "middleware"})

    class ExtensionRegistry:
        def fire_hook(self, event_name, ext_ctx, **kwargs):
            calls.append(("extension", kwargs["tool_name"], ext_ctx))
            assert event_name == "on_tool_result"
            assert json.loads(str(kwargs["result"].content)) == {"answer": "middleware"}
            return [ExtensionInterception(patched_content={"answer": "extension"})]

    source = _result()
    ext_ctx = object()
    services = SimpleNamespace(
        middleware_stack=MiddlewareStack(),
        extension_registry=ExtensionRegistry(),
    )

    patched_results = tool_result_hooks._apply_result_hooks(
        [source],
        services=services,
        ext_ctx=ext_ctx,
        thread_id="thread-1",
        run_id="run-1",
        active_agent_name="focus_agent",
    )

    assert calls == [
        (
            "middleware",
            "lookup",
            {
                "thread_id": "thread-1",
                "run_id": "run-1",
                "agent_name": "focus_agent",
            },
        ),
        ("extension", "lookup", ext_ctx),
    ]
    assert patched_results[0] is not source
    assert patched_results[0].index == source.index
    assert patched_results[0].cache_hit is True
    assert json.loads(str(patched_results[0].message.content)) == {"answer": "extension"}
    assert source.message.content == '{"answer":"original"}'


def test_apply_result_hooks_isolates_middleware_failures_and_runs_extension():
    class FailingMiddlewareStack:
        def intercept_tool_result(self, tool_name, result, *, ctx):
            raise RuntimeError("middleware failed")

    class ExtensionRegistry:
        def fire_hook(self, event_name, ext_ctx, **kwargs):
            return [ExtensionInterception(patched_error="extension failure")]

    source = _result('{"args":{"query":"focus"},"answer":"original"}')
    services = SimpleNamespace(
        middleware_stack=FailingMiddlewareStack(),
        extension_registry=ExtensionRegistry(),
    )

    patched_results = tool_result_hooks._apply_result_hooks(
        [source],
        services=services,
        ext_ctx=object(),
        thread_id="thread-1",
        run_id=None,
        active_agent_name="focus_agent",
    )

    payload = json.loads(str(patched_results[0].message.content))
    assert payload["error"] == "extension failure"
    assert payload["args"] == {"query": "focus"}
    assert source.message.status == "success"


def test_apply_result_hooks_keeps_fast_path_results_unchanged():
    results = [_result()]

    assert (
        tool_result_hooks._apply_result_hooks(
            results,
            services=None,
            ext_ctx=None,
            thread_id="thread-1",
            run_id=None,
            active_agent_name="focus_agent",
        )
        is results
    )
