import json
import time

from langchain.tools import tool

from focus_agent.capabilities.tool_runtime import ToolExecutionInput, ToolResultCacheStore, execute_tool_calls
from focus_agent.capabilities.tool_registry import ToolRuntimeMeta
from focus_agent.core.types import ContextBudget


def test_tool_runtime_uses_fallback_handler_when_primary_tool_fails():
    @tool
    def unstable_search(query: str) -> str:
        """Primary lookup that fails."""
        raise RuntimeError(f"primary failed: {query}")

    def _fallback_handler(error: Exception, args: dict[str, object]) -> str:
        return json.dumps(
            {
                "provider": "fallback",
                "query": args["query"],
                "error": str(error),
            },
            ensure_ascii=False,
        )

    unstable_search.metadata = {
        "parallel_safe": True,
        "fallback_group": "search",
        "fallback_handler": _fallback_handler,
    }

    result = execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="call-1",
                tool_name="unstable_search",
                args={"query": "focus"},
                tool=unstable_search,
                runtime=ToolRuntimeMeta.from_tool(unstable_search),
            )
        ],
        context_budget=ContextBudget(),
        cache_store=ToolResultCacheStore(),
    )[0]

    payload = json.loads(result.message.content)
    assert result.message.status == "success"
    assert payload["provider"] == "fallback"
    assert payload["query"] == "focus"
    assert result.message.artifact["runtime"]["fallback_used"] is True
    assert result.message.artifact["runtime"]["fallback_group"] == "search"


def test_tool_runtime_emits_parallel_and_cache_hit_events(monkeypatch):
    events = []

    monkeypatch.setattr(
        "focus_agent.capabilities.tool_runtime.get_stream_writer",
        lambda: lambda event: events.append(event),
    )

    @tool
    def cacheable_lookup(name: str) -> str:
        """Cacheable lookup."""
        return name

    cacheable_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
    }

    runtime = ToolRuntimeMeta.from_tool(cacheable_lookup)
    cache_store = ToolResultCacheStore()

    execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="call-a",
                tool_name="cacheable_lookup",
                args={"name": "alpha"},
                tool=cacheable_lookup,
                runtime=runtime,
            ),
            ToolExecutionInput(
                index=1,
                tool_call_id="call-b",
                tool_name="cacheable_lookup",
                args={"name": "alpha"},
                tool=cacheable_lookup,
                runtime=runtime,
            ),
        ],
        context_budget=ContextBudget(),
        cache_store=cache_store,
        cache_scope_keys={0: "thread:test", 1: "thread:test"},
    )
    first_run_events = list(events)
    events.clear()

    execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="call-c",
                tool_name="cacheable_lookup",
                args={"name": "alpha"},
                tool=cacheable_lookup,
                runtime=runtime,
            )
        ],
        context_budget=ContextBudget(),
        cache_store=cache_store,
        cache_scope_keys={0: "thread:test"},
    )

    assert any(event["stage"] == "parallel_dispatch" for event in first_run_events)
    assert any(event["stage"] == "cache_hit" for event in events)


def test_tool_runtime_deduplicates_identical_cacheable_calls_in_parallel_batch():
    call_count = 0

    @tool
    def cacheable_lookup(name: str) -> str:
        """Cacheable lookup."""
        nonlocal call_count
        call_count += 1
        return f"value:{name}"

    cacheable_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
    }
    runtime = ToolRuntimeMeta.from_tool(cacheable_lookup)

    results = execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="call-a",
                tool_name="cacheable_lookup",
                args={"name": "alpha"},
                tool=cacheable_lookup,
                runtime=runtime,
            ),
            ToolExecutionInput(
                index=1,
                tool_call_id="call-b",
                tool_name="cacheable_lookup",
                args={"name": "alpha"},
                tool=cacheable_lookup,
                runtime=runtime,
            ),
        ],
        context_budget=ContextBudget(),
        cache_store=ToolResultCacheStore(),
        cache_scope_keys={0: "thread:test", 1: "thread:test"},
    )

    assert call_count == 1
    assert [result.message.tool_call_id for result in results] == ["call-a", "call-b"]
    assert [result.message.content for result in results] == ["value:alpha", "value:alpha"]
    assert results[1].message.artifact["runtime"]["deduplicated"] is True
    assert results[1].message.artifact["runtime"]["cache_hit"] is True


def test_tool_runtime_deduplicates_fallback_results_in_parallel_batch():
    primary_count = 0
    fallback_count = 0

    @tool
    def unstable_lookup(query: str) -> str:
        """Lookup that uses fallback."""
        nonlocal primary_count
        primary_count += 1
        raise RuntimeError("primary down")

    def _fallback_handler(_error: Exception, args: dict[str, object]) -> str:
        nonlocal fallback_count
        fallback_count += 1
        return f"fallback:{args['query']}"

    unstable_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
        "fallback_group": "lookup",
        "fallback_handler": _fallback_handler,
    }
    runtime = ToolRuntimeMeta.from_tool(unstable_lookup)

    results = execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="call-a",
                tool_name="unstable_lookup",
                args={"query": "focus"},
                tool=unstable_lookup,
                runtime=runtime,
            ),
            ToolExecutionInput(
                index=1,
                tool_call_id="call-b",
                tool_name="unstable_lookup",
                args={"query": "focus"},
                tool=unstable_lookup,
                runtime=runtime,
            ),
        ],
        context_budget=ContextBudget(),
        cache_store=ToolResultCacheStore(),
        cache_scope_keys={0: "thread:test", 1: "thread:test"},
    )

    assert primary_count == 1
    assert fallback_count == 1
    assert [result.message.status for result in results] == ["success", "success"]
    assert [result.message.content for result in results] == ["fallback:focus", "fallback:focus"]
    assert results[1].message.artifact["runtime"]["fallback_used"] is True
    assert results[1].message.artifact["runtime"]["deduplicated"] is True


def test_tool_runtime_branch_scope_does_not_leak_between_branches():
    call_count = 0

    @tool
    def branch_lookup(name: str) -> str:
        """Branch-scoped lookup."""
        nonlocal call_count
        call_count += 1
        return name

    branch_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "branch",
    }

    runtime = ToolRuntimeMeta.from_tool(branch_lookup)
    cache_store = ToolResultCacheStore()

    execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="call-a",
                tool_name="branch_lookup",
                args={"name": "alpha"},
                tool=branch_lookup,
                runtime=runtime,
            )
        ],
        context_budget=ContextBudget(),
        cache_store=cache_store,
        cache_scope_keys={0: "branch:one"},
    )
    execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="call-b",
                tool_name="branch_lookup",
                args={"name": "alpha"},
                tool=branch_lookup,
                runtime=runtime,
            )
        ],
        context_budget=ContextBudget(),
        cache_store=cache_store,
        cache_scope_keys={0: "branch:one"},
    )
    execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="call-c",
                tool_name="branch_lookup",
                args={"name": "alpha"},
                tool=branch_lookup,
                runtime=runtime,
            )
        ],
        context_budget=ContextBudget(),
        cache_store=cache_store,
        cache_scope_keys={0: "branch:two"},
    )

    assert call_count == 2


def test_tool_runtime_side_effect_invalidates_named_cache_namespaces():
    read_count = 0

    @tool
    def read_lookup(name: str) -> str:
        """Cacheable read tool."""
        nonlocal read_count
        read_count += 1
        return name

    @tool
    def write_lookup(name: str) -> str:
        """Side-effect tool."""
        return f"wrote:{name}"

    read_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
    }
    write_lookup.metadata = {
        "side_effect": True,
    }

    cache_store = ToolResultCacheStore()

    execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="read-1",
                tool_name="read_lookup",
                args={"name": "alpha"},
                tool=read_lookup,
                runtime=ToolRuntimeMeta.from_tool(read_lookup),
            )
        ],
        context_budget=ContextBudget(),
        cache_store=cache_store,
        cache_scope_keys={0: "thread:demo"},
    )
    execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="write-1",
                tool_name="write_lookup",
                args={"name": "alpha"},
                tool=write_lookup,
                runtime=ToolRuntimeMeta.from_tool(write_lookup),
            )
        ],
        context_budget=ContextBudget(),
        cache_store=cache_store,
        cache_scope_keys={0: "thread:demo"},
        invalidation_scope_keys=["thread:demo"],
    )
    execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="read-2",
                tool_name="read_lookup",
                args={"name": "alpha"},
                tool=read_lookup,
                runtime=ToolRuntimeMeta.from_tool(read_lookup),
            )
        ],
        context_budget=ContextBudget(),
        cache_store=cache_store,
        cache_scope_keys={0: "thread:demo"},
    )

    assert read_count == 2


def test_tool_runtime_times_out_read_only_tool_without_fallback_or_cache():
    fallback_count = 0

    @tool
    def slow_lookup(name: str) -> str:
        """Slow read-only lookup."""
        time.sleep(0.2)
        return f"value:{name}"

    def _fallback_handler(_error: Exception, args: dict[str, object]) -> str:
        nonlocal fallback_count
        fallback_count += 1
        return f"fallback:{args['name']}"

    slow_lookup.metadata = {
        "parallel_safe": True,
        "cacheable": True,
        "cache_scope": "thread",
        "timeout_seconds": 0.05,
        "fallback_group": "lookup",
        "fallback_handler": _fallback_handler,
    }

    cache_store = ToolResultCacheStore()

    started = time.perf_counter()
    result = execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="call-timeout",
                tool_name="slow_lookup",
                args={"name": "alpha"},
                tool=slow_lookup,
                runtime=ToolRuntimeMeta.from_tool(slow_lookup),
            )
        ],
        context_budget=ContextBudget(),
        cache_store=cache_store,
        cache_scope_keys={0: "thread:test"},
    )[0]
    elapsed = time.perf_counter() - started

    payload = json.loads(result.message.content)

    assert elapsed < 0.16
    assert result.message.status == "error"
    assert "timed out" in payload["error"]
    assert fallback_count == 0
    assert cache_store.thread == {}
    assert result.message.artifact["runtime"]["timed_out"] is True
    assert result.message.artifact["runtime"]["timeout_seconds"] == 0.05
    assert result.message.artifact["runtime"]["fallback_used"] is False


def test_tool_runtime_does_not_apply_runtime_timeout_to_side_effect_tools():
    writes: list[str] = []

    @tool
    def write_lookup(name: str) -> str:
        """Side-effect tool that should not be detached on timeout."""
        time.sleep(0.08)
        writes.append(name)
        return f"wrote:{name}"

    write_lookup.metadata = {
        "side_effect": True,
        "timeout_seconds": 0.01,
    }

    started = time.perf_counter()
    result = execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="write-timeout",
                tool_name="write_lookup",
                args={"name": "alpha"},
                tool=write_lookup,
                runtime=ToolRuntimeMeta.from_tool(write_lookup),
            )
        ],
        context_budget=ContextBudget(),
        cache_store=ToolResultCacheStore(),
    )[0]
    elapsed = time.perf_counter() - started

    assert elapsed >= 0.06
    assert result.message.status == "success"
    assert result.message.content == "wrote:alpha"
    assert writes == ["alpha"]
