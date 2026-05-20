from __future__ import annotations

import importlib
import inspect
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from ..config import Settings
from ..storage.postgres import PostgresConnectionProvider


def _runtime_module() -> Any:
    return importlib.import_module("focus_agent.engine.runtime")


def _postgres_run_journal_cls() -> object:
    runtime_mod = _runtime_module()
    if runtime_mod.PostgresRunJournal is not None:
        return runtime_mod.PostgresRunJournal
    from ..harness.observability.postgres_run_journal import (
        PostgresRunJournal as PostgresRunJournalClass,
    )

    return PostgresRunJournalClass


def _sqlite_run_journal_cls() -> object:
    runtime_mod = _runtime_module()
    if runtime_mod.SQLiteRunJournal is not None:
        return runtime_mod.SQLiteRunJournal
    from ..harness.observability.run_journal import SQLiteRunJournal as SQLiteRunJournalClass

    return SQLiteRunJournalClass


def _create_postgres_primary_persistence(
    *,
    settings: Settings,
    exit_stack: ExitStack,
    memory_embedding_setup: object,
    postgres_connection_provider: PostgresConnectionProvider | None,
) -> tuple[object, object, object, object, object | None, object, object | None, object, object]:
    runtime_mod = _runtime_module()
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.store.postgres import PostgresStore

    from ..repositories.artifact_metadata_repository import ArtifactMetadataRepository
    from ..repositories.postgres_branch_repository import PostgresBranchRepository
    from ..repositories.postgres_memory_repository import PostgresMemoryRepository
    from ..repositories.postgres_productivity_repository import PostgresProductivityRepository
    from ..repositories.postgres_user_repository import PostgresUserRepository

    assert settings.database_uri is not None

    if bool(getattr(settings, "db_pool_enabled", True)) and bool(
        getattr(settings, "postgres_pool_enabled", True)
    ):
        checkpointer_pool = exit_stack.enter_context(
            runtime_mod._langgraph_postgres_pool(settings=settings, name="focus-agent-checkpointer")
        )
        store_pool = exit_stack.enter_context(
            runtime_mod._langgraph_postgres_pool(settings=settings, name="focus-agent-store")
        )
        checkpointer = PostgresSaver(checkpointer_pool)
        store = PostgresStore(store_pool)
    else:
        checkpointer = exit_stack.enter_context(
            PostgresSaver.from_conn_string(settings.database_uri)
        )
        store = exit_stack.enter_context(PostgresStore.from_conn_string(settings.database_uri))
    checkpointer.setup()
    store.setup()

    repo = runtime_mod._create_repository_with_provider(
        PostgresBranchRepository,
        settings.database_uri,
        connection_provider=postgres_connection_provider,
    )
    runtime_mod._setup_component_if_available(repo)
    user_repository = PostgresUserRepository(settings.database_uri)
    runtime_mod._setup_component_if_available(user_repository)

    artifact_metadata_repository = ArtifactMetadataRepository(settings.database_uri)
    runtime_mod._setup_component_if_available(artifact_metadata_repository)

    memory_repository = runtime_mod._create_repository_with_provider(
        PostgresMemoryRepository,
        settings.database_uri,
        connection_provider=postgres_connection_provider,
    )
    runtime_mod._setup_memory_repository_if_available(
        memory_repository,
        settings=settings,
        memory_embedding_setup=memory_embedding_setup,
    )

    productivity_repository = PostgresProductivityRepository(settings.database_uri)
    runtime_mod._setup_component_if_available(productivity_repository)

    trajectory_recorder = None
    if runtime_mod._trajectory_enabled(settings):
        from ..repositories.postgres_trajectory_repository import PostgresTrajectoryRepository

        candidate = runtime_mod._create_repository_with_provider(
            PostgresTrajectoryRepository,
            settings.database_uri,
            connection_provider=postgres_connection_provider,
        )
        try:
            runtime_mod._setup_component_if_available(candidate)
        except Exception:  # noqa: BLE001
            runtime_mod.logger.warning(
                "failed to initialize Postgres trajectory persistence", exc_info=True
            )
        else:
            trajectory_recorder = candidate

    run_journal = runtime_mod._postgres_run_journal_cls()(settings.database_uri)
    runtime_mod._setup_component_if_available(run_journal)

    return (
        checkpointer,
        store,
        repo,
        user_repository,
        memory_repository,
        productivity_repository,
        trajectory_recorder,
        artifact_metadata_repository,
        run_journal,
    )


def _create_repository_with_provider(
    repository_cls: object,
    database_uri: str,
    *,
    connection_provider: PostgresConnectionProvider | None,
) -> object:
    kwargs: dict[str, object] = {}
    if connection_provider is not None:
        signature = inspect.signature(repository_cls)
        if "connection_provider" in signature.parameters:
            kwargs["connection_provider"] = connection_provider
    return repository_cls(database_uri, **kwargs)  # type: ignore[operator]


def _create_local_fallback_persistence(
    settings: Settings,
) -> tuple[object, object, object, object, object | None, object, object | None, object | None, object]:
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
    runtime_mod = _runtime_module()
    checkpointer = runtime_mod._create_local_checkpointer(settings, persistence_dir, checkpoint_path)
    store = runtime_mod.PersistentInMemoryStore(store_path)
    repo = runtime_mod.InMemoryBranchRepository()
    user_repository = runtime_mod.InMemoryUserRepository()
    productivity_repository = runtime_mod.InMemoryProductivityRepository()
    run_journal = runtime_mod._sqlite_run_journal_cls()(persistence_dir / "harness_runs.sqlite3")
    runtime_mod._setup_component_if_available(run_journal)
    return (
        checkpointer,
        store,
        repo,
        user_repository,
        None,
        productivity_repository,
        None,
        None,
        run_journal,
    )


def _create_local_checkpointer(
    settings: Settings,
    persistence_dir: Path,
    checkpoint_path: Path,
) -> object:
    runtime_mod = _runtime_module()
    backend = str(
        getattr(settings, "resolved_env", {}).get("FOCUS_AGENT_CHECKPOINT_BACKEND", "")
        or os.environ.get("FOCUS_AGENT_CHECKPOINT_BACKEND", "")
        or "pickle"
    ).strip().lower()
    if backend == "pickle":
        return runtime_mod.PersistentInMemorySaver(checkpoint_path)
    if backend == "sqlite":
        if settings.local_checkpoint_path:
            candidate = Path(settings.local_checkpoint_path).expanduser()
            sqlite_path = (
                candidate
                if candidate.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
                else candidate.with_suffix(".sqlite3")
            )
        else:
            sqlite_path = persistence_dir / "langgraph-checkpoints.sqlite3"
        return runtime_mod.PersistentSQLiteSaver(sqlite_path)
    raise ValueError(
        "FOCUS_AGENT_CHECKPOINT_BACKEND must be one of: pickle, sqlite "
        f"(got {backend!r})."
    )
