from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import inspect
import logging
from pathlib import Path
from typing import Callable

from ..capabilities import ToolRegistry, build_tool_registry
from ..config import Settings, ensure_runtime_directories
from ..engine.local_persistence import PersistentInMemorySaver, PersistentInMemoryStore
from ..memory import MemoryExtractor, MemoryPolicy, MemoryRetriever, MemoryWriter
from ..memory.embedding import (
    MemoryEmbeddingError,
    MemoryEmbeddingService,
    create_memory_embedding_provider,
)
from ..observability.otel_runtime import OTelRuntime, initialize_otel_runtime
from ..repositories.agent_team_repository import AgentTeamRepository
from ..repositories.branch_repository import BranchRepository
from ..repositories.sqlite_agent_team_repository import SQLiteAgentTeamRepository
from ..repositories.sqlite_branch_repository import SQLiteBranchRepository
from ..repositories.sqlite_user_repository import SQLiteUserRepository
from ..repositories.user_repository import UserRepository
from ..services.agent_team import AgentTeamService
from ..services.background_work import (
    BackgroundJobHandlerRegistry,
    BoundedBackgroundQueue,
    DurableBackgroundWorker,
    register_default_background_job_handlers,
)
from ..services.branches import BranchService
from ..services.coordination import CoordinationBackend, create_coordination_backend
from ..services.users import UserService
from ..skills import SkillRegistry
from ..storage.namespaces import conversation_namespace_for_context
from ..core.request_context import RequestContext
from .graph_builder import build_graph

logger = logging.getLogger("focus_agent.runtime")


@dataclass(slots=True)
class RuntimePersistence:
    checkpointer: object
    store: object
    repo: BranchRepository
    user_repository: UserRepository
    memory_repository: object | None
    trajectory_recorder: object | None
    artifact_metadata_repository: object | None


@dataclass(slots=True)
class RuntimeMemoryComponents:
    memory_policy: MemoryPolicy
    memory_retriever: MemoryRetriever
    memory_writer: MemoryWriter
    memory_extractor: MemoryExtractor
    memory_repository: object | None
    memory_embedding_service: MemoryEmbeddingService | None
    memory_embedding_provider: object | None
    memory_embedding_backend_error: str | None = None


@dataclass(slots=True)
class RuntimeMemoryEmbeddingSetup:
    provider: object | None
    backend_error: str | None
    dimensions: int
    memory_embeddings_enabled: bool


@dataclass(slots=True)
class RuntimeRegistries:
    skill_registry: SkillRegistry
    tool_registry: ToolRegistry


@dataclass(slots=True)
class RuntimeServices:
    branch_service: BranchService
    agent_team_service: AgentTeamService
    user_service: UserService


@dataclass(slots=True)
class AppRuntime:
    settings: Settings
    graph: object
    repo: BranchRepository
    user_repository: UserRepository
    branch_service: BranchService
    agent_team_service: AgentTeamService
    user_service: UserService
    checkpointer: object
    store: object
    store_namespace_selector: Callable[[RequestContext], tuple[str, ...]]
    memory_policy: MemoryPolicy
    memory_retriever: MemoryRetriever
    memory_writer: MemoryWriter
    memory_extractor: MemoryExtractor
    memory_repository: object | None
    memory_embedding_service: MemoryEmbeddingService | None
    memory_embedding_provider: object | None
    memory_embedding_backend_error: str | None
    skill_registry: SkillRegistry
    tool_registry: ToolRegistry
    trajectory_recorder: object | None
    artifact_metadata_repository: object | None
    otel_runtime: OTelRuntime
    background_work: BoundedBackgroundQueue
    durable_background_worker: DurableBackgroundWorker | None
    coordination_backend: CoordinationBackend
    _exit_stack: ExitStack

    def close(self) -> None:
        self._exit_stack.close()

    def conversation_store_namespace(self, context: RequestContext) -> tuple[str, ...]:
        return conversation_namespace_for_context(context)

    def start_durable_background_worker(self, chat_service: object) -> DurableBackgroundWorker | None:
        if str(getattr(self.settings, "background_job_execution", "best_effort")).strip().lower() != "durable":
            return None
        if self.durable_background_worker is not None:
            return self.durable_background_worker
        if not self.settings.database_uri or str(self.settings.background_job_backend).lower() != "postgres":
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
    if (
        str(getattr(settings, "background_job_execution", "best_effort")).strip().lower() == "durable"
        and (not settings.database_uri or str(settings.background_job_backend).lower() != "postgres")
    ):
        raise ValueError(
            "BACKGROUND_JOB_EXECUTION=durable requires DATABASE_URI and BACKGROUND_JOB_BACKEND=postgres."
        )
    ensure_runtime_directories(settings)
    exit_stack = ExitStack()
    otel_runtime = initialize_otel_runtime(settings)
    exit_stack.callback(otel_runtime.shutdown)
    coordination_backend = create_coordination_backend(
        database_uri=settings.database_uri,
        background_job_backend=settings.background_job_backend,
        background_job_claim_ttl_seconds=settings.background_job_claim_ttl_seconds,
    )
    background_work = BoundedBackgroundQueue(
        name="runtime",
        max_concurrency=settings.background_worker_max_concurrency,
        max_size=settings.background_queue_max_size,
        job_deduper=coordination_backend.job_deduper,
    )
    exit_stack.callback(background_work.close)

    memory_embedding_setup = _resolve_memory_embedding_setup(settings)
    persistence = _create_runtime_persistence(
        settings=settings,
        exit_stack=exit_stack,
        memory_embedding_setup=memory_embedding_setup,
    )
    memory = _create_memory_components(
        settings=settings,
        store=persistence.store,
        memory_repository=persistence.memory_repository,
        memory_embedding_setup=memory_embedding_setup,
    )
    registries = _create_runtime_registries(
        settings=settings,
        persistence=persistence,
        memory=memory,
    )
    graph = _create_runtime_graph(
        settings=settings,
        persistence=persistence,
        memory=memory,
        registries=registries,
    )
    services = _create_runtime_services(
        settings=settings,
        graph=graph,
        repo=persistence.repo,
        user_repository=persistence.user_repository,
        store=persistence.store,
        memory_writer=memory.memory_writer,
        memory_repository=persistence.memory_repository,
        coordination_backend=coordination_backend,
        background_work=background_work,
    )

    return AppRuntime(
        settings=settings,
        graph=graph,
        repo=persistence.repo,
        user_repository=persistence.user_repository,
        branch_service=services.branch_service,
        agent_team_service=services.agent_team_service,
        user_service=services.user_service,
        checkpointer=persistence.checkpointer,
        store=persistence.store,
        store_namespace_selector=conversation_namespace_for_context,
        memory_policy=memory.memory_policy,
        memory_retriever=memory.memory_retriever,
        memory_writer=memory.memory_writer,
        memory_extractor=memory.memory_extractor,
        memory_repository=memory.memory_repository,
        memory_embedding_service=memory.memory_embedding_service,
        memory_embedding_provider=memory.memory_embedding_provider,
        memory_embedding_backend_error=memory.memory_embedding_backend_error,
        skill_registry=registries.skill_registry,
        tool_registry=registries.tool_registry,
        trajectory_recorder=persistence.trajectory_recorder,
        artifact_metadata_repository=persistence.artifact_metadata_repository,
        otel_runtime=otel_runtime,
        background_work=background_work,
        durable_background_worker=None,
        coordination_backend=coordination_backend,
        _exit_stack=exit_stack,
    )


def _create_runtime_persistence(
    *,
    settings: Settings,
    exit_stack: ExitStack,
    memory_embedding_setup: RuntimeMemoryEmbeddingSetup,
) -> RuntimePersistence:
    if settings.database_uri:
        logger.info("Runtime persistence backend selected: postgres-primary")
        (
            checkpointer,
            store,
            repo,
            user_repository,
            memory_repository,
            trajectory_recorder,
            artifact_metadata_repository,
        ) = (
            _create_postgres_primary_persistence(
                settings=settings,
                exit_stack=exit_stack,
                memory_embedding_setup=memory_embedding_setup,
            )
        )
    else:
        logger.info("Runtime persistence backend selected: local-fallback")
        (
            checkpointer,
            store,
            repo,
            user_repository,
            memory_repository,
            trajectory_recorder,
            artifact_metadata_repository,
        ) = (
            _create_local_fallback_persistence(settings)
        )

    return RuntimePersistence(
        checkpointer=checkpointer,
        store=store,
        repo=repo,
        user_repository=user_repository,
        memory_repository=memory_repository,
        trajectory_recorder=trajectory_recorder,
        artifact_metadata_repository=artifact_metadata_repository,
    )


def _create_memory_components(
    *,
    settings: Settings,
    store: object,
    memory_repository: object | None = None,
    memory_embedding_setup: RuntimeMemoryEmbeddingSetup | None = None,
) -> RuntimeMemoryComponents:
    memory_policy = MemoryPolicy()
    memory_embedding_service, memory_embedding_backend_error = _create_memory_embedding_service(
        settings,
        memory_repository=memory_repository,
        memory_embedding_setup=memory_embedding_setup,
    )
    memory_embedding_provider = (
        memory_embedding_service.provider if memory_embedding_service is not None else None
    )
    vector_search_mode = str(getattr(settings, "agent_memory_vector_search_mode", "shadow")).strip().lower()
    memory_retriever = MemoryRetriever(
        store=store,
        repository=memory_repository,
        policy=memory_policy,
        retrieval_mode="hybrid" if vector_search_mode == "hybrid" else "fts",
        vector_shadow=vector_search_mode == "shadow",
        embedding_provider=memory_embedding_provider,
    )
    memory_writer = MemoryWriter(
        store=store,
        repository=memory_repository,
        policy=memory_policy,
        embedding_service=memory_embedding_service,
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
    )


def _create_memory_embedding_service(
    settings: Settings,
    *,
    memory_repository: object | None,
    memory_embedding_setup: RuntimeMemoryEmbeddingSetup | None = None,
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
        batch_size=getattr(settings, "agent_memory_embedding_batch_size", 32),
    )
    return service, None


def _create_runtime_registries(
    *,
    settings: Settings,
    persistence: RuntimePersistence,
    memory: RuntimeMemoryComponents,
) -> RuntimeRegistries:
    skill_registry = SkillRegistry.from_settings(settings)
    tool_registry = _build_tool_registry_compat(
        settings=settings,
        skill_registry=skill_registry,
        store=persistence.store,
        checkpointer=persistence.checkpointer,
        artifact_metadata_repository=persistence.artifact_metadata_repository,
        memory_repository=persistence.memory_repository,
        memory_embedding_service=memory.memory_embedding_service,
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


def _create_runtime_services(
    *,
    settings: Settings,
    graph: object,
    repo: BranchRepository,
    user_repository: UserRepository,
    store: object,
    memory_writer: MemoryWriter,
    memory_repository: object | None,
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
    )
    user_service = UserService(
        user_repository,
        auth_enabled=settings.auth_enabled,
    )
    return RuntimeServices(
        branch_service=branch_service,
        agent_team_service=agent_team_service,
        user_service=user_service,
    )


def _create_postgres_primary_persistence(
    *,
    settings: Settings,
    exit_stack: ExitStack,
    memory_embedding_setup: RuntimeMemoryEmbeddingSetup,
) -> tuple[object, object, BranchRepository, UserRepository, object | None, object | None, object]:
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.store.postgres import PostgresStore

    from ..repositories.artifact_metadata_repository import ArtifactMetadataRepository
    from ..repositories.postgres_branch_repository import PostgresBranchRepository
    from ..repositories.postgres_memory_repository import PostgresMemoryRepository
    from ..repositories.postgres_user_repository import PostgresUserRepository

    assert settings.database_uri is not None

    checkpointer = exit_stack.enter_context(PostgresSaver.from_conn_string(settings.database_uri))
    store = exit_stack.enter_context(PostgresStore.from_conn_string(settings.database_uri))
    checkpointer.setup()
    store.setup()

    repo = PostgresBranchRepository(settings.database_uri)
    _setup_component_if_available(repo)
    user_repository = PostgresUserRepository(settings.database_uri)
    _setup_component_if_available(user_repository)

    artifact_metadata_repository = ArtifactMetadataRepository(settings.database_uri)
    _setup_component_if_available(artifact_metadata_repository)

    memory_repository = PostgresMemoryRepository(settings.database_uri)
    _setup_memory_repository_if_available(
        memory_repository,
        settings=settings,
        memory_embedding_setup=memory_embedding_setup,
    )

    trajectory_recorder = None
    if _trajectory_enabled(settings):
        from ..repositories.postgres_trajectory_repository import PostgresTrajectoryRepository

        candidate = PostgresTrajectoryRepository(settings.database_uri)
        try:
            _setup_component_if_available(candidate)
        except Exception:  # noqa: BLE001
            logger.warning("failed to initialize Postgres trajectory persistence", exc_info=True)
        else:
            trajectory_recorder = candidate

    return (
        checkpointer,
        store,
        repo,
        user_repository,
        memory_repository,
        trajectory_recorder,
        artifact_metadata_repository,
    )


def _create_local_fallback_persistence(
    settings: Settings,
) -> tuple[object, object, BranchRepository, UserRepository, object | None, object | None, object | None]:
    persistence_dir = Path(settings.branch_db_path).expanduser().parent
    checkpoint_path = (
        Path(settings.local_checkpoint_path).expanduser()
        if settings.local_checkpoint_path
        else persistence_dir / "langgraph-checkpoints.pkl"
    )
    store_path = (
        Path(settings.local_store_path).expanduser()
        if settings.local_store_path
        else persistence_dir / "langgraph-store.pkl"
    )
    checkpointer = PersistentInMemorySaver(checkpoint_path)
    store = PersistentInMemoryStore(store_path)
    repo = SQLiteBranchRepository(settings.branch_db_path)
    user_repository = SQLiteUserRepository(settings.branch_db_path)
    return checkpointer, store, repo, user_repository, None, None, None


def _create_agent_team_repository(settings: Settings) -> AgentTeamRepository:
    if settings.database_uri:
        from ..repositories.postgres_agent_team_repository import PostgresAgentTeamRepository

        repository = PostgresAgentTeamRepository(settings.database_uri)
    else:
        repository = SQLiteAgentTeamRepository(settings.branch_db_path)
    _setup_component_if_available(repository)
    return repository


def _setup_component_if_available(component: object) -> None:
    setup = getattr(component, "setup", None)
    if callable(setup):
        setup()


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
    provider_id = str(getattr(settings, "agent_memory_embedding_provider", "") or "").strip().lower()
    if model_id in {"embeddinggemma", "embedding-gemma"} or backend == "ollama" or provider_id == "ollama":
        return 768
    return 1536


def _setup_memory_repository_if_available(
    component: object,
    *,
    settings: Settings,
    memory_embedding_setup: RuntimeMemoryEmbeddingSetup,
) -> None:
    setup = getattr(component, "setup", None)
    if not callable(setup):
        return
    signature = inspect.signature(setup)
    if not signature.parameters:
        setup()
        return
    setup(
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
    return str(getattr(settings, "agent_memory_vector_search_mode", "off")).strip().lower() == "hybrid"


def _build_tool_registry_compat(
    *,
    settings: Settings,
    skill_registry: SkillRegistry,
    store: object,
    checkpointer: object,
    artifact_metadata_repository: object | None,
    memory_repository: object | None = None,
    memory_embedding_service: object | None = None,
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
    return build_tool_registry(**kwargs)


def _trajectory_enabled(settings: Settings) -> bool:
    if settings.trajectory_enabled is None:
        return bool(settings.database_uri)
    return bool(settings.trajectory_enabled and settings.database_uri)
