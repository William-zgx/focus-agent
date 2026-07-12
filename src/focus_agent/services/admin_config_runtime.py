from __future__ import annotations

import importlib
from typing import Any


def _admin_config_facade() -> Any:
    return importlib.import_module("focus_agent.services.admin_config")


def _reload_runtime_skill_registry(runtime: Any) -> dict[str, Any]:
    facade = _admin_config_facade()
    registry = getattr(runtime, "skill_registry", None)
    if isinstance(registry, facade.SkillRegistry):
        return registry.reload_from_settings(runtime.settings)
    registry = facade.SkillRegistry.from_settings(runtime.settings)
    try:
        runtime.skill_registry = registry
    except Exception:
        pass
    return {
        "success": True,
        "enabled": registry.enabled,
        "previous_count": 0,
        "count": len(registry.all_skills()),
        "sources": registry.list_sources(),
    }


def _refresh_runtime_skill_registry(runtime: Any) -> dict[str, Any]:
    facade = _admin_config_facade()
    registry = getattr(runtime, "skill_registry", None)
    if isinstance(registry, facade.SkillRegistry):
        return registry.refresh_index()
    return facade._reload_runtime_skill_registry(runtime)


def _reload_runtime_tool_registry(runtime: Any) -> dict[str, Any]:
    facade = _admin_config_facade()
    registry = getattr(runtime, "skill_registry", None)
    if not isinstance(registry, facade.SkillRegistry):
        registry = facade.SkillRegistry.from_settings(runtime.settings)
        try:
            runtime.skill_registry = registry
        except Exception:
            pass
    try:
        runtime.tool_registry = facade.build_tool_registry(
            settings=runtime.settings,
            skill_registry=registry,
            store=getattr(runtime, "store", None),
            checkpointer=getattr(runtime, "checkpointer", None),
            artifact_metadata_repository=getattr(
                runtime,
                "artifact_metadata_repository",
                None,
            ),
            artifact_store=getattr(runtime, "artifact_store", None),
            memory_repository=getattr(runtime, "memory_repository", None),
            memory_embedding_service=getattr(runtime, "memory_embedding_service", None),
            productivity_repository=getattr(runtime, "productivity_repository", None),
        )
    except Exception as exc:
        raise facade.AdminConfigError(
            "Failed to rebuild tool registry after skill configuration update."
        ) from exc
    return {
        "success": True,
        "count": len(getattr(runtime.tool_registry, "tools", ()) or ()),
    }


def _reload_runtime_graph(runtime: Any) -> dict[str, Any]:
    if getattr(runtime, "graph", None) is None and getattr(runtime, "harness", None) is None:
        return {"success": True, "rebuilt": False}
    facade = _admin_config_facade()
    harness = getattr(runtime, "harness", None)
    harness_config = getattr(harness, "config", None)
    try:
        if harness_config is not None:
            from focus_agent.harness.agents.factory import create_focus_agent

            rebuilt_harness = create_focus_agent(
                harness_config,
                settings=runtime.settings,
                checkpointer=getattr(runtime, "checkpointer", None),
                store=getattr(runtime, "store", None),
                event_store=getattr(runtime, "event_store", None)
                or getattr(harness, "event_store", None),
                memory_retriever=getattr(runtime, "memory_retriever", None),
                memory_policy=getattr(runtime, "memory_policy", None),
                memory_writer=getattr(runtime, "memory_writer", None),
                memory_extractor=getattr(runtime, "memory_extractor", None),
                skill_registry=getattr(runtime, "skill_registry", None),
                tool_registry=getattr(runtime, "tool_registry", None),
                approval_queue=getattr(
                    getattr(runtime, "coordination_backend", None),
                    "approval_queue",
                    None,
                ),
                subagent_executor=getattr(harness, "subagent_executor", None),
            )
            runtime.harness = rebuilt_harness
            runtime.graph = rebuilt_harness.graph
            runtime.run_manager = rebuilt_harness.run_manager
            runtime.stream_bridge = rebuilt_harness.stream_bridge
            runtime.event_store = rebuilt_harness.event_store
        else:
            from focus_agent.engine.graph_builder import build_graph

            runtime.graph = build_graph(
                settings=runtime.settings,
                checkpointer=getattr(runtime, "checkpointer", None),
                store=getattr(runtime, "store", None),
                memory_retriever=getattr(runtime, "memory_retriever", None),
                memory_policy=getattr(runtime, "memory_policy", None),
                memory_writer=getattr(runtime, "memory_writer", None),
                memory_extractor=getattr(runtime, "memory_extractor", None),
                skill_registry=getattr(runtime, "skill_registry", None),
                tool_registry=getattr(runtime, "tool_registry", None),
                approval_queue=getattr(
                    getattr(runtime, "coordination_backend", None),
                    "approval_queue",
                    None,
                ),
            )
    except Exception as exc:
        raise facade.AdminConfigError(
            "Failed to rebuild graph after skill configuration update."
        ) from exc
    facade._sync_runtime_graph_dependents(runtime)
    return {"success": True, "rebuilt": True}


def _sync_runtime_graph_dependents(runtime: Any) -> None:
    graph = getattr(runtime, "graph", None)
    if graph is None:
        return
    for attr_name in ("branch_service", "branch_decision_service"):
        service = getattr(runtime, attr_name, None)
        if service is not None and hasattr(service, "graph"):
            service.graph = graph
