from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from ..config import Settings
from .runtime_types import (
    RuntimeMemoryComponents,
    RuntimeMemoryEmbeddingSetup,
    RuntimePersistence,
    RuntimeRegistries,
    RuntimeServices,
)


def create_memory_components(
    *,
    settings: Settings,
    store: object,
    memory_repository: object | None,
    memory_embedding_setup: RuntimeMemoryEmbeddingSetup | None,
    coordination_backend: object | None,
    memory_policy_factory: Callable[[], Any],
    memory_retriever_factory: Callable[..., Any],
    memory_writer_factory: Callable[..., Any],
    memory_extractor_factory: Callable[..., Any],
    retrieval_index_factory: Callable[..., tuple[object | None, str | None]],
    memory_embedding_service_factory: Callable[..., tuple[object | None, str | None]],
    memory_embedding_setup_resolver: Callable[[Settings], RuntimeMemoryEmbeddingSetup],
) -> RuntimeMemoryComponents:
    memory_policy = memory_policy_factory()
    setup = memory_embedding_setup or memory_embedding_setup_resolver(settings)
    retrieval_index, retrieval_index_error = retrieval_index_factory(
        settings,
        dimensions=setup.dimensions,
    )
    memory_embedding_service, memory_embedding_backend_error = memory_embedding_service_factory(
        settings,
        memory_repository=memory_repository,
        memory_embedding_setup=setup,
        retrieval_index=retrieval_index,
    )
    memory_embedding_provider = (
        memory_embedding_service.provider if memory_embedding_service is not None else None
    )
    vector_search_mode = (
        str(getattr(settings, "agent_memory_vector_search_mode", "shadow")).strip().lower()
    )
    memory_retriever = memory_retriever_factory(
        store=store,
        repository=memory_repository,
        policy=memory_policy,
        retrieval_mode="hybrid" if vector_search_mode == "hybrid" else "fts",
        vector_shadow=vector_search_mode == "shadow",
        embedding_provider=memory_embedding_provider,
        retrieval_index=retrieval_index,
    )
    memory_writer = memory_writer_factory(
        store=store,
        repository=memory_repository,
        policy=memory_policy,
        embedding_service=memory_embedding_service,
        retrieval_index=retrieval_index,
        coordination_backend=coordination_backend,
    )
    memory_extractor = memory_extractor_factory(mode=settings.agent_memory_extractor_mode)
    return RuntimeMemoryComponents(
        memory_policy=memory_policy,
        memory_retriever=memory_retriever,
        memory_writer=memory_writer,
        memory_extractor=memory_extractor,
        memory_repository=memory_repository,
        memory_embedding_service=memory_embedding_service,
        memory_embedding_provider=memory_embedding_provider,
        memory_embedding_backend_error=memory_embedding_backend_error,
        retrieval_index=retrieval_index,
        retrieval_index_error=retrieval_index_error,
    )


def create_memory_embedding_service(
    settings: Settings,
    *,
    memory_repository: object | None,
    memory_embedding_setup: RuntimeMemoryEmbeddingSetup | None,
    retrieval_index: object | None,
    memory_embedding_setup_resolver: Callable[[Settings], RuntimeMemoryEmbeddingSetup],
    memory_embedding_service_factory: Callable[..., object],
) -> tuple[object | None, str | None]:
    setup = memory_embedding_setup or memory_embedding_setup_resolver(settings)
    if setup.backend_error is not None:
        return None, setup.backend_error
    provider = setup.provider
    if provider is None:
        return None, None
    if memory_repository is None:
        return None, "local_fallback"
    service = memory_embedding_service_factory(
        repository=memory_repository,
        provider=provider,
        retrieval_index=retrieval_index,
        batch_size=getattr(settings, "agent_memory_embedding_batch_size", 32),
    )
    return service, None


def create_runtime_registries(
    *,
    settings: Settings,
    persistence: RuntimePersistence,
    memory: RuntimeMemoryComponents,
    skill_registry_cls: object,
    tool_registry_compat_builder: Callable[..., object],
) -> RuntimeRegistries:
    skill_registry_kwargs: dict[str, object] = {"settings": settings}
    skill_registry_signature = inspect.signature(skill_registry_cls.from_settings)
    if "retrieval_index" in skill_registry_signature.parameters:
        skill_registry_kwargs["retrieval_index"] = memory.retrieval_index
    if "embedding_provider" in skill_registry_signature.parameters:
        skill_registry_kwargs["embedding_provider"] = memory.memory_embedding_provider
    skill_registry = skill_registry_cls.from_settings(**skill_registry_kwargs)
    tool_registry = tool_registry_compat_builder(
        settings=settings,
        skill_registry=skill_registry,
        store=persistence.store,
        checkpointer=persistence.checkpointer,
        artifact_metadata_repository=persistence.artifact_metadata_repository,
        memory_repository=persistence.memory_repository,
        memory_embedding_service=memory.memory_embedding_service,
        retrieval_index=memory.retrieval_index,
        productivity_repository=persistence.productivity_repository,
    )
    return RuntimeRegistries(skill_registry=skill_registry, tool_registry=tool_registry)


def create_runtime_graph(
    *,
    settings: Settings,
    persistence: RuntimePersistence,
    memory: RuntimeMemoryComponents,
    registries: RuntimeRegistries,
    graph_builder: Callable[..., object],
) -> object:
    return graph_builder(
        settings=settings,
        checkpointer=persistence.checkpointer,
        store=persistence.store,
        memory_retriever=memory.memory_retriever,
        memory_policy=memory.memory_policy,
        memory_writer=memory.memory_writer,
        memory_extractor=memory.memory_extractor,
        skill_registry=registries.skill_registry,
        tool_registry=registries.tool_registry,
    )


def create_runtime_harness(
    *,
    settings: Settings,
    persistence: RuntimePersistence,
    memory: RuntimeMemoryComponents,
    registries: RuntimeRegistries,
    coordination_backend: object,
    focus_agent_factory: Callable[..., object],
) -> object:
    from ..harness.schemas.config import HarnessConfig

    harness_config = HarnessConfig(
        name="focus-agent",
        model=settings.model,
        streaming={"heartbeat_seconds": settings.sse_heartbeat_seconds},
        subagents={
            "enabled": bool(settings.agent_delegation_enabled),
            "max_concurrent_subagents": max(1, int(settings.agent_role_max_parallel_runs or 1)),
        },
    )
    return focus_agent_factory(
        harness_config,
        settings=settings,
        checkpointer=persistence.checkpointer,
        store=persistence.store,
        memory_retriever=memory.memory_retriever,
        memory_policy=memory.memory_policy,
        memory_writer=memory.memory_writer,
        memory_extractor=memory.memory_extractor,
        skill_registry=registries.skill_registry,
        tool_registry=registries.tool_registry,
        approval_queue=coordination_backend.approval_queue,
        event_store=persistence.run_journal,
    )


def create_runtime_services(
    *,
    settings: Settings,
    graph: object,
    repo: object,
    user_repository: object,
    store: object,
    memory_writer: object,
    productivity_repository: object,
    governance_repository: object,
    memory_embedding_provider: object | None,
    retrieval_index: object | None,
    coordination_backend: object,
    background_work: object,
    agent_team_repository: object,
    branch_service_factory: Callable[..., Any],
    agent_team_service_factory: Callable[..., Any],
    user_service_factory: Callable[..., Any],
    branch_decision_service_factory: Callable[..., Any],
    productivity_service_factory: Callable[..., Any],
) -> RuntimeServices:
    branch_service = branch_service_factory(
        settings=settings,
        graph=graph,
        repo=repo,
        store=store,
        memory_writer=memory_writer,
    )
    branch_service._coordination_backend = coordination_backend
    agent_team_service = agent_team_service_factory(
        branch_service=branch_service,
        repository=agent_team_repository,
        settings=settings,
        coordination_backend=coordination_backend,
        background_work=background_work,
        retrieval_index=retrieval_index,
        memory_embedding_provider=memory_embedding_provider,
    )
    user_service = user_service_factory(
        user_repository,
        auth_enabled=settings.auth_enabled,
    )
    branch_decision_service = branch_decision_service_factory(
        settings=settings,
        graph=graph,
        governance_repository=governance_repository,
        branch_service=branch_service,
        coordination_backend=coordination_backend,
        retrieval_index=retrieval_index,
        memory_embedding_provider=memory_embedding_provider,
    )
    productivity_service = productivity_service_factory(productivity_repository)
    return RuntimeServices(
        branch_service=branch_service,
        agent_team_service=agent_team_service,
        branch_decision_service=branch_decision_service,
        user_service=user_service,
        productivity_service=productivity_service,
    )


def start_durable_background_worker(
    *,
    runtime: object,
    chat_service: object,
    handler_registry_factory: Callable[[], object],
    handler_registrar: Callable[..., None],
    durable_worker_factory: Callable[..., object],
) -> object | None:
    settings = runtime.settings
    if (
        str(getattr(settings, "background_job_execution", "best_effort")).strip().lower()
        != "durable"
    ):
        return None
    if runtime.durable_background_worker is not None:
        return runtime.durable_background_worker
    if not settings.database_uri or str(settings.background_job_backend).lower() != "postgres":
        raise RuntimeError(
            "BACKGROUND_JOB_EXECUTION=durable requires DATABASE_URI and "
            "BACKGROUND_JOB_BACKEND=postgres."
        )
    registry = handler_registry_factory()
    handler_registrar(
        registry,
        chat_service=chat_service,
        branch_service=runtime.branch_service,
        agent_team_service=runtime.agent_team_service,
        branch_decision_service=runtime.branch_decision_service,
        memory_embedding_service=runtime.memory_embedding_service,
        memory_repository=runtime.memory_repository,
    )
    worker = durable_worker_factory(
        name="runtime",
        job_backend=runtime.coordination_backend.job_deduper,
        handlers=registry,
        claim_ttl_seconds=settings.background_job_claim_ttl_seconds,
    )
    worker.start()
    runtime.durable_background_worker = worker
    runtime._exit_stack.callback(worker.close)
    return worker


def build_tool_registry_compat(
    *,
    settings: Settings,
    skill_registry: object,
    store: object,
    checkpointer: object,
    artifact_metadata_repository: object | None,
    memory_repository: object | None,
    memory_embedding_service: object | None,
    retrieval_index: object | None,
    productivity_repository: object | None,
    tool_registry_builder: Callable[..., object],
) -> object:
    kwargs: dict[str, object] = {
        "settings": settings,
        "skill_registry": skill_registry,
        "store": store,
        "checkpointer": checkpointer,
    }
    parameters = inspect.signature(tool_registry_builder).parameters
    if "artifact_metadata_repository" in parameters:
        kwargs["artifact_metadata_repository"] = artifact_metadata_repository
    if "memory_repository" in parameters:
        kwargs["memory_repository"] = memory_repository
    if "memory_embedding_service" in parameters:
        kwargs["memory_embedding_service"] = memory_embedding_service
    if "retrieval_index" in parameters:
        kwargs["retrieval_index"] = retrieval_index
    if "productivity_repository" in parameters:
        kwargs["productivity_repository"] = productivity_repository
    return tool_registry_builder(**kwargs)
