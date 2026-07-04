from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from ...capabilities import ToolRegistry
from ...capabilities.tool_manifest import ToolManifest
from ...engine.graph.tool_execution import HarnessToolServices
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

logger = logging.getLogger(__name__)


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
    # Newly-integrated components (populated by ``create_focus_agent``)
    agent_definition_registry: Any | None = None  # AgentDefinitionRegistry
    extension_registry: Any | None = None  # ExtensionRegistry
    extension_loader: Any | None = None  # ExtensionLoader
    permission_manager: Any | None = None  # PermissionManager
    system_agent_runner: Any | None = None  # SystemAgentRunner

    def invoke(self, payload: Any, **kwargs: Any) -> Any:
        """Invoke the graph through the harness middleware stack."""

        return self.middleware.invoke(self.graph.invoke, payload, **kwargs)

    def make_event_publisher(self, run_id: str, thread_id: str) -> Any:
        """Create an :class:`AgentEventPublisher` bound to this harness's bridge."""

        from ..streaming import AgentEventPublisher

        return AgentEventPublisher.for_harness(self, run_id=run_id, thread_id=thread_id)

    def facade(self) -> Any:
        """Return a :class:`FocusAgent` streaming facade wrapping this harness."""

        from .facade import FocusAgent

        return FocusAgent(self)

    @property
    def focus_agent(self) -> Any:
        """Return a :class:`FocusAgent` facade bound to this harness.

        The facade is imported lazily to avoid circular imports at module load
        time; each call returns a fresh lightweight wrapper.
        """

        from .facade import FocusAgent

        return FocusAgent(self)

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

    # Build middleware stack BEFORE the graph so we can pass the same
    # MiddlewareStack instance to the graph nodes (for on_turn_start/end).
    middleware_list: list[Any] = list(config.middleware)
    features = config.features
    if features.loop_detection:
        middleware_list.append(LoopDetectionMiddleware())
    middleware_list.append(DanglingToolCallMiddleware())
    middleware_list.append(
        LLMErrorHandlingMiddleware(
            retry=config.retry,
            circuit_breaker=config.circuit_breaker,
        )
    )
    middleware_stack = MiddlewareStack(tuple(middleware_list))

    # Create a mutable services holder that the graph will close over. We
    # populate permission_manager / extension_registry after the graph is
    # built; the graph node closures read from the holder at call time so
    # late binding works.
    run_id = str(uuid.uuid4())
    harness_services = HarnessToolServices(
        run_id=run_id,
        active_agent_name="focus_agent",
        middleware_stack=middleware_stack,
        permission_manager=None,
        extension_registry=None,
    )

    journal = event_store if event_store is not None else InMemoryRunJournal()
    stream_bridge = JournaledStreamBridge(
        journal=journal,
        bridge=InMemoryStreamBridge(max_buffer_size=config.streaming.event_buffer_size),
    )

    # Build the run_manager first so we can pass it to the graph.
    # Note: rollback_handler needs the graph, so we attach it AFTER build_graph.
    run_manager = RunManager(
        store=journal,
        rollback_handler=None,  # set below once graph exists
        lifecycle_publisher=_lifecycle_publisher_for_bridge(journal, stream_bridge),
    )

    # Build optional components up front so they can be wired into the graph.
    new_components = _build_new_components(config=config)
    agent_definition_registry = new_components.get("agent_definition_registry")
    system_agent_runner = new_components.get("system_agent_runner")

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
        harness_services=harness_services,
        run_manager=run_manager,
        system_agent_runner=system_agent_runner,
        agent_definition_registry=agent_definition_registry,
    )

    # Now that graph exists, attach rollback handler.
    run_manager._rollback_handler = rollback_handler_for_graph(graph, checkpointer)

    # Late-bind post-init components to the services holder the graph uses.
    harness_services.permission_manager = new_components.get("permission_manager")
    harness_services.extension_registry = new_components.get("extension_registry")

    harness = FocusAgentHarness(
        config=config,
        graph=graph,
        run_manager=run_manager,
        stream_bridge=stream_bridge,
        middleware=middleware_stack,
        event_store=journal,
        subagent_executor=effective_subagent_executor,
        tool_registry=effective_tool_registry,
        agent_definition_registry=agent_definition_registry,
        extension_registry=new_components.get("extension_registry"),
        extension_loader=new_components.get("extension_loader"),
        permission_manager=new_components.get("permission_manager"),
        system_agent_runner=system_agent_runner,
    )
    return harness


def _build_new_components(config: HarnessConfig) -> dict[str, Any]:
    """Construct optional components before the graph.

    Returns a dict of successfully-constructed components; missing entries
    mean the component was disabled or unavailable. Failures are logged
    and swallowed so existing code paths keep working.
    """

    components: dict[str, Any] = {}
    extension_dirs = list(getattr(config, "extension_dirs", []) or [])
    agent_definition_dirs = list(getattr(config, "agent_definition_dirs", []) or [])
    enable_extensions = bool(getattr(config, "enable_extensions", True))
    enable_permission_system = bool(getattr(config, "enable_permission_system", True))
    doom_loop_threshold = int(getattr(config, "doom_loop_threshold", 3) or 3)
    enable_system_agents = bool(getattr(config, "enable_system_agents", True))

    # a) Agent definition registry with built-in personas.
    try:
        from .definition import create_default_registry

        reg: Any = create_default_registry()
        load_dir = getattr(reg, "load_directory", None)
        if load_dir is not None:
            for directory in agent_definition_dirs:
                try:
                    load_dir(directory)
                except Exception:  # noqa: BLE001
                    logger.debug(
                        "Failed to load agent definitions from %s",
                        directory,
                        exc_info=True,
                    )
        components["agent_definition_registry"] = reg
    except Exception:  # noqa: BLE001
        logger.debug("Agent definition registry unavailable", exc_info=True)

    # b) Extension registry + loader.
    if enable_extensions:
        try:
            from ..extensions import ExtensionRegistry
            from ..extensions.loader import ExtensionLoader

            ext_registry: Any = ExtensionRegistry()
            loader: Any = ExtensionLoader(extension_dirs=extension_dirs)
            try:
                for ext in loader.discover():
                    try:
                        ext_registry.register(ext)
                    except Exception:  # noqa: BLE001
                        logger.debug(
                            "Failed to register extension %r",
                            getattr(ext, "name", "?"),
                            exc_info=True,
                        )
            except Exception:  # noqa: BLE001
                logger.debug("Extension discovery failed", exc_info=True)
            components["extension_registry"] = ext_registry
            components["extension_loader"] = loader
        except Exception:  # noqa: BLE001
            logger.debug("Extension subsystem unavailable", exc_info=True)

    # c) Permission manager — default to an allow-all rule for development.
    if enable_permission_system:
        try:
            from ..governance.permissions import (
                PermissionAction,
                PermissionManager,
                PermissionRule,
            )

            default_rules = [
                PermissionRule(
                    action=PermissionAction.ALLOW,
                    tool_pattern="*",
                    agent_pattern="*",
                    priority=100,
                    reason="dev default: allow all",
                ),
            ]
            components["permission_manager"] = PermissionManager(
                rules=default_rules,
                doom_loop_threshold=doom_loop_threshold,
            )
        except Exception:  # noqa: BLE001
            logger.debug("Permission manager unavailable", exc_info=True)

    # d) System agent runner.
    if enable_system_agents:
        try:
            from .system_agents import SystemAgentRunner, create_default_system_agent_registry

            system_registry: Any = create_default_system_agent_registry()
            components["system_agent_runner"] = SystemAgentRunner(system_registry)
        except Exception:  # noqa: BLE001
            logger.debug("System agent runner unavailable", exc_info=True)

    # NOTE: AgentEventPublisher is intentionally NOT constructed here.
    # It requires (run_id, thread_id) which are per-run, not per-harness.
    # Use FocusAgentHarness.make_event_publisher(run_id, thread_id) instead.

    return components


# Backwards-compatible alias used (if anywhere) for the previous post-hoc init.
def _initialize_new_components(harness: FocusAgentHarness, *, config: HarnessConfig) -> None:
    """No-op shim retained for backwards compatibility.

    Components are now constructed in :func:`_build_new_components` *before*
    the graph is built, so that the graph can wire in references to
    ``run_manager``, ``system_agent_runner``, and ``agent_definition_registry``.
    """
    pass


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
    # Select the runner based on config. Process isolation is opt-in
    # (defaults to False) so existing deployments keep in-process behavior.
    if getattr(config.subagents, "use_process_isolation", False):
        from ..subagents.process_runner import ProcessSubagentTaskRunner

        runner: Any = ProcessSubagentTaskRunner(
            cli_entry_point=getattr(config.subagents, "cli_entry_point", None),
            default_timeout_seconds=getattr(config.subagents, "process_timeout_seconds", 300),
            graceful_shutdown_seconds=getattr(config.subagents, "graceful_shutdown_seconds", 10),
        )
    else:
        runner = AgentTeamSubagentRunner(settings=settings, model_factory=model_provider)
    return SubagentExecutor(
        runner,
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
