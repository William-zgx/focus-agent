from pathlib import Path

import focus_agent.engine.runtime as runtime
import focus_agent.engine.runtime_memory_setup as runtime_memory_setup
from focus_agent.config import Settings


def test_runtime_memory_setup_helpers_remain_compatibly_exported() -> None:
    assert (
        runtime._memory_embedding_schema_dimensions
        is runtime_memory_setup._memory_embedding_schema_dimensions
    )
    assert (
        runtime._setup_memory_repository_if_available
        is runtime_memory_setup._setup_memory_repository_if_available
    )
    assert runtime._memory_embedding_configured is runtime_memory_setup._memory_embedding_configured


def test_runtime_memory_setup_preserves_helper_patch_seams(monkeypatch) -> None:
    provider = type("Provider", (), {"dimensions": 11})()
    monkeypatch.setattr(
        runtime,
        "create_memory_embedding_provider",
        lambda settings: provider,  # noqa: ARG005
    )
    monkeypatch.setattr(
        runtime,
        "_memory_embedding_schema_dimensions",
        lambda settings, *, provider: 13,  # noqa: ARG005
    )
    monkeypatch.setattr(
        runtime,
        "_memory_embedding_configured",
        lambda settings: False,  # noqa: ARG005
    )
    settings = Settings()

    setup = runtime._resolve_memory_embedding_setup(settings)

    assert setup.provider is provider
    assert setup.dimensions == 13
    assert setup.memory_embeddings_enabled is False
    assert settings.agent_memory_embedding_dimensions == 13


def test_runtime_module_stays_within_refactor_line_budget() -> None:
    runtime_path = Path(runtime.__file__)

    assert len(runtime_path.read_text(encoding="utf-8").splitlines()) <= 780
