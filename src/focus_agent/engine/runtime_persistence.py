from __future__ import annotations

import hashlib
import hmac
import importlib
import inspect
import logging
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from ..config import Settings
from ..storage.postgres import PostgresConnectionProvider
from .local_persistence import PersistentSQLiteStore

_FALSE_ENV_VALUES = {"0", "false", "no", "off"}
_SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
_LOGGER = logging.getLogger(__name__)


def _resolved_setting(settings: Settings, key: str) -> str:
    return str(
        getattr(settings, "resolved_env", {}).get(key, "") or os.environ.get(key, "")
    ).strip()


def _local_checkpoint_backend(settings: Settings) -> str:
    return (_resolved_setting(settings, "FOCUS_AGENT_CHECKPOINT_BACKEND") or "sqlite").lower()


def _legacy_pickle_paths(checkpoint_path: Path, store_path: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in (checkpoint_path, store_path)
        if path.suffix.lower() not in _SQLITE_SUFFIXES and path.exists()
    )


def _legacy_pickle_signature_path(path: Path) -> Path:
    return path.with_name(path.name + ".sig")


def _legacy_pickle_owner_matches(path: Path) -> bool:
    getuid = getattr(os, "getuid", None)
    if getuid is None:
        return True
    try:
        return path.stat().st_uid == getuid()
    except OSError:
        return False


def _require_verified_legacy_pickles(paths: tuple[Path, ...], hmac_key: str) -> None:
    key = hmac_key.encode("utf-8")
    for path in paths:
        signature_path = _legacy_pickle_signature_path(path)
        try:
            data = path.read_bytes()
            signature = signature_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(
                "Cannot safely use legacy pickle persistence at "
                f"{path}. Set FOCUS_AGENT_CHECKPOINT_BACKEND=sqlite to start "
                "with new local persistence after preserving the legacy files."
            ) from exc
        if not _legacy_pickle_owner_matches(path) or not _legacy_pickle_owner_matches(
            signature_path
        ):
            raise ValueError(
                "Cannot safely use legacy pickle persistence with an owner mismatch: "
                f"{path}. Set FOCUS_AGENT_CHECKPOINT_BACKEND=sqlite to start "
                "with new local persistence after preserving the legacy files."
            )
        expected = hmac.new(key, data, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError(
                "Cannot safely use legacy pickle persistence without a valid HMAC "
                f"signature: {path}. Set FOCUS_AGENT_CHECKPOINT_BACKEND=sqlite "
                "to start with new local persistence after preserving the legacy files."
            )


def _use_verified_legacy_pickle_backend(
    settings: Settings,
    checkpoint_path: Path,
    store_path: Path,
) -> bool:
    paths = _legacy_pickle_paths(checkpoint_path, store_path)
    if not paths:
        return False

    hmac_key = _resolved_setting(settings, "FOCUS_AGENT_CHECKPOINT_HMAC_KEY")
    if not hmac_key:
        raise ValueError(
            "Cannot safely use legacy pickle persistence without "
            "FOCUS_AGENT_CHECKPOINT_HMAC_KEY. Set FOCUS_AGENT_CHECKPOINT_BACKEND=sqlite "
            "to start with new local persistence after preserving the legacy files."
        )
    _require_verified_legacy_pickles(paths, hmac_key)
    _LOGGER.warning(
        "Using signed legacy pickle persistence at %s because "
        "FOCUS_AGENT_CHECKPOINT_BACKEND is unset. Set "
        "FOCUS_AGENT_CHECKPOINT_BACKEND=pickle to keep using it explicitly, "
        "or migrate the data to SQLite before selecting sqlite.",
        ", ".join(str(path) for path in paths),
    )
    return True


def _pickle_persistence_options(settings: Settings) -> dict[str, object]:
    verify_value = _resolved_setting(settings, "FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE")
    verify_signature = not verify_value or verify_value.lower() not in _FALSE_ENV_VALUES
    hmac_key = _resolved_setting(settings, "FOCUS_AGENT_CHECKPOINT_HMAC_KEY")
    if verify_signature and not hmac_key:
        raise ValueError(
            "FOCUS_AGENT_CHECKPOINT_HMAC_KEY is required when "
            "FOCUS_AGENT_CHECKPOINT_BACKEND=pickle and signature verification is enabled."
        )
    return {
        "hmac_key": hmac_key or None,
        "verify_signature": verify_signature,
    }


def _sqlite_path(path: Path) -> Path:
    if path.suffix.lower() in _SQLITE_SUFFIXES:
        return path
    return path.with_suffix(".sqlite3")


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


def _create_local_app_state_repositories(settings: Settings) -> tuple[object, object, object]:
    from ..repositories.sqlite_branch_repository import SQLiteBranchRepository
    from ..repositories.sqlite_productivity_repository import SQLiteProductivityRepository
    from ..repositories.sqlite_user_repository import SQLiteUserRepository

    database_path = str(Path(settings.branch_db_path).expanduser())
    return (
        SQLiteBranchRepository(database_path),
        SQLiteUserRepository(database_path),
        SQLiteProductivityRepository(database_path),
    )


def _create_local_fallback_persistence(
    settings: Settings,
) -> tuple[
    object, object, object, object, object | None, object, object | None, object | None, object
]:
    persistence_dir = Path(settings.branch_db_path).expanduser().parent
    backend = _local_checkpoint_backend(settings)
    checkpoint_path = (
        Path(settings.local_checkpoint_path).expanduser()
        if settings.local_checkpoint_path
        else persistence_dir / "langgraph-checkpoints.pkl"
    )
    configured_store_path = (
        Path(settings.local_store_path).expanduser()
        if settings.local_store_path
        else persistence_dir / "langgraph-store.pkl"
    )
    using_legacy_pickle = (
        backend == "sqlite"
        and not _resolved_setting(settings, "FOCUS_AGENT_CHECKPOINT_BACKEND")
        and _use_verified_legacy_pickle_backend(
            settings,
            checkpoint_path,
            configured_store_path,
        )
    )
    if using_legacy_pickle:
        backend = "pickle"
    pickle_options = _pickle_persistence_options(settings) if backend == "pickle" else None
    if using_legacy_pickle:
        assert pickle_options is not None
        pickle_options["verify_signature"] = True
    runtime_mod = _runtime_module()
    checkpointer = _create_local_checkpointer(
        settings,
        persistence_dir,
        checkpoint_path,
        backend=backend,
        pickle_options=pickle_options,
    )
    if backend == "pickle":
        store = runtime_mod.PersistentInMemoryStore(
            configured_store_path,
            **(pickle_options or {}),
        )
    elif backend == "sqlite":
        store = PersistentSQLiteStore(_sqlite_path(configured_store_path))
    else:
        raise ValueError(
            f"FOCUS_AGENT_CHECKPOINT_BACKEND must be one of: pickle, sqlite (got {backend!r})."
        )
    repo, user_repository, productivity_repository = _create_local_app_state_repositories(settings)
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
    *,
    backend: str | None = None,
    pickle_options: dict[str, object] | None = None,
) -> object:
    runtime_mod = _runtime_module()
    backend = backend or _local_checkpoint_backend(settings)
    if backend == "pickle":
        options = (
            pickle_options if pickle_options is not None else _pickle_persistence_options(settings)
        )
        return runtime_mod.PersistentInMemorySaver(checkpoint_path, **options)
    if backend == "sqlite":
        if settings.local_checkpoint_path:
            sqlite_path = _sqlite_path(Path(settings.local_checkpoint_path).expanduser())
        else:
            sqlite_path = persistence_dir / "langgraph-checkpoints.sqlite3"
        return runtime_mod.PersistentSQLiteSaver(sqlite_path)
    raise ValueError(
        f"FOCUS_AGENT_CHECKPOINT_BACKEND must be one of: pickle, sqlite (got {backend!r})."
    )
