from __future__ import annotations

import logging
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from langchain.tools import tool

import focus_agent.engine.runtime as runtime_mod
import focus_agent.engine.runtime_persistence as runtime_persistence_mod
from focus_agent.config import Settings, ToolCatalogConfig, ensure_runtime_directories
from focus_agent.config_parts.catalogs import ToolProviderConfig
from focus_agent.services.coordination import (
    InMemoryBackgroundJobDeduperBackend,
    InMemoryThreadTurnLockBackend,
    PostgresBackgroundJobDeduperBackend,
    PostgresThreadTurnLockBackend,
)
from focus_agent.storage.postgres import PostgresConnectionProvider


class _FakeContextManager:
    def __init__(self, value: object):
        self.value = value

    def __enter__(self) -> object:
        return self.value

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeMemoryPolicy:
    pass


class _FakeMemoryComponent:
    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs


class _FakeMemoryExtractor:
    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs


class _FakeSkillRegistry:
    @staticmethod
    def from_settings(settings: Settings) -> object:
        return {"settings": settings}


class _FakeBranchService:
    def __init__(self, **kwargs: Any):
        self.kwargs = kwargs


def _make_postgres_component(*, with_factory: bool):
    class _Component:
        instances: list[_Component] = []

        def __init__(self, value: str):
            self.value = value
            self.setup_calls = 0
            self.setup_kwargs: dict[str, object] = {}
            type(self).instances.append(self)

        @classmethod
        def from_conn_string(cls, value: str) -> _FakeContextManager:
            if not with_factory:
                raise AssertionError("from_conn_string() should not be used for this fake")
            return _FakeContextManager(cls(value))

        def setup(self, **kwargs: object) -> None:
            self.setup_calls += 1
            self.setup_kwargs = dict(kwargs)

    return _Component


def _install_postgres_modules(monkeypatch):
    saver_cls = _make_postgres_component(with_factory=True)
    store_cls = _make_postgres_component(with_factory=True)
    branch_repo_cls = _make_postgres_component(with_factory=False)
    artifact_repo_cls = _make_postgres_component(with_factory=False)
    memory_repo_cls = _make_postgres_component(with_factory=False)
    productivity_repo_cls = _make_postgres_component(with_factory=False)
    trajectory_repo_cls = _make_postgres_component(with_factory=False)
    agent_team_repo_cls = _make_postgres_component(with_factory=False)
    user_repo_cls = _make_postgres_component(with_factory=False)
    run_journal_cls = _make_postgres_component(with_factory=False)

    checkpoint_module = types.ModuleType("langgraph.checkpoint.postgres")
    checkpoint_module.PostgresSaver = saver_cls
    store_module = types.ModuleType("langgraph.store.postgres")
    store_module.PostgresStore = store_cls
    branch_module = types.ModuleType("focus_agent.repositories.postgres_branch_repository")
    branch_module.PostgresBranchRepository = branch_repo_cls
    artifact_module = types.ModuleType("focus_agent.repositories.artifact_metadata_repository")
    artifact_module.ArtifactMetadataRepository = artifact_repo_cls
    memory_module = types.ModuleType("focus_agent.repositories.postgres_memory_repository")
    memory_module.PostgresMemoryRepository = memory_repo_cls
    productivity_module = types.ModuleType(
        "focus_agent.repositories.postgres_productivity_repository"
    )
    productivity_module.PostgresProductivityRepository = productivity_repo_cls
    trajectory_module = types.ModuleType("focus_agent.repositories.postgres_trajectory_repository")
    trajectory_module.PostgresTrajectoryRepository = trajectory_repo_cls
    agent_team_module = types.ModuleType("focus_agent.repositories.postgres_agent_team_repository")
    agent_team_module.PostgresAgentTeamRepository = agent_team_repo_cls
    user_module = types.ModuleType("focus_agent.repositories.postgres_user_repository")
    user_module.PostgresUserRepository = user_repo_cls

    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.postgres", checkpoint_module)
    monkeypatch.setitem(sys.modules, "langgraph.store.postgres", store_module)
    monkeypatch.setitem(
        sys.modules, "focus_agent.repositories.postgres_branch_repository", branch_module
    )
    monkeypatch.setitem(
        sys.modules, "focus_agent.repositories.artifact_metadata_repository", artifact_module
    )
    monkeypatch.setitem(
        sys.modules, "focus_agent.repositories.postgres_memory_repository", memory_module
    )
    monkeypatch.setitem(
        sys.modules,
        "focus_agent.repositories.postgres_productivity_repository",
        productivity_module,
    )
    monkeypatch.setitem(
        sys.modules, "focus_agent.repositories.postgres_trajectory_repository", trajectory_module
    )
    monkeypatch.setitem(
        sys.modules, "focus_agent.repositories.postgres_agent_team_repository", agent_team_module
    )
    monkeypatch.setitem(
        sys.modules, "focus_agent.repositories.postgres_user_repository", user_module
    )
    monkeypatch.setattr(
        runtime_mod,
        "_langgraph_postgres_pool",
        lambda *, settings, name: _FakeContextManager(f"{name}:{settings.database_uri}"),
    )
    monkeypatch.setattr(runtime_mod, "PostgresRunJournal", run_journal_cls)

    return {
        "saver": saver_cls,
        "store": store_cls,
        "branch_repo": branch_repo_cls,
        "artifact_repo": artifact_repo_cls,
        "memory_repo": memory_repo_cls,
        "productivity_repo": productivity_repo_cls,
        "trajectory_repo": trajectory_repo_cls,
        "agent_team_repo": agent_team_repo_cls,
        "user_repo": user_repo_cls,
        "run_journal": run_journal_cls,
    }


def _patch_runtime_collaborators(monkeypatch, *, build_tool_registry):
    local_run_journal_cls = _make_postgres_component(with_factory=False)

    def fake_create_focus_agent(config, **kwargs):
        return types.SimpleNamespace(
            config=config,
            graph={"graph": kwargs},
            run_manager=types.SimpleNamespace(store=kwargs.get("event_store")),
            stream_bridge=types.SimpleNamespace(event_store=kwargs.get("event_store")),
            event_store=kwargs.get("event_store"),
            tool_registry=kwargs.get("tool_registry"),
        )

    monkeypatch.setattr(runtime_mod, "MemoryPolicy", _FakeMemoryPolicy)
    monkeypatch.setattr(runtime_mod, "MemoryRetriever", _FakeMemoryComponent)
    monkeypatch.setattr(runtime_mod, "MemoryWriter", _FakeMemoryComponent)
    monkeypatch.setattr(runtime_mod, "MemoryExtractor", _FakeMemoryExtractor)
    monkeypatch.setattr(runtime_mod, "SkillRegistry", _FakeSkillRegistry)
    monkeypatch.setattr(runtime_mod, "build_graph", lambda **kwargs: {"graph": kwargs})
    monkeypatch.setattr(runtime_mod, "BranchService", _FakeBranchService)
    monkeypatch.setattr(runtime_mod, "build_tool_registry", build_tool_registry)
    monkeypatch.setattr(runtime_mod, "SQLiteRunJournal", local_run_journal_cls)
    monkeypatch.setattr(runtime_mod, "create_focus_agent", fake_create_focus_agent)
    return {"local_run_journal": local_run_journal_cls}


def _make_settings(
    tmp_path: Path, *, database_uri: str | None, trajectory_enabled: bool | None
) -> Settings:
    return Settings(
        database_uri=database_uri,
        branch_db_path=str(tmp_path / "branches.sqlite3"),
        artifact_dir=str(tmp_path / "artifacts"),
        local_checkpoint_path=str(tmp_path / "langgraph-checkpoints.pkl"),
        local_store_path=str(tmp_path / "langgraph-store.pkl"),
        trajectory_enabled=trajectory_enabled,
    )


def test_create_runtime_selects_postgres_primary_and_forwards_artifact_repo(
    monkeypatch, tmp_path, caplog
):
    captured: dict[str, object] = {}

    def fake_build_tool_registry(
        *,
        settings,
        skill_registry,
        store=None,
        checkpointer=None,
        artifact_metadata_repository=None,
        memory_repository=None,
    ):
        captured["settings"] = settings
        captured["skill_registry"] = skill_registry
        captured["store"] = store
        captured["checkpointer"] = checkpointer
        captured["artifact_metadata_repository"] = artifact_metadata_repository
        captured["memory_repository"] = memory_repository
        return {"tool_registry": True}

    fake_modules = _install_postgres_modules(monkeypatch)
    _patch_runtime_collaborators(monkeypatch, build_tool_registry=fake_build_tool_registry)
    caplog.set_level(logging.INFO, logger="focus_agent.runtime")

    runtime = runtime_mod.create_runtime(
        _make_settings(
            tmp_path,
            database_uri="postgresql://focus-agent.test/runtime",
            trajectory_enabled=True,
        )
    )
    try:
        saver = fake_modules["saver"].instances[0]
        store = fake_modules["store"].instances[0]
        repo = fake_modules["branch_repo"].instances[0]
        artifact_repo = fake_modules["artifact_repo"].instances[0]
        memory_repo = fake_modules["memory_repo"].instances[0]
        trajectory_repo = fake_modules["trajectory_repo"].instances[0]
        agent_team_repo = fake_modules["agent_team_repo"].instances[0]
        user_repo = fake_modules["user_repo"].instances[0]
        run_journal = fake_modules["run_journal"].instances[0]

        assert runtime.checkpointer is saver
        assert runtime.store is store
        assert runtime.event_store is run_journal
        assert runtime.repo is repo
        assert runtime.user_repository is user_repo
        assert runtime.memory_repository is memory_repo
        assert runtime.artifact_metadata_repository is artifact_repo
        assert runtime.trajectory_recorder is trajectory_repo
        assert runtime.agent_team_service.repository is agent_team_repo
        assert runtime.agent_team_service._agent_team_runtime is runtime
        assert runtime.user_service.repository is user_repo
        assert isinstance(runtime.coordination_backend.thread_turns, PostgresThreadTurnLockBackend)
        assert isinstance(
            runtime.coordination_backend.job_deduper, InMemoryBackgroundJobDeduperBackend
        )
        assert saver.setup_calls == 1
        assert store.setup_calls == 1
        assert repo.setup_calls == 1
        assert artifact_repo.setup_calls == 1
        assert memory_repo.setup_calls == 1
        assert trajectory_repo.setup_calls == 1
        assert agent_team_repo.setup_calls == 1
        assert user_repo.setup_calls == 1
        assert run_journal.setup_calls == 1
        assert captured["artifact_metadata_repository"] is artifact_repo
        assert captured["memory_repository"] is memory_repo
        assert runtime.memory_retriever.kwargs["repository"] is memory_repo
        assert runtime.memory_writer.kwargs["repository"] is memory_repo
        assert "postgres-primary" in caplog.text
    finally:
        runtime.close()


def test_create_runtime_defaults_local_fallback_to_sqlite_when_database_uri_is_missing(
    monkeypatch, tmp_path, caplog
):
    captured: dict[str, object] = {}

    def fake_build_tool_registry(*, settings, skill_registry, store=None, checkpointer=None):
        captured["settings"] = settings
        captured["skill_registry"] = skill_registry
        captured["store"] = store
        captured["checkpointer"] = checkpointer
        return {"tool_registry": True}

    class _FakeSQLiteSaver:
        def __init__(self, path: Path):
            self.path = Path(path)

    class _FakeSQLiteStore:
        def __init__(self, path: Path):
            self.path = Path(path)

    class _FakeSQLiteBranchRepository:
        instances: list[_FakeSQLiteBranchRepository] = []

        def __init__(self, path: str):
            self.path = Path(path)
            self.__class__.instances.append(self)

    class _FakeInMemoryAgentTeamRepository:
        instances: list[_FakeInMemoryAgentTeamRepository] = []

        def __init__(self):
            self.__class__.instances.append(self)

    class _FakeSQLiteUserRepository:
        instances: list[_FakeSQLiteUserRepository] = []

        def __init__(self, path: str):
            self.path = Path(path)
            self.__class__.instances.append(self)

    class _FakeSQLiteProductivityRepository:
        instances: list[_FakeSQLiteProductivityRepository] = []

        def __init__(self, path: str):
            self.path = Path(path)
            self.__class__.instances.append(self)

    fakes = _patch_runtime_collaborators(monkeypatch, build_tool_registry=fake_build_tool_registry)
    monkeypatch.setattr(runtime_mod, "PersistentSQLiteSaver", _FakeSQLiteSaver)
    monkeypatch.setattr(runtime_persistence_mod, "PersistentSQLiteStore", _FakeSQLiteStore)
    monkeypatch.setattr(
        "focus_agent.repositories.sqlite_branch_repository.SQLiteBranchRepository",
        _FakeSQLiteBranchRepository,
    )
    monkeypatch.setattr(
        "focus_agent.repositories.sqlite_user_repository.SQLiteUserRepository",
        _FakeSQLiteUserRepository,
    )
    monkeypatch.setattr(
        "focus_agent.repositories.sqlite_productivity_repository.SQLiteProductivityRepository",
        _FakeSQLiteProductivityRepository,
    )
    monkeypatch.setattr(
        runtime_mod, "InMemoryAgentTeamRepository", _FakeInMemoryAgentTeamRepository
    )
    caplog.set_level(logging.INFO, logger="focus_agent.runtime")

    settings = _make_settings(tmp_path, database_uri=None, trajectory_enabled=None)
    runtime = runtime_mod.create_runtime(settings)
    try:
        assert isinstance(runtime.checkpointer, _FakeSQLiteSaver)
        assert runtime.checkpointer.path == tmp_path / "langgraph-checkpoints.sqlite3"
        assert isinstance(runtime.store, _FakeSQLiteStore)
        assert runtime.store.path == tmp_path / "langgraph-store.sqlite3"
        assert runtime.event_store is fakes["local_run_journal"].instances[0]
        assert runtime.event_store.value == tmp_path / "harness_runs.sqlite3"
        assert runtime.event_store.setup_calls == 1
        assert isinstance(runtime.repo, _FakeSQLiteBranchRepository)
        assert runtime.repo.path == tmp_path / "branches.sqlite3"
        assert isinstance(runtime.user_repository, _FakeSQLiteUserRepository)
        assert runtime.user_repository.path == tmp_path / "branches.sqlite3"
        assert isinstance(runtime.user_service.repository, _FakeSQLiteUserRepository)
        assert isinstance(runtime.productivity_repository, _FakeSQLiteProductivityRepository)
        assert runtime.productivity_repository.path == tmp_path / "branches.sqlite3"
        assert isinstance(runtime.agent_team_service.repository, _FakeInMemoryAgentTeamRepository)
        assert runtime.trajectory_recorder is None
        assert runtime.artifact_metadata_repository is None
        assert runtime.memory_repository is None
        assert runtime.postgres_connection_provider is None
        assert isinstance(runtime.coordination_backend.thread_turns, InMemoryThreadTurnLockBackend)
        assert isinstance(
            runtime.coordination_backend.job_deduper, InMemoryBackgroundJobDeduperBackend
        )
        assert captured["store"] is runtime.store
        assert captured["checkpointer"] is runtime.checkpointer
        assert "local-fallback" in caplog.text
    finally:
        runtime.close()


def test_create_runtime_selects_explicit_sqlite_persistence_backend(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_build_tool_registry(*, settings, skill_registry, store=None, checkpointer=None):
        captured["store"] = store
        captured["checkpointer"] = checkpointer
        return {"tool_registry": True}

    class _FakePickleSaver:
        def __init__(self, path: Path):
            self.path = Path(path)

    class _FakeSQLiteSaver:
        def __init__(self, path: Path):
            self.path = Path(path)

    class _FakeSQLiteStore:
        def __init__(self, path: Path):
            self.path = Path(path)

    class _FakeInMemoryBranchRepository:
        pass

    class _FakeInMemoryAgentTeamRepository:
        pass

    class _FakeInMemoryUserRepository:
        pass

    _patch_runtime_collaborators(monkeypatch, build_tool_registry=fake_build_tool_registry)
    monkeypatch.setattr(runtime_mod, "PersistentInMemorySaver", _FakePickleSaver)
    monkeypatch.setattr(runtime_mod, "PersistentSQLiteSaver", _FakeSQLiteSaver)
    monkeypatch.setattr(runtime_persistence_mod, "PersistentSQLiteStore", _FakeSQLiteStore)
    monkeypatch.setattr(runtime_mod, "InMemoryBranchRepository", _FakeInMemoryBranchRepository)
    monkeypatch.setattr(
        runtime_mod, "InMemoryAgentTeamRepository", _FakeInMemoryAgentTeamRepository
    )
    monkeypatch.setattr(runtime_mod, "InMemoryUserRepository", _FakeInMemoryUserRepository)

    settings = _make_settings(tmp_path, database_uri=None, trajectory_enabled=None)
    settings.resolved_env["FOCUS_AGENT_CHECKPOINT_BACKEND"] = "sqlite"
    runtime = runtime_mod.create_runtime(settings)
    try:
        assert isinstance(runtime.checkpointer, _FakeSQLiteSaver)
        assert runtime.checkpointer.path == tmp_path / "langgraph-checkpoints.sqlite3"
        assert isinstance(runtime.store, _FakeSQLiteStore)
        assert runtime.store.path == tmp_path / "langgraph-store.sqlite3"
        assert captured["checkpointer"] is runtime.checkpointer
    finally:
        runtime.close()


def test_create_runtime_injects_deterministic_memory_embedding_service(monkeypatch, tmp_path):
    def fake_build_tool_registry(
        *,
        settings,
        skill_registry,
        store=None,
        checkpointer=None,
        artifact_metadata_repository=None,
        memory_repository=None,
    ):
        return {
            "store": store,
            "checkpointer": checkpointer,
            "artifact_metadata_repository": artifact_metadata_repository,
            "memory_repository": memory_repository,
        }

    fake_modules = _install_postgres_modules(monkeypatch)
    monkeypatch.setattr(
        fake_modules["memory_repo"],
        "upsert_embedding",
        lambda self, **kwargs: kwargs.get("memory_id", "embedding-id"),
        raising=False,
    )
    _patch_runtime_collaborators(monkeypatch, build_tool_registry=fake_build_tool_registry)

    settings = _make_settings(
        tmp_path,
        database_uri="postgresql://focus-agent.test/runtime",
        trajectory_enabled=False,
    )
    settings.agent_memory_embedding_backend = "deterministic_test"
    settings.agent_memory_embedding_dimensions = 5
    runtime = runtime_mod.create_runtime(settings)
    try:
        assert runtime.memory_embedding_service is not None
        assert runtime.memory_embedding_service.provider.provider_id == "deterministic_test"
        assert len(runtime.memory_embedding_service.provider.embed_query("runtime probe")) == 5
        assert runtime.memory_embedding_backend_error is None
        assert fake_modules["memory_repo"].instances[0].setup_kwargs == {
            "dimensions": 5,
            "vector_index": False,
            "memory_embeddings_enabled": True,
            "pgvector_extension_mode": "auto_create",
        }
    finally:
        runtime.close()


def test_create_runtime_sets_pgvector_schema_dimensions_from_resolved_provider(
    monkeypatch,
    tmp_path,
):
    class _Provider:
        provider_id = "ollama"
        model_id = "embeddinggemma"
        dimensions = 7

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * self.dimensions for _ in texts]

    provider = _Provider()

    def fake_build_tool_registry(
        *,
        settings,
        skill_registry,
        store=None,
        checkpointer=None,
        artifact_metadata_repository=None,
        memory_repository=None,
        memory_embedding_service=None,
    ):
        return {
            "settings": settings,
            "skill_registry": skill_registry,
            "store": store,
            "checkpointer": checkpointer,
            "artifact_metadata_repository": artifact_metadata_repository,
            "memory_repository": memory_repository,
            "memory_embedding_service": memory_embedding_service,
        }

    fake_modules = _install_postgres_modules(monkeypatch)
    _patch_runtime_collaborators(monkeypatch, build_tool_registry=fake_build_tool_registry)
    monkeypatch.setattr(
        runtime_mod,
        "create_memory_embedding_provider",
        lambda settings: provider,  # noqa: ARG005
    )

    settings = _make_settings(
        tmp_path,
        database_uri="postgresql://focus-agent.test/runtime",
        trajectory_enabled=False,
    )
    settings.agent_memory_embedding_backend = "auto"
    settings.agent_memory_embedding_model = "embeddinggemma"
    settings.agent_memory_embedding_dimensions = 1536

    runtime = runtime_mod.create_runtime(settings)
    try:
        assert runtime.memory_embedding_service is not None
        assert runtime.memory_embedding_service.provider is provider
        assert settings.agent_memory_embedding_dimensions == 7
        assert fake_modules["memory_repo"].instances[0].setup_kwargs == {
            "dimensions": 7,
            "vector_index": False,
            "memory_embeddings_enabled": True,
            "pgvector_extension_mode": "auto_create",
        }
    finally:
        runtime.close()


def test_create_runtime_auto_loads_registered_builtin_tool_provider(monkeypatch, tmp_path):
    def runtime_probe_impl() -> str:
        """Return a marker from the runtime provider registry test."""
        return "runtime-loaded"

    runtime_probe = tool(runtime_probe_impl)

    def fake_get_default_tools(settings, **kwargs):  # noqa: ARG001
        return [runtime_probe]

    class _FakeLocalSaver:
        def __init__(self, path: Path):
            self.path = Path(path)

    class _FakeLocalStore:
        def __init__(self, path: Path):
            self.path = Path(path)

    class _FakeInMemoryBranchRepository:
        instances: list[_FakeInMemoryBranchRepository] = []

        def __init__(self):
            self.__class__.instances.append(self)

    class _FakeInMemoryAgentTeamRepository:
        instances: list[_FakeInMemoryAgentTeamRepository] = []

        def __init__(self):
            self.__class__.instances.append(self)

    class _FakeInMemoryUserRepository:
        instances: list[_FakeInMemoryUserRepository] = []

        def __init__(self):
            self.__class__.instances.append(self)

    monkeypatch.setattr(
        "focus_agent.capabilities.tool_registry.get_default_tools",
        fake_get_default_tools,
    )
    _patch_runtime_collaborators(monkeypatch, build_tool_registry=runtime_mod.build_tool_registry)
    monkeypatch.setattr(runtime_mod, "PersistentInMemorySaver", _FakeLocalSaver)
    monkeypatch.setattr(runtime_mod, "PersistentInMemoryStore", _FakeLocalStore)
    monkeypatch.setattr(runtime_mod, "InMemoryBranchRepository", _FakeInMemoryBranchRepository)
    monkeypatch.setattr(
        runtime_mod, "InMemoryAgentTeamRepository", _FakeInMemoryAgentTeamRepository
    )
    monkeypatch.setattr(runtime_mod, "InMemoryUserRepository", _FakeInMemoryUserRepository)

    settings = _make_settings(tmp_path, database_uri=None, trajectory_enabled=None)
    settings.tool_catalog = ToolCatalogConfig(
        providers=(
            ToolProviderConfig(id="builtin", enabled=True),
            ToolProviderConfig(id="skill", enabled=False),
        )
    )

    runtime = runtime_mod.create_runtime(settings)
    try:
        assert runtime.tool_registry.by_name["runtime_probe_impl"].invoke({}) == "runtime-loaded"
        assert runtime.tool_registry.runtime_by_name["runtime_probe_impl"].provider_id == "builtin"
    finally:
        runtime.close()


def test_create_runtime_uses_postgres_background_jobs_only_when_opted_in(monkeypatch, tmp_path):
    def fake_build_tool_registry(
        *,
        settings,
        skill_registry,
        store=None,
        checkpointer=None,
        artifact_metadata_repository=None,
    ):
        return {"artifact_metadata_repository": artifact_metadata_repository}

    _install_postgres_modules(monkeypatch)
    _patch_runtime_collaborators(monkeypatch, build_tool_registry=fake_build_tool_registry)

    settings = _make_settings(
        tmp_path,
        database_uri="postgresql://focus-agent.test/runtime",
        trajectory_enabled=False,
    )
    settings.background_job_backend = "postgres"
    settings.background_job_claim_ttl_seconds = 12.0
    runtime = runtime_mod.create_runtime(settings)
    try:
        assert isinstance(runtime.coordination_backend.thread_turns, PostgresThreadTurnLockBackend)
        assert isinstance(
            runtime.coordination_backend.job_deduper, PostgresBackgroundJobDeduperBackend
        )
        assert runtime.coordination_backend.job_deduper.claim_ttl_seconds == 12.0
    finally:
        runtime.close()


def test_create_runtime_exposes_postgres_connection_provider(monkeypatch, tmp_path):
    def fake_build_tool_registry(
        *,
        settings,
        skill_registry,
        store=None,
        checkpointer=None,
        artifact_metadata_repository=None,
    ):
        return {"artifact_metadata_repository": artifact_metadata_repository}

    _install_postgres_modules(monkeypatch)
    _patch_runtime_collaborators(monkeypatch, build_tool_registry=fake_build_tool_registry)

    settings = _make_settings(
        tmp_path,
        database_uri="postgresql://focus-agent.test/runtime",
        trajectory_enabled=False,
    )
    settings.postgres_pool_enabled = False
    settings.postgres_slow_query_threshold_ms = 125.0
    runtime = runtime_mod.create_runtime(settings)
    try:
        provider = runtime.postgres_connection_provider
        assert provider is not None
        snapshot = provider.snapshot()
        assert snapshot["postgres_pool_enabled"] == 0
        assert snapshot["postgres_pool_fallback_direct"] == 1
        assert snapshot["postgres_slow_query_threshold_ms"] == 125.0
    finally:
        runtime.close()


def test_postgres_connection_provider_records_slow_query_metrics(caplog):
    provider = PostgresConnectionProvider(
        "postgresql://focus-agent.test/runtime",
        pool_enabled=False,
        slow_query_threshold_ms=10.0,
    )
    caplog.set_level(logging.WARNING, logger="focus_agent.postgres")

    provider._record_query(duration_ms=12.5, statement="SELECT pg_sleep(1)", error=None)
    snapshot = provider.snapshot()

    assert snapshot["postgres_query_total"] == 1
    assert snapshot["postgres_slow_query_total"] == 1
    assert "slow Postgres query observed" in caplog.text


def test_create_runtime_rejects_durable_background_execution_without_postgres(
    monkeypatch, tmp_path
):
    settings = _make_settings(
        tmp_path,
        database_uri=None,
        trajectory_enabled=False,
    )
    settings.background_job_execution = "durable"

    with pytest.raises(ValueError, match="BACKGROUND_JOB_EXECUTION=durable"):
        runtime_mod.create_runtime(settings)


def test_create_runtime_ensures_runtime_directories(monkeypatch, tmp_path):
    def fake_build_tool_registry(*, settings, skill_registry, store=None, checkpointer=None):
        return {"store": store, "checkpointer": checkpointer}

    class _FakeLocalSaver:
        def __init__(self, path: Path):
            self.path = Path(path)

    class _FakeLocalStore:
        def __init__(self, path: Path):
            self.path = Path(path)

    class _FakeInMemoryBranchRepository:
        instances: list[_FakeInMemoryBranchRepository] = []

        def __init__(self):
            self.__class__.instances.append(self)

    class _FakeInMemoryAgentTeamRepository:
        instances: list[_FakeInMemoryAgentTeamRepository] = []

        def __init__(self):
            self.__class__.instances.append(self)

    class _FakeInMemoryUserRepository:
        instances: list[_FakeInMemoryUserRepository] = []

        def __init__(self):
            self.__class__.instances.append(self)

    _patch_runtime_collaborators(monkeypatch, build_tool_registry=fake_build_tool_registry)
    monkeypatch.setattr(runtime_mod, "PersistentInMemorySaver", _FakeLocalSaver)
    monkeypatch.setattr(runtime_mod, "PersistentInMemoryStore", _FakeLocalStore)
    monkeypatch.setattr(runtime_mod, "InMemoryBranchRepository", _FakeInMemoryBranchRepository)
    monkeypatch.setattr(
        runtime_mod, "InMemoryAgentTeamRepository", _FakeInMemoryAgentTeamRepository
    )
    monkeypatch.setattr(runtime_mod, "InMemoryUserRepository", _FakeInMemoryUserRepository)

    branch_db_path = tmp_path / "runtime" / "db" / "branches.sqlite3"
    artifact_dir = tmp_path / "runtime" / "artifacts"
    settings = Settings(
        branch_db_path=str(branch_db_path),
        artifact_dir=str(artifact_dir),
        local_checkpoint_path=str(tmp_path / "runtime" / "checkpoints.pkl"),
        local_store_path=str(tmp_path / "runtime" / "store.pkl"),
    )

    assert not branch_db_path.parent.exists()
    assert not artifact_dir.exists()
    runtime = runtime_mod.create_runtime(settings)
    try:
        assert branch_db_path.parent.is_dir()
        assert artifact_dir.is_dir()
    finally:
        runtime.close()


def test_runtime_reexports_directory_helper() -> None:
    assert runtime_mod.ensure_runtime_directories is ensure_runtime_directories


def test_create_runtime_skips_trajectory_repo_when_disabled(monkeypatch, tmp_path):
    def fake_build_tool_registry(
        *,
        settings,
        skill_registry,
        store=None,
        checkpointer=None,
        artifact_metadata_repository=None,
    ):
        return {"artifact_metadata_repository": artifact_metadata_repository}

    fake_modules = _install_postgres_modules(monkeypatch)
    _patch_runtime_collaborators(monkeypatch, build_tool_registry=fake_build_tool_registry)

    runtime = runtime_mod.create_runtime(
        _make_settings(
            tmp_path,
            database_uri="postgresql://focus-agent.test/runtime",
            trajectory_enabled=False,
        )
    )
    try:
        assert runtime.trajectory_recorder is None
        assert fake_modules["trajectory_repo"].instances == []
    finally:
        runtime.close()
