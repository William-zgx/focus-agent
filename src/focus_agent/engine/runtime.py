from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import inspect
import logging
from pathlib import Path
from typing import Callable

from ..capabilities import ToolRegistry, build_tool_registry
from ..config import Settings
from ..engine.local_persistence import PersistentInMemorySaver, PersistentInMemoryStore
from ..memory import MemoryExtractor, MemoryPolicy, MemoryRetriever, MemoryWriter
from ..repositories.branch_repository import BranchRepository
from ..repositories.sqlite_branch_repository import SQLiteBranchRepository
from ..services.branches import BranchService
from ..skills import SkillRegistry
from ..storage.namespaces import conversation_namespace_for_context
from ..core.request_context import RequestContext
from .graph_builder import build_graph

logger = logging.getLogger("focus_agent.runtime")


@dataclass(slots=True)
class AppRuntime:
    settings: Settings
    graph: object
    repo: BranchRepository
    branch_service: BranchService
    checkpointer: object
    store: object
    store_namespace_selector: Callable[[RequestContext], tuple[str, ...]]
    memory_policy: MemoryPolicy
    memory_retriever: MemoryRetriever
    memory_writer: MemoryWriter
    memory_extractor: MemoryExtractor
    skill_registry: SkillRegistry
    tool_registry: ToolRegistry
    trajectory_recorder: object | None
    artifact_metadata_repository: object | None
    _exit_stack: ExitStack

    def close(self) -> None:
        self._exit_stack.close()

    def conversation_store_namespace(self, context: RequestContext) -> tuple[str, ...]:
        return conversation_namespace_for_context(context)


def create_runtime(settings: Settings | None = None) -> AppRuntime:
    settings = settings or Settings.from_env()
    exit_stack = ExitStack()

    if settings.database_uri:
        logger.info("Runtime persistence backend selected: postgres-primary")
        checkpointer, store, repo, trajectory_recorder, artifact_metadata_repository = (
            _create_postgres_primary_persistence(
                settings=settings,
                exit_stack=exit_stack,
            )
        )
    else:
        logger.info("Runtime persistence backend selected: local-fallback")
        checkpointer, store, repo, trajectory_recorder, artifact_metadata_repository = (
            _create_local_fallback_persistence(settings)
        )

    memory_policy = MemoryPolicy()
    memory_retriever = MemoryRetriever(store=store, policy=memory_policy)
    memory_writer = MemoryWriter(store=store, policy=memory_policy)
    memory_extractor = MemoryExtractor()
    skill_registry = SkillRegistry.from_settings(settings)
    tool_registry = _build_tool_registry_compat(
        settings=settings,
        skill_registry=skill_registry,
        store=store,
        checkpointer=checkpointer,
        artifact_metadata_repository=artifact_metadata_repository,
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
        tool_registry=tool_registry,
    )
    branch_service = BranchService(
        settings=settings,
        graph=graph,
        repo=repo,
        store=store,
        memory_writer=memory_writer,
    )

    return AppRuntime(
        settings=settings,
        graph=graph,
        repo=repo,
        branch_service=branch_service,
        checkpointer=checkpointer,
        store=store,
        store_namespace_selector=conversation_namespace_for_context,
        memory_policy=memory_policy,
        memory_retriever=memory_retriever,
        memory_writer=memory_writer,
        memory_extractor=memory_extractor,
        skill_registry=skill_registry,
        tool_registry=tool_registry,
        trajectory_recorder=trajectory_recorder,
        artifact_metadata_repository=artifact_metadata_repository,
        _exit_stack=exit_stack,
    )


def _create_postgres_primary_persistence(
    *,
    settings: Settings,
    exit_stack: ExitStack,
) -> tuple[object, object, BranchRepository, object | None, object]:
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.store.postgres import PostgresStore

    from ..repositories.artifact_metadata_repository import ArtifactMetadataRepository
    from ..repositories.postgres_branch_repository import PostgresBranchRepository

    assert settings.database_uri is not None

    checkpointer = exit_stack.enter_context(PostgresSaver.from_conn_string(settings.database_uri))
    store = exit_stack.enter_context(PostgresStore.from_conn_string(settings.database_uri))
    checkpointer.setup()
    store.setup()

    repo = PostgresBranchRepository(settings.database_uri)
    _setup_component_if_available(repo)

    artifact_metadata_repository = ArtifactMetadataRepository(settings.database_uri)
    _setup_component_if_available(artifact_metadata_repository)

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

    return checkpointer, store, repo, trajectory_recorder, artifact_metadata_repository


def _create_local_fallback_persistence(
    settings: Settings,
) -> tuple[object, object, BranchRepository, object | None, object | None]:
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
    return checkpointer, store, repo, None, None


def _setup_component_if_available(component: object) -> None:
    setup = getattr(component, "setup", None)
    if callable(setup):
        setup()


def _build_tool_registry_compat(
    *,
    settings: Settings,
    skill_registry: SkillRegistry,
    store: object,
    checkpointer: object,
    artifact_metadata_repository: object | None,
) -> ToolRegistry:
    kwargs = {
        "settings": settings,
        "skill_registry": skill_registry,
        "store": store,
        "checkpointer": checkpointer,
    }
    if "artifact_metadata_repository" in inspect.signature(build_tool_registry).parameters:
        kwargs["artifact_metadata_repository"] = artifact_metadata_repository
    return build_tool_registry(**kwargs)


def _trajectory_enabled(settings: Settings) -> bool:
    if settings.trajectory_enabled is None:
        return bool(settings.database_uri)
    return bool(settings.trajectory_enabled and settings.database_uri)
