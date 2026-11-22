from __future__ import annotations

import pytest

from focus_agent.capabilities.tool_execution import execute_single
from focus_agent.capabilities.tool_execution_types import (
    ToolExecutionInput,
    ToolExecutionResult,
    operation_fingerprint,
)
from focus_agent.capabilities.tool_messages import annotate_tool_result_runtime, build_tool_message
from focus_agent.capabilities.tool_registry import ToolRuntimeMeta
from focus_agent.core.types import ContextBudget


def test_operation_fingerprint_is_canonical_and_argument_order_sensitive():
    left = {"z": 1, "nested": {"b": 2, "a": [3, 4]}, "empty": None}
    right = {"nested": {"a": [3, 4], "b": 2}, "empty": None, "z": 1}
    reordered_list = {"nested": {"a": [4, 3], "b": 2}, "empty": None, "z": 1}

    first = operation_fingerprint("record_operation", left, ToolRuntimeMeta())
    second = operation_fingerprint("record_operation", right, ToolRuntimeMeta())

    assert first == second
    assert len(first) == 64
    assert first != operation_fingerprint("record_operation", reordered_list, ToolRuntimeMeta())
    assert first != operation_fingerprint("other_tool", left, ToolRuntimeMeta())


def test_operation_fingerprint_uses_redacted_args_and_stable_retry_identity():
    runtime = ToolRuntimeMeta(sensitive_args=("token",))
    public = operation_fingerprint("record_operation", {"token": "a", "value": 1}, runtime)
    alternate_secret = operation_fingerprint(
        "record_operation", {"token": "b", "value": 1}, runtime
    )
    changed_public = operation_fingerprint("record_operation", {"token": "a", "value": 2}, runtime)

    assert public == alternate_secret
    assert public != changed_public


def test_operation_fingerprint_rejects_non_json_shapes_and_unknown_tool():
    assert operation_fingerprint("record_operation", "not-a-dict", ToolRuntimeMeta()) is None
    assert operation_fingerprint("record_operation", {1: "x"}, ToolRuntimeMeta()) is None
    assert operation_fingerprint("record_operation", {"x": {1: "x"}}, ToolRuntimeMeta()) is None
    assert operation_fingerprint("record_operation", {"x": object()}, ToolRuntimeMeta()) is None
    assert operation_fingerprint("unknown_tool", {"x": 1}, ToolRuntimeMeta()) is None


class _Tool:
    def invoke(self, args):
        return "ok"


def test_executor_attaches_redacted_operation_fingerprint_to_results():
    runtime = ToolRuntimeMeta(sensitive_args=("token",))
    result = execute_single(
        ToolExecutionInput(
            index=0,
            tool_call_id="call-1",
            tool_name="record_operation",
            args={"token": "secret", "value": 1},
            tool=_Tool(),
            runtime=runtime,
        ),
        context_budget=ContextBudget(),
        cache_store=None,
        cache_scope_key=None,
        parallel_batch_size=None,
    )

    artifact = result.message.artifact
    assert artifact["runtime"]["operation_fingerprint"] == operation_fingerprint(
        "record_operation",
        {"token": "secret", "value": 1},
        runtime,
    )
    assert artifact["runtime"]["operation_fingerprint_redacted_args"] is True
    assert "secret" not in artifact["runtime"]["operation_fingerprint"]


def test_operation_fingerprint_is_stable_across_retry_attempt_ids():
    runtime = ToolRuntimeMeta(sensitive_args=("token",))
    args = {"token": "secret", "value": 1}
    first = execute_single(
        ToolExecutionInput(
            index=0,
            tool_call_id="call-attempt-1",
            tool_name="record_operation",
            args=args,
            tool=_Tool(),
            runtime=runtime,
        ),
        context_budget=ContextBudget(),
        cache_store=None,
        cache_scope_key=None,
        parallel_batch_size=None,
    )
    second = execute_single(
        ToolExecutionInput(
            index=0,
            tool_call_id="call-attempt-2",
            tool_name="record_operation",
            args=args,
            tool=_Tool(),
            runtime=runtime,
        ),
        context_budget=ContextBudget(),
        cache_store=None,
        cache_scope_key=None,
        parallel_batch_size=None,
    )

    assert (
        first.message.artifact["runtime"]["operation_fingerprint"]
        == (second.message.artifact["runtime"]["operation_fingerprint"])
    )


def test_executor_propagates_declared_runtime_operation_metadata():
    runtime = ToolRuntimeMeta(
        side_effect=True,
        operation_id="update_address",
        execution_version="v1",
        superseded_by="v2",
    )
    result = execute_single(
        ToolExecutionInput(
            index=0,
            tool_call_id="call-1",
            tool_name="record_operation",
            args={"value": 1},
            tool=_Tool(),
            runtime=runtime,
        ),
        context_budget=ContextBudget(),
        cache_store=None,
        cache_scope_key=None,
        parallel_batch_size=None,
    )

    runtime_info = result.message.artifact["runtime"]
    assert runtime_info["operation_id"] == "update_address"
    assert runtime_info["execution_version"] == "v1"
    assert runtime_info["superseded_by"] == "v2"
    assert runtime_info["side_effect_serialized"] is True


def test_operation_fingerprint_allows_wide_arguments():
    args = {"items": [{"a": index} for index in range(65)]}
    assert operation_fingerprint("record_operation", args, ToolRuntimeMeta())


def test_tuple_nested_sensitive_args_are_redacted_like_lists():
    runtime = ToolRuntimeMeta(sensitive_args=("token",))
    list_result = operation_fingerprint("record_operation", [{"token": "A"}], runtime)
    tuple_result = operation_fingerprint("record_operation", ({"token": "A"},), runtime)

    assert list_result == tuple_result
    assert operation_fingerprint("record_operation", ({"token": "B"},), runtime) == tuple_result


def test_operation_fingerprint_bounds_shared_reference_traversal():
    shared = []
    args = {"items": [shared] * 10001}
    assert operation_fingerprint("record_operation", args, ToolRuntimeMeta()) is None


def test_operation_fingerprint_handles_cycles_and_deep_nesting():
    cyclic = {}
    cyclic["self"] = cyclic
    assert operation_fingerprint("record_operation", cyclic, ToolRuntimeMeta()) is None
    deeply_nested = value = []
    for _ in range(100):
        child = []
        value.append(child)
        value = child
    assert operation_fingerprint("record_operation", deeply_nested, ToolRuntimeMeta()) is None


def test_operation_fingerprint_rejects_unredacted_policy():
    assert (
        operation_fingerprint(
            "record_operation",
            {"password": "hunter2"},
            ToolRuntimeMeta(redaction_policy="none"),
        )
        is None
    )


def test_operation_fingerprint_accepts_json_tuples():
    assert operation_fingerprint("record_operation", {"x": (1, 2)}, ToolRuntimeMeta())


class _MutatingTool:
    def invoke(self, args):
        args["values"].sort()
        return "ok"


def test_executor_computes_fingerprint_before_tool_mutation():
    runtime = ToolRuntimeMeta()
    args = {"values": [2, 1]}
    expected = operation_fingerprint("record_operation", args, runtime)
    result = execute_single(
        ToolExecutionInput(
            index=0,
            tool_call_id="call-mutating",
            tool_name="record_operation",
            args=args,
            tool=_MutatingTool(),
            runtime=runtime,
        ),
        context_budget=ContextBudget(),
        cache_store=None,
        cache_scope_key=None,
        parallel_batch_size=None,
    )

    assert result.message.artifact["runtime"]["operation_fingerprint"] == expected
    assert args["values"] == [1, 2]


@pytest.mark.parametrize("bad", [float("inf"), float("-inf")])
def test_operation_fingerprint_rejects_infinite_numbers(bad):
    assert operation_fingerprint("record_operation", {"value": bad}, ToolRuntimeMeta()) is None


def test_runtime_annotation_accepts_only_harness_operation_metadata():
    result = ToolExecutionResult(
        index=0,
        message=build_tool_message(
            content="ok",
            tool_call_id="call-1",
            tool_name="record_operation",
            runtime_info={
                "operation_id": "tool-spoof",
                "execution_version": "tool-spoof",
                "superseded_by": "tool-spoof",
            },
        ),
    )
    annotate_tool_result_runtime(result, {"operation_fingerprint": "a" * 64})
    assert "operation_id" not in result.message.artifact["runtime"]
    assert "execution_version" not in result.message.artifact["runtime"]
    assert "superseded_by" not in result.message.artifact["runtime"]

    annotate_tool_result_runtime(
        result,
        {},
        harness_operation_metadata={
            "operation_id": "update_address",
            "execution_version": "v1",
            "superseded_by": "v2",
            "ignored": "not-allowed",
        },
    )
    assert result.message.artifact["runtime"]["operation_id"] == "update_address"
    assert result.message.artifact["runtime"]["execution_version"] == "v1"
    assert result.message.artifact["runtime"]["superseded_by"] == "v2"
    assert "ignored" not in result.message.artifact["runtime"]

    result.message.artifact["runtime"]["operation_id"] = "tool-spoof"
    annotate_tool_result_runtime(result, {})
    assert "operation_id" not in result.message.artifact["runtime"]
    assert "operation_fingerprint" not in result.message.artifact["runtime"]
    assert "operation_fingerprint_redacted_args" not in result.message.artifact["runtime"]
