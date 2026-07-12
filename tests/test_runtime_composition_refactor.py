from pathlib import Path
from types import SimpleNamespace

import focus_agent.engine.runtime as runtime
from focus_agent.config import Settings
from focus_agent.engine.runtime_types import (
    RuntimeMemoryComponents,
    RuntimePersistence,
)


def _memory_components() -> RuntimeMemoryComponents:
    return RuntimeMemoryComponents(
        memory_policy=object(),
        memory_retriever=object(),
        memory_writer=object(),
        memory_extractor=object(),
        memory_repository=object(),
        memory_embedding_service=SimpleNamespace(provider="embedding-provider"),
        memory_embedding_provider="embedding-provider",
        retrieval_index="retrieval-index",
    )


def _persistence() -> RuntimePersistence:
    return RuntimePersistence(
        checkpointer="checkpointer",
        store="store",
        repo=object(),
        user_repository=object(),
        memory_repository=object(),
        productivity_repository=object(),
        trajectory_recorder=None,
        artifact_metadata_repository="artifact-metadata",
        run_journal=object(),
    )


def test_runtime_registries_use_runtime_compatibility_builder_seam(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _SkillRegistry:
        @staticmethod
        def from_settings(*, settings, retrieval_index=None, embedding_provider=None):
            captured["skill_registry"] = {
                "settings": settings,
                "retrieval_index": retrieval_index,
                "embedding_provider": embedding_provider,
            }
            return "skill-registry"

    def build_tool_registry_compat(**kwargs):
        captured["tool_registry"] = kwargs
        return "tool-registry"

    monkeypatch.setattr(runtime, "SkillRegistry", _SkillRegistry)
    monkeypatch.setattr(runtime, "_build_tool_registry_compat", build_tool_registry_compat)

    registries = runtime._create_runtime_registries(
        settings=Settings(),
        persistence=_persistence(),
        memory=_memory_components(),
    )

    assert registries.skill_registry == "skill-registry"
    assert registries.tool_registry == "tool-registry"
    assert captured["skill_registry"]["retrieval_index"] == "retrieval-index"
    assert captured["skill_registry"]["embedding_provider"] == "embedding-provider"
    assert captured["tool_registry"]["artifact_metadata_repository"] == "artifact-metadata"
    assert captured["tool_registry"]["memory_embedding_service"].provider == "embedding-provider"


def test_runtime_services_use_runtime_factory_and_repository_patch_seams(monkeypatch) -> None:
    class _BranchService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _AgentTeamRepository:
        def __init__(self):
            self.setup_calls = 0

        def setup(self):
            self.setup_calls += 1

    class _AgentTeamService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _UserService:
        def __init__(self, repository, **kwargs):
            self.repository = repository
            self.kwargs = kwargs

    class _BranchDecisionService:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _ProductivityService:
        def __init__(self, repository):
            self.repository = repository

    monkeypatch.setattr(runtime, "BranchService", _BranchService)
    monkeypatch.setattr(runtime, "InMemoryAgentTeamRepository", _AgentTeamRepository)
    monkeypatch.setattr(runtime, "AgentTeamService", _AgentTeamService)
    monkeypatch.setattr(runtime, "UserService", _UserService)
    monkeypatch.setattr(runtime, "BranchDecisionService", _BranchDecisionService)
    monkeypatch.setattr(runtime, "ProductivityService", _ProductivityService)
    coordination_backend = SimpleNamespace()
    user_repository = object()
    productivity_repository = object()

    services = runtime._create_runtime_services(
        settings=Settings(),
        graph="graph",
        repo="branch-repository",
        user_repository=user_repository,
        store="store",
        memory_writer="memory-writer",
        memory_repository=object(),
        productivity_repository=productivity_repository,
        governance_repository="governance-repository",
        memory_embedding_provider="embedding-provider",
        retrieval_index="retrieval-index",
        coordination_backend=coordination_backend,
        background_work="background-work",
    )

    assert services.branch_service.kwargs["repo"] == "branch-repository"
    assert services.branch_service._coordination_backend is coordination_backend
    assert services.agent_team_service.kwargs["repository"].setup_calls == 1
    assert services.agent_team_service.kwargs["branch_service"] is services.branch_service
    assert services.user_service.repository is user_repository
    assert (
        services.branch_decision_service.kwargs["governance_repository"] == "governance-repository"
    )
    assert services.productivity_service.repository is productivity_repository


def test_runtime_module_stays_within_composition_line_budget() -> None:
    runtime_path = Path(runtime.__file__)

    assert len(runtime_path.read_text(encoding="utf-8").splitlines()) <= 690
