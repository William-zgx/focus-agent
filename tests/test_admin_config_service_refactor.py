from __future__ import annotations

from types import SimpleNamespace

import pytest

from focus_agent.services import admin_config, admin_config_runtime


def test_admin_config_reexports_runtime_reload_helpers() -> None:
    helpers = (
        "_reload_runtime_skill_registry",
        "_refresh_runtime_skill_registry",
        "_reload_runtime_tool_registry",
        "_reload_runtime_graph",
        "_sync_runtime_graph_dependents",
    )

    for name in helpers:
        assert getattr(admin_config, name) is getattr(admin_config_runtime, name)


def test_runtime_tool_reload_uses_admin_config_patch_seams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRegistry:
        enabled = True

        @classmethod
        def from_settings(cls, settings: object) -> FakeRegistry:
            assert settings == "settings"
            return cls()

    captured: dict[str, object] = {}

    def build_registry(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(tools=("read_file", "search_code"))

    runtime = SimpleNamespace(
        settings="settings",
        skill_registry=None,
        store="store",
        checkpointer="checkpointer",
        artifact_metadata_repository="artifact-metadata",
        artifact_store="artifact-store",
        memory_repository="memory-repository",
        memory_embedding_service="embedding-service",
        productivity_repository="productivity-repository",
    )
    monkeypatch.setattr(admin_config, "SkillRegistry", FakeRegistry)
    monkeypatch.setattr(admin_config, "build_tool_registry", build_registry)

    result = admin_config._reload_runtime_tool_registry(runtime)

    assert result == {"success": True, "count": 2}
    assert isinstance(runtime.skill_registry, FakeRegistry)
    assert captured == {
        "settings": "settings",
        "skill_registry": runtime.skill_registry,
        "store": "store",
        "checkpointer": "checkpointer",
        "artifact_metadata_repository": "artifact-metadata",
        "artifact_store": "artifact-store",
        "memory_repository": "memory-repository",
        "memory_embedding_service": "embedding-service",
        "productivity_repository": "productivity-repository",
    }


def test_runtime_skill_refresh_fallback_uses_reexported_reload_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = SimpleNamespace(skill_registry=None)
    expected = {"success": True, "count": 3}
    monkeypatch.setattr(
        admin_config,
        "_reload_runtime_skill_registry",
        lambda value: expected if value is runtime else {},
    )

    assert admin_config._refresh_runtime_skill_registry(runtime) is expected


def test_sync_runtime_graph_dependents_updates_existing_graph_consumers() -> None:
    graph = object()
    branch_service = SimpleNamespace(graph=None)
    decision_service = SimpleNamespace(graph=None)
    runtime = SimpleNamespace(
        graph=graph,
        branch_service=branch_service,
        branch_decision_service=decision_service,
    )

    admin_config._sync_runtime_graph_dependents(runtime)

    assert branch_service.graph is graph
    assert decision_service.graph is graph
