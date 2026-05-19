from __future__ import annotations

# ruff: noqa: E402
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from langchain.messages import ToolMessage

from focus_agent.capabilities.tool_execution_types import ToolExecutionInput, ToolExecutionResult
from focus_agent.capabilities.tool_parallel import run_parallel_batch
from focus_agent.capabilities.tool_registry import ToolRuntimeMeta
from focus_agent.core.types import ContextBudget
from focus_agent.runtime.thread_pool import shutdown_thread_pool


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark parallel tool batch dispatch.")
    parser.add_argument("--tools", type=int, default=10)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.01)
    args = parser.parse_args()

    tool_count = max(1, args.tools)
    workers = max(1, args.workers or tool_count)
    sleep_seconds = max(0.0, args.sleep)
    runtime = ToolRuntimeMeta(parallel_safe=True)
    items = [
        ToolExecutionInput(
            index=index,
            tool_call_id=f"bench-call-{index}",
            tool_name="bench_tool",
            args={"index": index},
            tool=None,
            runtime=runtime,
        )
        for index in range(tool_count)
    ]

    def execute_single(
        item: ToolExecutionInput,
        _context_budget: ContextBudget,
        _cache_store: object,
        _cache_scope_key: str | None,
        _parallel_batch_size: int | None,
    ) -> ToolExecutionResult:
        time.sleep(sleep_seconds)
        return ToolExecutionResult(
            index=item.index,
            message=ToolMessage(
                content=f"ok:{item.index}",
                tool_call_id=item.tool_call_id,
                name=item.tool_name,
            ),
        )

    started = time.perf_counter()
    results = run_parallel_batch(
        items,
        context_budget=ContextBudget(),
        cache_store=None,
        cache_scope_keys={},
        max_parallel_workers=workers,
        execute_single=execute_single,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(
        "tool_parallel_bench "
        f"tools={tool_count} workers={workers} sleep_ms={sleep_seconds * 1000:.2f} "
        f"elapsed_ms={elapsed_ms:.2f} results={len(results)}"
    )
    shutdown_thread_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
