from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
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
    _exit_stack: ExitStack

    def close(self) -> None:
        self._exit_stack.close()

    def conversation_store_namespace(self, context: RequestContext) -> tuple[str, ...]:
        return conversation_namespace_for_context(context)


def create_runtime(settings: Settings | None = None) -> AppRuntime:
    settings = settings or Settings.from_env()
    exit_stack = ExitStack()

    if settings.database_uri:
        from langgraph.checkpoint.postgres import PostgresSaver
        from langgraph.store.postgres import PostgresStore

        checkpointer = exit_stack.enter_context(PostgresSaver.from_conn_string(settings.database_uri))
        store = exit_stack.enter_context(PostgresStore.from_conn_string(settings.database_uri))
        checkpointer.setup()
        store.setup()
    else:
        persistence_dir = Path(settings.branch_db_path).expanduser().parent
        checkpoint_path = Path(settings.local_checkpoint_path).expanduser() if settings.local_checkpoint_path else persistence_dir / "langgraph-checkpoints.pkl"
        store_path = Path(settings.local_store_path).expanduser() if settings.local_store_path else persistence_dir / "langgraph-store.pkl"
        checkpointer = PersistentInMemorySaver(checkpoint_path)
        store = PersistentInMemoryStore(store_path)

    repo = SQLiteBranchRepository(settings.branch_db_path)
    memory_policy = MemoryPolicy()
    memory_retriever = MemoryRetriever(store=store, policy=memory_policy)
    memory_writer = MemoryWriter(store=store, policy=memory_policy)
    memory_extractor = MemoryExtractor()
    skill_registry = SkillRegistry.from_settings(settings)
    tool_registry = build_tool_registry(
        settings=settings,
        skill_registry=skill_registry,
        store=store,
        checkpointer=checkpointer,
    )
    graph = build_graph(
        settings=settings,
        checkpointer=checkpointer,
        store=store,
        memory_retriever=memory_retriever,
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
        _exit_stack=exit_stack,
    )
