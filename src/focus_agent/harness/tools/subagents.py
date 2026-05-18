from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from ..subagents.executor import (
    DEFAULT_SUBAGENT_MAX_PARALLEL,
    SubagentExecutor,
    SubagentTaskRequest,
)
from ..subagents.fake import FakeSubagentRunner


class SubagentTaskToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(..., min_length=1)
    thread_id: str | None = None
    assistant_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    input: dict[str, Any] = Field(default_factory=dict)


def create_subagent_task_tool(
    executor: SubagentExecutor | None = None,
    *,
    name: str = "task",
    description: str = "Run a bounded harness subagent task.",
    max_parallel: int = DEFAULT_SUBAGENT_MAX_PARALLEL,
) -> StructuredTool:
    """Create a harness task tool that returns a ToolResultEnvelope payload."""

    effective_executor = executor or SubagentExecutor(
        FakeSubagentRunner(),
        max_parallel=max_parallel,
    )

    async def _run_task(
        instruction: str,
        thread_id: str | None = None,
        assistant_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        envelope = await effective_executor.execute(
            SubagentTaskRequest(
                instruction=instruction,
                thread_id=thread_id,
                assistant_id=assistant_id,
                metadata=dict(metadata or {}),
                input=dict(input or {}),
            ),
            tool_name=name,
        )
        return envelope.model_dump(mode="json")

    def _run_task_sync(
        instruction: str,
        thread_id: str | None = None,
        assistant_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return asyncio.run(
            _run_task(
                instruction=instruction,
                thread_id=thread_id,
                assistant_id=assistant_id,
                metadata=metadata,
                input=input,
            )
        )

    tool = StructuredTool.from_function(
        func=_run_task_sync,
        coroutine=_run_task,
        name=name,
        description=description,
        args_schema=SubagentTaskToolInput,
    )
    tool.metadata = {
        "display_name": "Task",
        "parallel_safe": True,
        "cacheable": False,
        "toolset": "subagent",
        "risk_level": "low",
        "max_parallel": effective_executor.max_parallel,
        "provider_id": "harness_subagents",
    }
    return tool
