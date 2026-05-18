from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from ...capabilities import ToolRegistry
from ...capabilities.tool_manifest import ToolManifest
from ..middleware import (
    DanglingToolCallMiddleware,
    LLMErrorHandlingMiddleware,
    LoopDetectionMiddleware,
    MiddlewareStack,
)
from ..observability import InMemoryRunJournal, JournaledStreamBridge, RunJournal
from ..runtime import RunManager
from ..runtime.rollback import rollback_handler_for_graph
from ..schemas import HarnessConfig
from ..streaming import InMemoryStreamBridge, canonical_event_payload
from ..subagents import AgentTeamSubagentRunner, SubagentExecutor
from ..tools import create_subagent_task_tool


@dataclass(slots=True)
class FocusAgentHarness:
    config: HarnessConfig
    graph: Any
    run_manager: RunManager
    stream_bridge: InMemoryStreamBridge | JournaledStreamBridge
    middleware: MiddlewareStack
    event_store: RunJournal
    subagent_executor: SubagentExecutor | None = None
    tool_registry: Any = None

    def invoke(self, payload: Any, **kwargs: Any) -> Any:
        """Invoke the graph through the harness middleware stack."""

        return self.middleware.invoke(self.graph.invoke, payload, **kwargs)

    async def stream_chunks(
        self,
        *,
        settings: Any,
        payload: Any,
        config: Any,
        context: Any,
        checkpointer: Any | None = None,
    ) -> AsyncIterator[dict[str, Any] | None]:
        """Stream graph chunks through the harness execution adapter."""

        from ...services.chat_streaming import stream_graph_chunks

        def _run_stream(state: Any) -> AsyncIterator[dict[str, Any] | None]:
            return stream_graph_chunks(
                graph=self.graph,
                checkpointer=checkpointer,
                settings=settings,
                payload=state,
                config=config,
                context=context,
            )

        chunks = self.middleware.invoke(_run_stream, payload)
        async for chunk in chunks:
            yield chunk


def create_focus_agent(
    config: HarnessConfig,
    *,
    settings: Any,
    model_provider: Any | None = None,
    tool_provider: Any | None = None,
    checkpointer: Any | None = None,
    store: Any | None = None,
    event_store: Any | None = None,
    memory_retriever: Any | None = None,
    memory_policy: Any | None = None,
    memory_writer: Any | None = None,
    memory_extractor: Any | None = None,
    skill_registry: Any | None = None,
    tool_registry: Any | None = None,
    approval_queue: Any | None = None,
    subagent_executor: SubagentExecutor | None = None,
) -> FocusAgentHarness:
    """Create the reusable Focus Agent harness around the existing graph.

    The first migration step keeps the explicit LangGraph graph, but moves
    runtime ownership into this factory so API/service layers no longer need to
    know how graph, runs, streaming, and stability middleware are assembled.
    """

    del tool_provider
    from ...engine.graph_builder import build_graph

    effective_subagent_executor = _subagent_executor_for_config(
        config=config,
        settings=settings,
        model_provider=model_provider,
        subagent_executor=subagent_executor,
    )
    effective_tool_registry = _tool_registry_with_subagent_task(
        tool_registry=tool_registry,
        config=config,
        subagent_executor=effective_subagent_executor,
    )
    graph = build_graph(
        settings=settings,
        checkpointer=checkpointer,
        store=store,
        memory_retriever=memory_retriever,
        memory_policy=memory_policy,
        memory_writer=memory_writer,
        memory_extractor=memory_extractor,
        skill_registry=skill_registry,
        tool_registry=effective_tool_registry,
        approval_queue=approval_queue,
    )
    middleware = list(config.middleware)
    features = config.features
    if features.loop_detection:
        middleware.append(LoopDetectionMiddleware())
    middleware.append(DanglingToolCallMiddleware())
    middleware.append(
        LLMErrorHandlingMiddleware(
            retry=config.retry,
            circuit_breaker=config.circuit_breaker,
        )
    )
    journal = event_store if event_store is not None else InMemoryRunJournal()
    stream_bridge = JournaledStreamBridge(
        journal=journal,
        bridge=InMemoryStreamBridge(max_buffer_size=config.streaming.event_buffer_size),
    )
    return FocusAgentHarness(
        config=config,
        graph=graph,
        run_manager=RunManager(
            store=journal,
            rollback_handler=rollback_handler_for_graph(graph, checkpointer),
            lifecycle_publisher=_lifecycle_publisher_for_bridge(journal, stream_bridge),
        ),
        stream_bridge=stream_bridge,
        middleware=MiddlewareStack(tuple(middleware)),
        event_store=journal,
        subagent_executor=effective_subagent_executor,
        tool_registry=effective_tool_registry,
    )


def _lifecycle_publisher_for_bridge(
    journal: RunJournal,
    stream_bridge: InMemoryStreamBridge | JournaledStreamBridge,
):
    async def publish(record: Any, event: str, data: dict[str, Any]) -> None:
        sequence = await journal.count_events(record.run_id) + 1
        await stream_bridge.publish(
            record.run_id,
            event,
            canonical_event_payload(
                run_id=record.run_id,
                thread_id=record.thread_id,
                turn_id=record.run_id,
                sequence=sequence,
                source_node="harness",
                **data,
            ),
        )

    return publish


def _subagent_executor_for_config(
    *,
    config: HarnessConfig,
    settings: Any,
    model_provider: Any | None,
    subagent_executor: SubagentExecutor | None,
) -> SubagentExecutor | None:
    if subagent_executor is not None:
        return subagent_executor
    if not (config.subagents.enabled or config.features.subagents):
        return None
    return SubagentExecutor(
        AgentTeamSubagentRunner(settings=settings, model_factory=model_provider),
        max_parallel=config.subagents.max_concurrent_subagents,
    )


def _tool_registry_with_subagent_task(
    *,
    tool_registry: Any | None,
    config: HarnessConfig,
    subagent_executor: SubagentExecutor | None,
) -> Any | None:
    if subagent_executor is None:
        return tool_registry
    if tool_registry is None:
        return None
    if "task" in getattr(tool_registry, "by_name", {}):
        return tool_registry

    task_tool = create_subagent_task_tool(
        subagent_executor,
        max_parallel=config.subagents.max_concurrent_subagents,
    )
    manifests = tuple(getattr(tool_registry, "manifests", ()) or ())
    return ToolRegistry(
        tools=(*tuple(getattr(tool_registry, "tools", ()) or ()), task_tool),
        manifests=(
            *manifests,
            ToolManifest.from_tool(task_tool, provider_id="harness_subagents"),
        ),
    )
