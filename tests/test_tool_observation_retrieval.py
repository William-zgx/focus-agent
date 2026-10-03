import json
import types
from pathlib import Path

import pytest
from langchain.messages import AIMessage, HumanMessage
from langchain.tools import tool

from focus_agent.capabilities.default_tool_modules.artifact import build_artifact_tools
from focus_agent.capabilities.tool_messages import build_tool_message
from focus_agent.capabilities.tool_registry import ToolRuntimeMeta
from focus_agent.capabilities.tool_runtime import ToolExecutionInput, execute_tool_calls
from focus_agent.config import Settings
from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import ContextBudget
from focus_agent.storage import LocalArtifactStore


def _artifact_tools(tmp_path: Path, current_thread: list[str | None], *, repository=None):
    settings = Settings(
        workspace_root=str(tmp_path),
        artifact_dir=str(tmp_path / "artifacts"),
    )
    tools, _ = build_artifact_tools(
        artifact_dir=Path(settings.artifact_dir),
        workspace_root=Path(settings.workspace_root),
        settings=settings,
        tool_catalog=settings.tool_catalog,
        artifact_store=LocalArtifactStore(settings.artifact_dir),
        artifact_metadata_repository=repository,
        emit_tool_event=lambda **_: None,
        get_current_thread_id=lambda: current_thread[0],
    )
    return tools


def _execute(tool_obj, *, tool_call_id: str, observation_saver=None, thread_id=None):
    result = execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id=tool_call_id,
                tool_name=tool_obj.name,
                args={},
                tool=tool_obj,
                runtime=ToolRuntimeMeta.from_tool(tool_obj),
            )
        ],
        context_budget=ContextBudget(
            tool_observation_token_limit=32,
            chars_per_token=1,
            tool_reference_token_limit=16,
        ),
        observation_saver=observation_saver,
        observation_thread_id=thread_id,
    )[0]
    return result


def test_trimmed_observation_is_saved_and_read_in_scoped_ranges(tmp_path):
    current_thread = ["thread-a"]
    tools = _artifact_tools(tmp_path, current_thread)
    raw = "0123456789abcdef" * 8

    @tool
    def produce_observation() -> str:
        """Return a deliberately large observation."""
        return raw

    produce_observation.metadata = {
        "parallel_safe": True,
        "max_observation_chars": 24,
    }
    saver = tools["artifact_read"].metadata["_focus_agent_save_tool_observation"]
    result = _execute(
        produce_observation,
        tool_call_id="call-1",
        observation_saver=saver,
        thread_id="thread-a",
    )

    runtime = result.message.artifact["runtime"]
    assert runtime["observation_retrievable"] is True
    reference = "tool-observation://produce_observation/call-1"
    assert reference in result.message.artifact["prompt_observation"]

    payload = json.loads(
        tools["artifact_read"].invoke({"artifact_id": reference, "offset": 10, "limit": 12})
    )
    assert payload["content"] == raw[10:22]
    assert payload["total_chars"] == len(raw)
    assert payload["next_offset"] == 22
    assert payload["truncated"] is True

    with pytest.raises(PermissionError):
        tools["artifact_read"].invoke({"artifact_id": runtime["observation_artifact_id"]})
    current_thread[0] = "thread-b"
    with pytest.raises((PermissionError, FileNotFoundError)):
        tools["artifact_read"].invoke({"artifact_id": reference})


def test_reserved_observation_alias_cannot_bypass_scoped_read(tmp_path):
    class MetadataRepository:
        def __init__(self):
            self.records = {}

        def upsert_from_file(self, *, thread_id, artifact_id, path, title):
            self.records[artifact_id] = types.SimpleNamespace(
                artifact_id=artifact_id,
                thread_id=thread_id,
                path=str(path),
                title=title,
                size_bytes=Path(path).stat().st_size,
            )

        def get_by_artifact_id(self, artifact_id):
            return self.records.get(artifact_id)

    current_thread = ["thread-a"]
    repository = MetadataRepository()
    tools = _artifact_tools(tmp_path, current_thread, repository=repository)
    saver = tools["artifact_read"].metadata["_focus_agent_save_tool_observation"]
    internal_id = saver(
        tool_name="produce",
        tool_call_id="call-2",
        content="reserved content",
        thread_id="thread-a",
    )
    repository.records["alias.md"] = types.SimpleNamespace(
        artifact_id="alias.md",
        thread_id="thread-a",
        path=str(Path(tmp_path / "artifacts") / internal_id),
        title="Alias",
        size_bytes=16,
    )

    with pytest.raises(PermissionError):
        tools["artifact_read"].invoke({"artifact_id": "alias.md"})


def test_failed_save_and_artifact_read_trim_are_not_reported_as_retrievable():
    @tool
    def failing_save() -> str:
        """Return output whose persistence will fail."""
        return "x" * 120

    failing_save.metadata = {"max_observation_chars": 16}

    def fail_save(**_kwargs):
        raise OSError("disk unavailable")

    result = _execute(
        failing_save,
        tool_call_id="call-fail",
        observation_saver=fail_save,
        thread_id="thread-a",
    )
    runtime = result.message.artifact["runtime"]
    assert runtime["observation_retrievable"] is False
    assert "artifact_ref" not in str(result.message.artifact.get("prompt_observation"))
    assert result.message.content

    @tool
    def artifact_read() -> str:
        """Return a large nested read result."""
        return "y" * 120

    artifact_read.metadata = {"max_observation_chars": 16}
    saved_calls = []
    result = _execute(
        artifact_read,
        tool_call_id="call-read",
        observation_saver=lambda **kwargs: saved_calls.append(kwargs),
        thread_id="thread-a",
    )
    assert saved_calls == []
    assert result.message.artifact["runtime"]["observation_retrievable"] is False
    assert (
        "not recursively persisted"
        in result.message.artifact["runtime"]["observation_artifact_error"]
    )


def test_graph_uses_active_child_thread_for_observation_scope(monkeypatch):
    from focus_agent.capabilities.tool_execution_types import ToolExecutionResult
    from focus_agent.engine.graph import tool_execution as graph_tool_execution

    @tool
    def probe() -> str:
        """Return a probe result."""
        return "ok"

    probe.metadata = {"parallel_safe": True}
    captured: dict[str, object] = {}

    def fake_execute_tool_calls(inputs, **kwargs):
        captured.update(kwargs)
        return [
            ToolExecutionResult(
                index=inputs[0].index,
                message=build_tool_message(
                    content="ok",
                    tool_call_id=inputs[0].tool_call_id,
                    tool_name=inputs[0].tool_name,
                ),
            )
        ]

    monkeypatch.setattr(graph_tool_execution, "execute_tool_calls", fake_execute_tool_calls)
    monkeypatch.setattr(
        graph_tool_execution,
        "get_config",
        lambda: {"configurable": {"thread_id": "child-thread"}},
    )
    node = graph_tool_execution.make_tool_executor_node(
        tools_by_name={"probe": probe},
        tool_runtime_by_name={"probe": ToolRuntimeMeta.from_tool(probe)},
        tool_result_cache=graph_tool_execution.ToolResultCacheStore(),
    )
    state = {
        "messages": [
            HumanMessage(content="run probe"),
            AIMessage(
                content="",
                tool_calls=[{"id": "call-child", "name": "probe", "args": {}}],
            ),
        ],
        "context_budget": ContextBudget(),
    }
    runtime = type(
        "Runtime",
        (),
        {"context": RequestContext(user_id="u", root_thread_id="root-thread")},
    )()

    node(state, runtime)

    assert captured["observation_thread_id"] == "child-thread"
    assert captured["observation_thread_id"] != runtime.context.root_thread_id

    monkeypatch.setattr(graph_tool_execution, "get_config", lambda: {})
    captured.clear()
    node(state, runtime)
    assert captured["observation_thread_id"] is None
