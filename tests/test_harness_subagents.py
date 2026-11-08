import asyncio
import inspect

from focus_agent.harness.subagents import (
    SubagentExecutor,
    SubagentTaskRequest,
    SubagentTaskResult,
)


class _FakeRunner:
    def __init__(self, handler):
        self._handler = handler

    async def run(self, request, *, run_record):
        result = self._handler(request, run_record)
        if inspect.isawaitable(result):
            return await result
        return result


def test_subagent_executor_rejects_when_parallel_limit_is_reached():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(request, run_record):
            started.set()
            await release.wait()
            return SubagentTaskResult(content="done")

        executor = SubagentExecutor(_FakeRunner(handler), max_parallel=1)
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

        executor = SubagentExecutor(_FakeRunner(handler))
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

        executor = SubagentExecutor(_FakeRunner(handler))
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
