from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass

from ..branch_decision import BranchDecisionService
from ..capabilities import ToolRegistry, build_tool_registry
from ..config import Settings, ensure_runtime_directories
from ..core.repo_call import has_repo_method
from ..core.request_context import RequestContext
from ..engine.local_persistence import (
    PersistentInMemorySaver as PersistentInMemorySaver,
)
from ..engine.local_persistence import (
    PersistentInMemoryStore as PersistentInMemoryStore,
)
from ..engine.local_persistence import (
    PersistentSQLiteSaver as PersistentSQLiteSaver,
)
from ..memory import MemoryExtractor, MemoryPolicy, MemoryRetriever, MemoryWriter
from ..memory.embedding import (
    MemoryEmbeddingError,
    MemoryEmbeddingService,
    create_memory_embedding_provider,
)
from ..multi_agent.maintenance import MultiAgentMaintenanceWorker
from ..observability.otel_runtime import OTelRuntime, initialize_otel_runtime
from ..repositories.agent_team_repository import AgentTeamRepository, InMemoryAgentTeamRepository
from ..repositories.branch_repository import BranchRepository
from ..repositories.in_memory_branch_repository import (
    InMemoryBranchRepository as InMemoryBranchRepository,
)
from ..repositories.productivity_repository import (
    InMemoryProductivityRepository as InMemoryProductivityRepository,
)
from ..repositories.productivity_repository import (
    ProductivityRepository,
)
from ..repositories.user_repository import (
    InMemoryUserRepository as InMemoryUserRepository,
)
from ..repositories.user_repository import (
    UserRepository,
)
from ..retrieval.factory import create_retrieval_index
from ..services.agent_team import AgentTeamService
from ..services.background_work import (
    BackgroundJobHandlerRegistry,
    BoundedBackgroundQueue,
    DurableBackgroundWorker,
    register_default_background_job_handlers,
)
from ..services.branches import BranchService
from ..services.coordination import CoordinationBackend, create_coordination_backend
from ..services.productivity import ProductivityService
from ..services.users import UserService
from ..skills import SkillRegistry
from ..storage.namespaces import conversation_namespace_for_context
from ..storage.postgres import PostgresConnectionProvider
from .runtime_persistence import (
    _create_local_checkpointer as _create_local_checkpointer,
)
from .runtime_persistence import (
    _create_local_fallback_persistence,
    _create_postgres_primary_persistence,
)
from .runtime_persistence import (
    _create_repository_with_provider as _create_repository_with_provider,
)
from .runtime_persistence import (
    _postgres_run_journal_cls as _postgres_run_journal_cls,
)
from .runtime_persistence import (
    _sqlite_run_journal_cls as _sqlite_run_journal_cls,
)
from .runtime_types import (
    RuntimeMemoryComponents,
    RuntimeMemoryEmbeddingSetup,
    RuntimePersistence,
    RuntimeRegistries,
    RuntimeServices,
)

logger = logging.getLogger("focus_agent.runtime")

PostgresRunJournal: object | None = None
SQLiteRunJournal: object | None = None


def create_focus_agent(*args: object, **kwargs: object) -> object:
    from ..harness.agents.factory import create_focus_agent as factory

    return factory(*args, **kwargs)


def build_graph(*args: object, **kwargs: object) -> object:
    from .graph_builder import build_graph as graph_builder

    return graph_builder(*args, **kwargs)


@dataclass(slots=True)
class AppRuntime:
    settings: Settings
    harness: object
    graph: object
    run_manager: object
    stream_bridge: object
    event_store: object
    repo: BranchRepository
    user_repository: UserRepository
    branch_service: BranchService
    agent_team_service: AgentTeamService
    branch_decision_service: BranchDecisionService
    user_service: UserService
    productivity_service: ProductivityService
    checkpointer: object
    store: object
    store_namespace_selector: Callable[[RequestContext], tuple[str, ...]]
    memory_policy: MemoryPolicy
    memory_retriever: MemoryRetriever
    memory_writer: MemoryWriter
    memory_extractor: MemoryExtractor
    memory_repository: object | None
    productivity_repository: ProductivityRepository
    governance_repository: object
    memory_embedding_service: MemoryEmbeddingService | None
    memory_embedding_provider: object | None
    memory_embedding_backend_error: str | None
    retrieval_index: object | None
    retrieval_index_error: str | None
    skill_registry: SkillRegistry
    tool_registry: ToolRegistry
    trajectory_recorder: object | None
    artifact_metadata_repository: object | None
    otel_runtime: OTelRuntime
    background_work: BoundedBackgroundQueue
    durable_background_worker: DurableBackgroundWorker | None
    multi_agent_maintenance_worker: MultiAgentMaintenanceWorker | None
    coordination_backend: CoordinationBackend
    postgres_connection_provider: PostgresConnectionProvider | None
    _exit_stack: ExitStack

    def close(self) -> None:
        self._exit_stack.close()

    def conversation_store_namespace(self, context: RequestContext) -> tuple[str, ...]:
        return conversation_namespace_for_context(context)

    def start_durable_background_worker(
        self, chat_service: object
    ) -> DurableBackgroundWorker | None:
        if (
            str(getattr(self.settings, "background_job_execution", "best_effort")).strip().lower()
            != "durable"
        ):
            return None
        if self.durable_background_worker is not None:
            return self.durable_background_worker
        if (
            not self.settings.database_uri
            or str(self.settings.background_job_backend).lower() != "postgres"
        ):
            raise RuntimeError(
                "BACKGROUND_JOB_EXECUTION=durable requires DATABASE_URI and "
                "BACKGROUND_JOB_BACKEND=postgres."
            )
        registry = BackgroundJobHandlerRegistry()
        register_default_background_job_handlers(
            registry,
            chat_service=chat_service,
            branch_service=self.branch_service,
            agent_team_service=self.agent_team_service,
            branch_decision_service=self.branch_decision_service,
            memory_embedding_service=self.memory_embedding_service,
            memory_repository=self.memory_repository,
        )
        worker = DurableBackgroundWorker(
            name="runtime",
            job_backend=self.coordination_backend.job_deduper,
            handlers=registry,
            claim_ttl_seconds=self.settings.background_job_claim_ttl_seconds,
        )
        worker.start()
        self.durable_background_worker = worker
        self._exit_stack.callback(worker.close)
        return worker


def create_runtime(settings: Settings | None = None) -> AppRuntime:
    settings = settings or Settings.from_env()
    if str(
        getattr(settings, "background_job_execution", "best_effort")
    ).strip().lower() == "durable" and (
        not settings.database_uri or str(settings.background_job_backend).lower() != "postgres"
    ):
        raise ValueError(
            "BACKGROUND_JOB_EXECUTION=durable requires DATABASE_URI and BACKGROUND_JOB_BACKEND=postgres."
        )
    ensure_runtime_directories(settings)
    exit_stack = ExitStack()
    otel_runtime = initialize_otel_runtime(settings)
    exit_stack.callback(otel_runtime.shutdown)
    postgres_connection_provider = _create_postgres_connection_provider(settings)
    if postgres_connection_provider is not None:
        exit_stack.callback(postgres_connection_provider.close)
    coordination_backend = create_coordination_backend(
        database_uri=settings.database_uri,
        background_job_backend=settings.background_job_backend,
        background_job_claim_ttl_seconds=settings.background_job_claim_ttl_seconds,
        background_job_retry_base_delay_seconds=settings.background_job_retry_base_delay_seconds,
        background_job_retry_max_delay_seconds=settings.background_job_retry_max_delay_seconds,
        multi_agent_enabled=settings.multi_agent_v2_enabled,
        multi_agent_message_ttl_seconds=settings.multi_agent_message_ttl_seconds,
    )
    background_work = BoundedBackgroundQueue(
        name="runtime",
        max_concurrency=settings.background_worker_max_concurrency,
        max_size=settings.background_queue_max_size,
        job_deduper=coordination_backend.job_deduper,
    )
    exit_stack.callback(background_work.close)
    multi_agent_maintenance_worker = _start_multi_agent_maintenance_worker(
        settings=settings,
        coordination_backend=coordination_backend,
        exit_stack=exit_stack,
    )

    memory_embedding_setup = _resolve_memory_embedding_setup(settings)
    persistence = _create_runtime_persistence(
        settings=settings,
        exit_stack=exit_stack,
        memory_embedding_setup=memory_embedding_setup,
        postgres_connection_provider=postgres_connection_provider,
    )
    memory = _create_memory_components(
        settings=settings,
        store=persistence.store,
        memory_repository=persistence.memory_repository,
        memory_embedding_setup=memory_embedding_setup,
        coordination_backend=coordination_backend,
    )
    registries = _create_runtime_registries(
        settings=settings,
        persistence=persistence,
        memory=memory,
    )
    harness = _create_runtime_harness(
        settings=settings,
        persistence=persistence,
        memory=memory,
        registries=registries,
        coordination_backend=coordination_backend,
    )
    graph = harness.graph
    governance_repository = _create_governance_repository(settings)
    services = _create_runtime_services(
        settings=settings,
        graph=graph,
        repo=persistence.repo,
        user_repository=persistence.user_repository,
        store=persistence.store,
        memory_writer=memory.memory_writer,
        memory_repository=persistence.memory_repository,
        productivity_repository=persistence.productivity_repository,
        governance_repository=governance_repository,
        memory_embedding_provider=memory.memory_embedding_provider,
        retrieval_index=memory.retrieval_index,
        coordination_backend=coordination_backend,
        background_work=background_work,
    )

    return AppRuntime(
        settings=settings,
        harness=harness,
        graph=graph,
        run_manager=harness.run_manager,
        stream_bridge=harness.stream_bridge,
        event_store=harness.event_store,
        repo=persistence.repo,
        user_repository=persistence.user_repository,
        branch_service=services.branch_service,
        agent_team_service=services.agent_team_service,
        branch_decision_service=services.branch_decision_service,
        user_service=services.user_service,
        productivity_service=services.productivity_service,
        checkpointer=persistence.checkpointer,
        store=persistence.store,
        store_namespace_selector=conversation_namespace_for_context,
        memory_policy=memory.memory_policy,
        memory_retriever=memory.memory_retriever,
        memory_writer=memory.memory_writer,
        memory_extractor=memory.memory_extractor,
        memory_repository=memory.memory_repository,
        productivity_repository=persistence.productivity_repository,
        governance_repository=governance_repository,
        memory_embedding_service=memory.memory_embedding_service,
        memory_embedding_provider=memory.memory_embedding_provider,
        memory_embedding_backend_error=memory.memory_embedding_backend_error,
        retrieval_index=memory.retrieval_index,
        retrieval_index_error=memory.retrieval_index_error,
        skill_registry=registries.skill_registry,
        tool_registry=registries.tool_registry,
        trajectory_recorder=persistence.trajectory_recorder,
        artifact_metadata_repository=persistence.artifact_metadata_repository,
        otel_runtime=otel_runtime,
        background_work=background_work,
        durable_background_worker=None,
        multi_agent_maintenance_worker=multi_agent_maintenance_worker,
        coordination_backend=coordination_backend,
        postgres_connection_provider=persistence.postgres_connection_provider,
        _exit_stack=exit_stack,
    )


def _start_multi_agent_maintenance_worker(
    *,
    settings: Settings,
    coordination_backend: CoordinationBackend,
    exit_stack: ExitStack,
) -> MultiAgentMaintenanceWorker | None:
    if not bool(getattr(settings, "multi_agent_v2_enabled", False)):
        return None
    worker = MultiAgentMaintenanceWorker(coordination_backend)
    worker.start()
    exit_stack.callback(worker.close)
    return worker


def _create_runtime_persistence(
    *,
    settings: Settings,
    exit_stack: ExitStack,
    memory_embedding_setup: RuntimeMemoryEmbeddingSetup,
    postgres_connection_provider: PostgresConnectionProvider | None,
) -> RuntimePersistence:
    if settings.database_uri:
        logger.info("Runtime persistence backend selected: postgres-primary")
        (
            checkpointer,
            store,
            repo,
            user_repository,
            memory_repository,
            productivity_repository,
            trajectory_recorder,
            artifact_metadata_repository,
            run_journal,
        ) = _create_postgres_primary_persistence(
            settings=settings,
            exit_stack=exit_stack,
            memory_embedding_setup=memory_embedding_setup,
            postgres_connection_provider=postgres_connection_provider,
        )
    else:
        logger.info("Runtime persistence backend selected: local-fallback")
        (
            checkpointer,
            store,
            repo,
            user_repository,
            memory_repository,
            productivity_repository,
            trajectory_recorder,
            artifact_metadata_repository,
            run_journal,
        ) = _create_local_fallback_persistence(settings)

    return RuntimePersistence(
        checkpointer=checkpointer,
        store=store,
        repo=repo,
        user_repository=user_repository,
        memory_repository=memory_repository,
        productivity_repository=productivity_repository,
        trajectory_recorder=trajectory_recorder,
        artifact_metadata_repository=artifact_metadata_repository,
        run_journal=run_journal,
        postgres_connection_provider=postgres_connection_provider,
        pool=postgres_connection_provider,
    )


def _create_postgres_connection_provider(settings: Settings) -> PostgresConnectionProvider | None:
    if not settings.database_uri:
        return None
    return PostgresConnectionProvider(
        settings.database_uri,
        pool_enabled=bool(getattr(settings, "db_pool_enabled", True))
        and bool(getattr(settings, "postgres_pool_enabled", True)),
        min_size=int(getattr(settings, "postgres_pool_min_size", 2) or 2),
        max_size=int(getattr(settings, "db_pool_max", 20) or 20),
        slow_query_threshold_ms=float(
            getattr(settings, "postgres_slow_query_threshold_ms", 500.0) or 500.0
        ),
    )


def _create_governance_repository(settings: Settings) -> object:
    if settings.database_uri:
        from ..repositories.postgres_governance_repository import PostgresGovernanceRepository

        return PostgresGovernanceRepository(settings.database_uri)
    from ..repositories.governance_repository import InMemoryGovernanceRepository

    return InMemoryGovernanceRepository()


def _create_memory_components(
    *,
    settings: Settings,
    store: object,
    memory_repository: object | None = None,
    memory_embedding_setup: RuntimeMemoryEmbeddingSetup | None = None,
    coordination_backend: CoordinationBackend | None = None,
) -> RuntimeMemoryComponents:
    memory_policy = MemoryPolicy()
    setup = memory_embedding_setup or _resolve_memory_embedding_setup(settings)
    retrieval_index, retrieval_index_error = create_retrieval_index(
        settings,
        dimensions=setup.dimensions,
    )
    memory_embedding_service, memory_embedding_backend_error = _create_memory_embedding_service(
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
    memory_retriever = MemoryRetriever(
        store=store,
        repository=memory_repository,
        policy=memory_policy,
        retrieval_mode="hybrid" if vector_search_mode == "hybrid" else "fts",
        vector_shadow=vector_search_mode == "shadow",
        embedding_provider=memory_embedding_provider,
        retrieval_index=retrieval_index,
    )
    memory_writer = MemoryWriter(
        store=store,
        repository=memory_repository,
        policy=memory_policy,
        embedding_service=memory_embedding_service,
        retrieval_index=retrieval_index,
        coordination_backend=coordination_backend,
    )
    memory_extractor = MemoryExtractor(mode=settings.agent_memory_extractor_mode)
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


def _create_memory_embedding_service(
    settings: Settings,
    *,
    memory_repository: object | None,
    memory_embedding_setup: RuntimeMemoryEmbeddingSetup | None = None,
    retrieval_index: object | None = None,
) -> tuple[MemoryEmbeddingService | None, str | None]:
    setup = memory_embedding_setup or _resolve_memory_embedding_setup(settings)
    if setup.backend_error is not None:
        return None, setup.backend_error
    provider = setup.provider
    if provider is None:
        return None, None
    if memory_repository is None:
        return None, "local_fallback"
    service = MemoryEmbeddingService(
        repository=memory_repository,
        provider=provider,
        retrieval_index=retrieval_index,
        batch_size=getattr(settings, "agent_memory_embedding_batch_size", 32),
    )
    return service, None


def _create_runtime_registries(
    *,
    settings: Settings,
    persistence: RuntimePersistence,
    memory: RuntimeMemoryComponents,
) -> RuntimeRegistries:
    skill_registry_kwargs = {"settings": settings}
    skill_registry_signature = inspect.signature(SkillRegistry.from_settings)
    if "retrieval_index" in skill_registry_signature.parameters:
        skill_registry_kwargs["retrieval_index"] = memory.retrieval_index
    if "embedding_provider" in skill_registry_signature.parameters:
        skill_registry_kwargs["embedding_provider"] = memory.memory_embedding_provider
    skill_registry = SkillRegistry.from_settings(**skill_registry_kwargs)
    tool_registry = _build_tool_registry_compat(
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


def _create_runtime_graph(
    *,
    settings: Settings,
    persistence: RuntimePersistence,
    memory: RuntimeMemoryComponents,
    registries: RuntimeRegistries,
) -> object:
    return build_graph(
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


def _create_runtime_harness(
    *,
    settings: Settings,
    persistence: RuntimePersistence,
    memory: RuntimeMemoryComponents,
    registries: RuntimeRegistries,
    coordination_backend: CoordinationBackend,
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
    return create_focus_agent(
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


def _create_runtime_services(
    *,
    settings: Settings,
    graph: object,
    repo: BranchRepository,
    user_repository: UserRepository,
    store: object,
    memory_writer: MemoryWriter,
    memory_repository: object | None,
    productivity_repository: ProductivityRepository,
    governance_repository: object,
    memory_embedding_provider: object | None,
    retrieval_index: object | None,
    coordination_backend: CoordinationBackend,
    background_work: BoundedBackgroundQueue,
) -> RuntimeServices:
    branch_service = BranchService(
        settings=settings,
        graph=graph,
        repo=repo,
        store=store,
        memory_writer=memory_writer,
    )
    branch_service._coordination_backend = coordination_backend
    agent_team_service = AgentTeamService(
        branch_service=branch_service,
        repository=_create_agent_team_repository(settings),
        settings=settings,
        coordination_backend=coordination_backend,
        background_work=background_work,
        retrieval_index=retrieval_index,
        memory_embedding_provider=memory_embedding_provider,
    )
    user_service = UserService(
        user_repository,
        auth_enabled=settings.auth_enabled,
    )
    branch_decision_service = BranchDecisionService(
        settings=settings,
        graph=graph,
        governance_repository=governance_repository,
        branch_service=branch_service,
        coordination_backend=coordination_backend,
        retrieval_index=retrieval_index,
        memory_embedding_provider=memory_embedding_provider,
    )
    productivity_service = ProductivityService(productivity_repository)
    return RuntimeServices(
        branch_service=branch_service,
        agent_team_service=agent_team_service,
        branch_decision_service=branch_decision_service,
        user_service=user_service,
        productivity_service=productivity_service,
    )


@contextmanager
def _langgraph_postgres_pool(*, settings: Settings, name: str) -> Iterator[object]:
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    assert settings.database_uri is not None
    min_size = max(0, int(getattr(settings, "postgres_pool_min_size", 2) or 2))
    max_size = max(1, int(getattr(settings, "db_pool_max", 20) or 20))
    if min_size > max_size:
        min_size = max_size
    with ConnectionPool(
        settings.database_uri,
        min_size=min_size,
        max_size=max_size,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        name=name,
        open=True,
    ) as pool:
        yield pool



def _create_agent_team_repository(settings: Settings) -> AgentTeamRepository:
    if settings.database_uri:
        from ..repositories.postgres_agent_team_repository import PostgresAgentTeamRepository

        repository = PostgresAgentTeamRepository(settings.database_uri)
    else:
        repository = InMemoryAgentTeamRepository()
    _setup_component_if_available(repository)
    return repository


def _setup_component_if_available(component: object) -> None:
    if has_repo_method(component, "setup"):
        component.setup()


def _resolve_memory_embedding_setup(settings: Settings) -> RuntimeMemoryEmbeddingSetup:
    provider: object | None = None
    backend_error: str | None = None
    try:
        provider = create_memory_embedding_provider(settings)
    except MemoryEmbeddingError as exc:
        backend_error = str(exc)
        logger.warning("Memory embedding backend unavailable: %s", exc)
    dimensions = _memory_embedding_schema_dimensions(settings, provider=provider)
    try:
        settings.agent_memory_embedding_dimensions = dimensions
    except Exception:  # pragma: no cover - Settings is mutable in production.
        pass
    return RuntimeMemoryEmbeddingSetup(
        provider=provider,
        backend_error=backend_error,
        dimensions=dimensions,
        memory_embeddings_enabled=_memory_embedding_configured(settings),
    )


def _memory_embedding_schema_dimensions(settings: Settings, *, provider: object | None) -> int:
    provider_dimensions = getattr(provider, "dimensions", None)
    if provider_dimensions:
        return max(1, int(provider_dimensions))
    configured = int(getattr(settings, "agent_memory_embedding_dimensions", 1536) or 1536)
    if configured > 0:
        return configured
    model_id = str(getattr(settings, "agent_memory_embedding_model", "") or "").strip().lower()
    backend = str(getattr(settings, "agent_memory_embedding_backend", "") or "").strip().lower()
    provider_id = (
        str(getattr(settings, "agent_memory_embedding_provider", "") or "").strip().lower()
    )
    if (
        model_id in {"embeddinggemma", "embedding-gemma"}
        or backend == "ollama"
        or provider_id == "ollama"
    ):
        return 768
    return 1536


def _setup_memory_repository_if_available(
    component: object,
    *,
    settings: Settings,
    memory_embedding_setup: RuntimeMemoryEmbeddingSetup,
) -> None:
    if not has_repo_method(component, "setup"):
        return
    signature = inspect.signature(component.setup)
    if not signature.parameters:
        component.setup()
        return
    component.setup(
        dimensions=memory_embedding_setup.dimensions,
        vector_index=getattr(settings, "agent_memory_vector_index_enabled", False),
        memory_embeddings_enabled=memory_embedding_setup.memory_embeddings_enabled,
        pgvector_extension_mode=getattr(
            settings,
            "agent_memory_pgvector_extension_mode",
            "auto_create",
        ),
    )


def _memory_embedding_configured(settings: Settings) -> bool:
    backend = str(getattr(settings, "agent_memory_embedding_backend", "") or "").strip().lower()
    if backend and backend not in {"disabled", "none", "off"}:
        return True
    if bool(getattr(settings, "agent_memory_embedding_enabled", False)):
        return True
    return (
        str(getattr(settings, "agent_memory_vector_search_mode", "off")).strip().lower() == "hybrid"
    )


def _build_tool_registry_compat(
    *,
    settings: Settings,
    skill_registry: SkillRegistry,
    store: object,
    checkpointer: object,
    artifact_metadata_repository: object | None,
    memory_repository: object | None = None,
    memory_embedding_service: object | None = None,
    retrieval_index: object | None = None,
    productivity_repository: object | None = None,
) -> ToolRegistry:
    kwargs = {
        "settings": settings,
        "skill_registry": skill_registry,
        "store": store,
        "checkpointer": checkpointer,
    }
    if "artifact_metadata_repository" in inspect.signature(build_tool_registry).parameters:
        kwargs["artifact_metadata_repository"] = artifact_metadata_repository
    if "memory_repository" in inspect.signature(build_tool_registry).parameters:
        kwargs["memory_repository"] = memory_repository
    if "memory_embedding_service" in inspect.signature(build_tool_registry).parameters:
        kwargs["memory_embedding_service"] = memory_embedding_service
    if "retrieval_index" in inspect.signature(build_tool_registry).parameters:
        kwargs["retrieval_index"] = retrieval_index
    if "productivity_repository" in inspect.signature(build_tool_registry).parameters:
        kwargs["productivity_repository"] = productivity_repository
    return build_tool_registry(**kwargs)


def _trajectory_enabled(settings: Settings) -> bool:
    if settings.trajectory_enabled is None:
        return bool(settings.database_uri)
    return bool(settings.trajectory_enabled and settings.database_uri)
