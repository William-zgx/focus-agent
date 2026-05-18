import asyncio

from focus_agent.capabilities import ToolRegistry
from focus_agent.config import Settings
from focus_agent.harness import HarnessConfig, create_focus_agent
from focus_agent.harness.subagents import (
    AgentTeamSubagentRunner,
    FakeSubagentRunner,
    SubagentExecutor,
    SubagentTaskRequest,
    SubagentTaskResult,
)
from focus_agent.harness.tools import create_subagent_task_tool


def test_subagent_executor_rejects_when_parallel_limit_is_reached():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(request, run_record):
            started.set()
            await release.wait()
            return SubagentTaskResult(content="done")

        executor = SubagentExecutor(FakeSubagentRunner(handler), max_parallel=1)
        first = asyncio.create_task(executor.execute(SubagentTaskRequest("hold")))
        await started.wait()

        second = await executor.execute(SubagentTaskRequest("overflow"), tool_call_id="call-2")
        assert second.status == "error"
        assert second.tool_call_id == "call-2"
        assert second.runtime["reason"] == "parallelism_limit"
        assert "limit reached" in second.content

        release.set()
        assert (await first).status == "success"

    asyncio.run(scenario())


def test_subagent_executor_returns_success_artifact_and_run_metadata():
    async def scenario():
        def handler(request, run_record):
            return SubagentTaskResult(
                content="wrote artifact",
                metadata={"model": "fake-worker"},
                artifact={"output": {"path": "artifact://task-1"}},
            )

        executor = SubagentExecutor(FakeSubagentRunner(handler))
        envelope = await executor.execute(
            SubagentTaskRequest(
                "write report",
                thread_id="parent-thread",
                assistant_id="worker-e",
                metadata={"parent_run_id": "run-parent"},
            ),
            tool_call_id="call-1",
            tool_name="task",
        )

        assert envelope.status == "success"
        assert envelope.content == "wrote artifact"
        assert envelope.runtime["executor"] == "subagent"
        assert envelope.runtime["model"] == "fake-worker"
        assert envelope.runtime["thread_id"] == "parent-thread"
        assert envelope.artifact["output"] == {"path": "artifact://task-1"}
        assert envelope.artifact["run"]["metadata"]["parent_run_id"] == "run-parent"

    asyncio.run(scenario())


def test_subagent_executor_converts_runner_error_to_envelope():
    async def scenario():
        def handler(request, run_record):
            raise RuntimeError("boom")

        executor = SubagentExecutor(FakeSubagentRunner(handler))
        envelope = await executor.execute(
            SubagentTaskRequest("explode"),
            tool_call_id="call-error",
        )

        assert envelope.status == "error"
        assert envelope.tool_call_id == "call-error"
        assert envelope.runtime["error_type"] == "RuntimeError"
        assert "boom" in envelope.content
        assert envelope.artifact["run"]["status"] == "error"

    asyncio.run(scenario())


def test_task_tool_factory_returns_envelope_payload_with_runtime_metadata():
    async def scenario():
        executor = SubagentExecutor(FakeSubagentRunner())
        task_tool = create_subagent_task_tool(executor)

        payload = await task_tool.ainvoke(
            {
                "instruction": "summarize",
                "thread_id": "thread-tool",
                "metadata": {"parent": "root"},
            }
        )

        assert payload["tool_name"] == "task"
        assert payload["status"] == "success"
        assert payload["runtime"]["executor"] == "subagent"
        assert payload["runtime"]["thread_id"] == "thread-tool"
        assert payload["artifact"]["run"]["metadata"]["parent"] == "root"
        assert task_tool.metadata["toolset"] == "subagent"

    asyncio.run(scenario())


def test_agent_team_subagent_runner_bridges_to_existing_fake_delegated_executor():
    async def scenario():
        run_manager = SubagentExecutor(
            AgentTeamSubagentRunner(settings=Settings(agent_delegation_execution_mode="fake"))
        )
        envelope = await run_manager.execute(
            SubagentTaskRequest(
                "review harness",
                metadata={
                    "role": "critic",
                    "allowed_tools": ["read_file"],
                    "acceptance_criteria": ["stable result"],
                },
            ),
            tool_call_id="call-agent-team",
        )

        assert envelope.status == "success"
        assert envelope.tool_call_id == "call-agent-team"
        assert envelope.runtime["execution_mode"] == "fake"
        assert envelope.runtime["role"] == "critic"
        assert envelope.artifact["artifacts"][0]["payload"]["allowed_tools"] == ["read_file"]

    asyncio.run(scenario())


def test_create_focus_agent_injects_task_tool_when_subagents_enabled(monkeypatch):
    captured = {}

    def fake_build_graph(**kwargs):
        captured["tool_registry"] = kwargs["tool_registry"]
        return object()

    monkeypatch.setattr("focus_agent.engine.graph_builder.build_graph", fake_build_graph)
    harness = create_focus_agent(
        HarnessConfig(subagents={"enabled": True, "max_concurrent_subagents": 2}),
        settings=Settings(agent_delegation_execution_mode="observe"),
        tool_registry=ToolRegistry(tools=()),
    )

    assert harness.subagent_executor is not None
    assert harness.subagent_executor.max_parallel == 2
    assert "task" in captured["tool_registry"].by_name
    assert captured["tool_registry"].runtime_by_name["task"].toolset == "subagent"
