from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable

from ..runtime import RunRecord
from .executor import SubagentTaskRequest, SubagentTaskResult

FakeSubagentHandler = Callable[
    [SubagentTaskRequest, RunRecord],
    SubagentTaskResult | Awaitable[SubagentTaskResult],
]


class FakeSubagentRunner:
    """Small fake runner for harness tests and local task-tool wiring."""

    def __init__(
        self,
        handler: FakeSubagentHandler | None = None,
        *,
        delay_seconds: float = 0.0,
    ) -> None:
        self._handler = handler
        self._delay_seconds = delay_seconds
        self.records: list[RunRecord] = []

    async def run(
        self,
        request: SubagentTaskRequest,
        *,
        run_record: RunRecord,
    ) -> SubagentTaskResult:
        self.records.append(run_record)
        if self._delay_seconds > 0:
            await asyncio.sleep(self._delay_seconds)
        if self._handler is None:
            return SubagentTaskResult(
                content=f"completed: {request.instruction}",
                metadata={"runner": "fake"},
                artifact={"output": {"instruction": request.instruction}},
            )
        result = self._handler(request, run_record)
        if inspect.isawaitable(result):
            result = await result
        return result
