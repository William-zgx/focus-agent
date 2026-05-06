from __future__ import annotations

import logging
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from langchain.tools import tool

import focus_agent.engine.runtime as runtime_mod
from focus_agent.config import Settings, ToolCatalogConfig, ensure_runtime_directories
from focus_agent.config_parts.catalogs import ToolProviderConfig
from focus_agent.services.coordination import (
    InMemoryBackgroundJobDeduperBackend,
    InMemoryThreadTurnLockBackend,
    PostgresBackgroundJobDeduperBackend,
    PostgresThreadTurnLockBackend,
)


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
        instances: list["_Component"] = []

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
    trajectory_repo_cls = _make_postgres_component(with_factory=False)
    agent_team_repo_cls = _make_postgres_component(with_factory=False)
    user_repo_cls = _make_postgres_component(with_factory=False)

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
    trajectory_module = types.ModuleType("focus_agent.repositories.postgres_trajectory_repository")
    trajectory_module.PostgresTrajectoryRepository = trajectory_repo_cls
    agent_team_module = types.ModuleType("focus_agent.repositories.postgres_agent_team_repository")
    agent_team_module.PostgresAgentTeamRepository = agent_team_repo_cls
    user_module = types.ModuleType("focus_agent.repositories.postgres_user_repository")
    user_module.PostgresUserRepository = user_repo_cls

    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.postgres", checkpoint_module)
    monkeypatch.setitem(sys.modules, "langgraph.store.postgres", store_module)
    monkeypatch.setitem(sys.modules, "focus_agent.repositories.postgres_branch_repository", branch_module)
    monkeypatch.setitem(sys.modules, "focus_agent.repositories.artifact_metadata_repository", artifact_module)
    monkeypatch.setitem(sys.modules, "focus_agent.repositories.postgres_memory_repository", memory_module)
    monkeypatch.setitem(sys.modules, "focus_agent.repositories.postgres_trajectory_repository", trajectory_module)
    monkeypatch.setitem(sys.modules, "focus_agent.repositories.postgres_agent_team_repository", agent_team_module)
    monkeypatch.setitem(sys.modules, "focus_agent.repositories.postgres_user_repository", user_module)

    return {
        "saver": saver_cls,
        "store": store_cls,
        "branch_repo": branch_repo_cls,
        "artifact_repo": artifact_repo_cls,
        "memory_repo": memory_repo_cls,
        "trajectory_repo": trajectory_repo_cls,
        "agent_team_repo": agent_team_repo_cls,
        "user_repo": user_repo_cls,
    }


def _patch_runtime_collaborators(monkeypatch, *, build_tool_registry):
    monkeypatch.setattr(runtime_mod, "MemoryPolicy", _FakeMemoryPolicy)
    monkeypatch.setattr(runtime_mod, "MemoryRetriever", _FakeMemoryComponent)
    monkeypatch.setattr(runtime_mod, "MemoryWriter", _FakeMemoryComponent)
    monkeypatch.setattr(runtime_mod, "MemoryExtractor", _FakeMemoryExtractor)
    monkeypatch.setattr(runtime_mod, "SkillRegistry", _FakeSkillRegistry)
    monkeypatch.setattr(runtime_mod, "build_graph", lambda **kwargs: {"graph": kwargs})
    monkeypatch.setattr(runtime_mod, "BranchService", _FakeBranchService)
    monkeypatch.setattr(runtime_mod, "build_tool_registry", build_tool_registry)


def _make_settings(tmp_path: Path, *, database_uri: str | None, trajectory_enabled: bool | None) -> Settings:
    return Settings(
        database_uri=database_uri,
        branch_db_path=str(tmp_path / "branches.sqlite3"),
        artifact_dir=str(tmp_path / "artifacts"),
        local_checkpoint_path=str(tmp_path / "langgraph-checkpoints.pkl"),
        local_store_path=str(tmp_path / "langgraph-store.pkl"),
        trajectory_enabled=trajectory_enabled,
    )


def test_create_runtime_selects_postgres_primary_and_forwards_artifact_repo(monkeypatch, tmp_path, caplog):
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

        assert runtime.checkpointer is saver
        assert runtime.store is store
        assert runtime.repo is repo
        assert runtime.user_repository is user_repo
        assert runtime.memory_repository is memory_repo
        assert runtime.artifact_metadata_repository is artifact_repo
        assert runtime.trajectory_recorder is trajectory_repo
        assert runtime.agent_team_service.repository is agent_team_repo
        assert runtime.user_service.repository is user_repo
        assert isinstance(runtime.coordination_backend.thread_turns, PostgresThreadTurnLockBackend)
        assert isinstance(runtime.coordination_backend.job_deduper, InMemoryBackgroundJobDeduperBackend)
        assert saver.setup_calls == 1
        assert store.setup_calls == 1
        assert repo.setup_calls == 1
        assert artifact_repo.setup_calls == 1
        assert memory_repo.setup_calls == 1
        assert trajectory_repo.setup_calls == 1
        assert agent_team_repo.setup_calls == 1
        assert user_repo.setup_calls == 1
        assert captured["artifact_metadata_repository"] is artifact_repo
        assert captured["memory_repository"] is memory_repo
        assert runtime.memory_retriever.kwargs["repository"] is memory_repo
        assert runtime.memory_writer.kwargs["repository"] is memory_repo
        assert "postgres-primary" in caplog.text
    finally:
        runtime.close()


def test_create_runtime_keeps_local_fallback_when_database_uri_is_missing(monkeypatch, tmp_path, caplog):
    captured: dict[str, object] = {}

    def fake_build_tool_registry(*, settings, skill_registry, store=None, checkpointer=None):
        captured["settings"] = settings
        captured["skill_registry"] = skill_registry
        captured["store"] = store
        captured["checkpointer"] = checkpointer
        return {"tool_registry": True}

    class _FakeLocalSaver:
        def __init__(self, path: Path):
            self.path = Path(path)

    class _FakeLocalStore:
        def __init__(self, path: Path):
            self.path = Path(path)

    class _FakeSQLiteBranchRepository:
        def __init__(self, path: str):
            self.path = path

    class _FakeSQLiteAgentTeamRepository:
        def __init__(self, path: str):
            self.path = path

    class _FakeSQLiteUserRepository:
        def __init__(self, path: str):
            self.path = path

    _patch_runtime_collaborators(monkeypatch, build_tool_registry=fake_build_tool_registry)
    monkeypatch.setattr(runtime_mod, "PersistentInMemorySaver", _FakeLocalSaver)
    monkeypatch.setattr(runtime_mod, "PersistentInMemoryStore", _FakeLocalStore)
    monkeypatch.setattr(runtime_mod, "SQLiteBranchRepository", _FakeSQLiteBranchRepository)
    monkeypatch.setattr(runtime_mod, "SQLiteAgentTeamRepository", _FakeSQLiteAgentTeamRepository)
    monkeypatch.setattr(runtime_mod, "SQLiteUserRepository", _FakeSQLiteUserRepository)
    caplog.set_level(logging.INFO, logger="focus_agent.runtime")

    settings = _make_settings(tmp_path, database_uri=None, trajectory_enabled=None)
    runtime = runtime_mod.create_runtime(settings)
    try:
        assert runtime.checkpointer.path == tmp_path / "langgraph-checkpoints.pkl"
        assert runtime.store.path == tmp_path / "langgraph-store.pkl"
        assert runtime.repo.path == str(tmp_path / "branches.sqlite3")
        assert runtime.user_repository.path == str(tmp_path / "branches.sqlite3")
        assert runtime.agent_team_service.repository.path == str(tmp_path / "branches.sqlite3")
        assert runtime.user_service.repository.path == str(tmp_path / "branches.sqlite3")
        assert runtime.trajectory_recorder is None
        assert runtime.artifact_metadata_repository is None
        assert runtime.memory_repository is None
        assert isinstance(runtime.coordination_backend.thread_turns, InMemoryThreadTurnLockBackend)
        assert isinstance(runtime.coordination_backend.job_deduper, InMemoryBackgroundJobDeduperBackend)
        assert captured["store"] is runtime.store
        assert captured["checkpointer"] is runtime.checkpointer
        assert "local-fallback" in caplog.text
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

    class _FakeSQLiteBranchRepository:
        def __init__(self, path: str):
            self.path = path

    class _FakeSQLiteAgentTeamRepository:
        def __init__(self, path: str):
            self.path = path

    class _FakeSQLiteUserRepository:
        def __init__(self, path: str):
            self.path = path

    monkeypatch.setattr(
        "focus_agent.capabilities.tool_registry.get_default_tools",
        fake_get_default_tools,
    )
    _patch_runtime_collaborators(monkeypatch, build_tool_registry=runtime_mod.build_tool_registry)
    monkeypatch.setattr(runtime_mod, "PersistentInMemorySaver", _FakeLocalSaver)
    monkeypatch.setattr(runtime_mod, "PersistentInMemoryStore", _FakeLocalStore)
    monkeypatch.setattr(runtime_mod, "SQLiteBranchRepository", _FakeSQLiteBranchRepository)
    monkeypatch.setattr(runtime_mod, "SQLiteAgentTeamRepository", _FakeSQLiteAgentTeamRepository)
    monkeypatch.setattr(runtime_mod, "SQLiteUserRepository", _FakeSQLiteUserRepository)

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
        assert isinstance(runtime.coordination_backend.job_deduper, PostgresBackgroundJobDeduperBackend)
        assert runtime.coordination_backend.job_deduper.claim_ttl_seconds == 12.0
    finally:
        runtime.close()


def test_create_runtime_rejects_durable_background_execution_without_postgres(monkeypatch, tmp_path):
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

    class _FakeSQLiteBranchRepository:
        def __init__(self, path: str):
            self.path = path

    class _FakeSQLiteAgentTeamRepository:
        def __init__(self, path: str):
            self.path = path

    class _FakeSQLiteUserRepository:
        def __init__(self, path: str):
            self.path = path

    _patch_runtime_collaborators(monkeypatch, build_tool_registry=fake_build_tool_registry)
    monkeypatch.setattr(runtime_mod, "PersistentInMemorySaver", _FakeLocalSaver)
    monkeypatch.setattr(runtime_mod, "PersistentInMemoryStore", _FakeLocalStore)
    monkeypatch.setattr(runtime_mod, "SQLiteBranchRepository", _FakeSQLiteBranchRepository)
    monkeypatch.setattr(runtime_mod, "SQLiteAgentTeamRepository", _FakeSQLiteAgentTeamRepository)
    monkeypatch.setattr(runtime_mod, "SQLiteUserRepository", _FakeSQLiteUserRepository)

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
