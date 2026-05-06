from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest

from focus_agent.api.route_utils.readiness import _build_runtime_readiness
from focus_agent.config import Settings
from focus_agent.config_parts.agent import load_agent_config
import focus_agent.memory.embedding as embedding_mod
from focus_agent.memory.embedding import (
    DeterministicTestEmbeddingProvider,
    EmbeddingProviderConfigError,
    OpenAICompatibleEmbeddingProvider,
    create_memory_embedding_provider,
)
from focus_agent.memory.embedding_service import MemoryEmbeddingService


class _FakeEmbeddingResponse:
    def __init__(self, payload: object):
        self.payload = payload

    def __enter__(self) -> "_FakeEmbeddingResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_deterministic_embedding_provider_returns_stable_unit_vectors() -> None:
    provider = DeterministicTestEmbeddingProvider(dimensions=6)

    first = provider.embed_texts(["same text"])[0]
    second = provider.embed_texts(["same text"])[0]
    different = provider.embed_texts(["different text"])[0]

    assert first == second
    assert first != different
    assert len(first) == 6
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0)


def test_memory_embedding_service_factory_supports_disabled_and_deterministic_backends() -> None:
    assert create_memory_embedding_provider(Settings()) is None

    provider = create_memory_embedding_provider(
        Settings(
            agent_memory_embedding_backend="deterministic_test",
            agent_memory_embedding_dimensions=4,
        )
    )

    assert provider is not None
    assert provider.provider_id == "deterministic_test"
    assert len(provider.embed_query("hello")) == 4


def test_memory_embedding_config_loads_agent_env_overrides() -> None:
    values = load_agent_config(
        {
            "AGENT_MEMORY_EMBEDDING_BACKEND": "deterministic-test",
            "AGENT_MEMORY_EMBEDDING_MODEL": "embed-small",
            "AGENT_MEMORY_EMBEDDING_BASE_URL": "https://embeddings.example.test/v1",
            "AGENT_MEMORY_EMBEDDING_API_KEY_ENV": "",
            "AGENT_MEMORY_EMBEDDING_API_KEY": "direct-secret",
            "AGENT_MEMORY_EMBEDDING_DIMENSIONS": "32",
            "AGENT_MEMORY_PGVECTOR_EXTENSION_MODE": "require-installed",
            "AGENT_MEMORY_EMBEDDING_TIMEOUT_SECONDS": "4.5",
        },
        Settings(),
    )

    assert values["agent_memory_embedding_backend"] == "deterministic_test"
    assert values["agent_memory_embedding_model"] == "embed-small"
    assert values["agent_memory_embedding_base_url"] == "https://embeddings.example.test/v1"
    assert values["agent_memory_embedding_api_key_env"] is None
    assert values["agent_memory_embedding_api_key"] == "direct-secret"
    assert values["agent_memory_embedding_dimensions"] == 32
    assert values["agent_memory_pgvector_extension_mode"] == "required"
    assert values["agent_memory_embedding_timeout_seconds"] == 4.5


def test_memory_embedding_config_defaults_pgvector_extension_mode_by_environment() -> None:
    assert (
        load_agent_config({"APP_ENVIRONMENT": "testing"}, Settings())[
            "agent_memory_pgvector_extension_mode"
        ]
        == "auto_create"
    )
    assert (
        load_agent_config({"APP_ENVIRONMENT": "production"}, Settings())[
            "agent_memory_pgvector_extension_mode"
        ]
        == "required"
    )


def test_openai_compatible_embedding_provider_posts_embeddings_request(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeEmbeddingResponse(
            {
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ]
            }
        )

    monkeypatch.setattr(embedding_mod, "urlopen", fake_urlopen)
    provider = OpenAICompatibleEmbeddingProvider(
        model_id="embed-small",
        base_url="https://embeddings.example.test/v1/",
        api_key="secret",
        dimensions=2,
        timeout_seconds=8.0,
    )

    vectors = provider.embed_texts(["alpha", "beta"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["url"] == "https://embeddings.example.test/v1/embeddings"
    assert captured["timeout"] == 8.0
    assert captured["authorization"] == "Bearer secret"
    assert captured["payload"] == {
        "model": "embed-small",
        "input": ["alpha", "beta"],
        "dimensions": 2,
    }


def test_openai_compatible_factory_reports_missing_configured_api_key_env() -> None:
    settings = Settings(
        agent_memory_embedding_backend="openai_compatible",
        agent_memory_embedding_api_key_env="MISSING_EMBEDDING_API_KEY",
        resolved_env={"OTHER_KEY": "value"},
    )

    with pytest.raises(EmbeddingProviderConfigError, match="MISSING_EMBEDDING_API_KEY"):
        create_memory_embedding_provider(settings)


def test_readiness_reports_memory_embedding_backend_ready_and_keeps_trajectory_last() -> None:
    class _Repository:
        def inspect_pgvector_support(self, *, dimensions: int, vector_index: bool) -> dict[str, object]:
            return {
                "extension_installed": True,
                "extension_version": "0.8.0",
                "embeddings_table_exists": True,
                "embedding_column_type": f"vector({dimensions})",
                "dimensions_match": True,
                "vector_index_exists": vector_index,
            }

    settings = Settings(agent_memory_embedding_backend="deterministic_test")
    settings.database_uri = "postgresql://focus-agent.test/readiness"
    settings.trajectory_enabled = False
    runtime = SimpleNamespace(
        settings=settings,
        graph=object(),
        repo=object(),
        branch_service=object(),
        tool_registry=object(),
        skill_registry=object(),
        memory_repository=_Repository(),
        memory_embedding_service=MemoryEmbeddingService(
            repository=object(),
            provider=DeterministicTestEmbeddingProvider(),
        ),
        memory_embedding_backend_error=None,
        otel_runtime=None,
        trajectory_recorder=None,
    )

    readiness = _build_runtime_readiness(runtime)
    checks = {check.name: check for check in readiness.checks}

    assert readiness.ready is True
    assert checks["memory_embedding_backend"].ready is True
    assert checks["memory_embedding_backend"].detail.startswith("deterministic_test: ready")
    assert checks["memory_pgvector"].ready is True
    assert "extension=installed" in checks["memory_pgvector"].detail
    assert readiness.checks[-1].name == "trajectory_recorder"


def test_readiness_degrades_when_configured_pgvector_storage_is_missing() -> None:
    class _Repository:
        def inspect_pgvector_support(self, *, dimensions: int, vector_index: bool) -> dict[str, object]:
            return {
                "extension_installed": False,
                "extension_version": None,
                "embeddings_table_exists": False,
                "embedding_column_type": None,
                "dimensions_match": False,
                "vector_index_exists": False,
            }

    runtime = SimpleNamespace(
        settings=Settings(
            database_uri="postgresql://focus-agent.test/readiness",
            agent_memory_embedding_backend="deterministic_test",
            agent_memory_pgvector_extension_mode="required",
        ),
        graph=object(),
        repo=object(),
        branch_service=object(),
        tool_registry=object(),
        skill_registry=object(),
        memory_repository=_Repository(),
        memory_embedding_service=MemoryEmbeddingService(
            repository=object(),
            provider=DeterministicTestEmbeddingProvider(),
        ),
        memory_embedding_backend_error=None,
        otel_runtime=None,
        trajectory_recorder=None,
    )

    readiness = _build_runtime_readiness(runtime)
    check = next(item for item in readiness.checks if item.name == "memory_pgvector")

    assert readiness.ready is False
    assert readiness.status == "degraded"
    assert check.ready is False
    assert "mode=required" in check.detail
    assert "extension=missing" in check.detail


def test_readiness_degrades_when_configured_memory_embedding_backend_is_unavailable() -> None:
    runtime = SimpleNamespace(
        settings=Settings(agent_memory_embedding_backend="openai_compatible"),
        graph=object(),
        repo=object(),
        branch_service=object(),
        tool_registry=object(),
        skill_registry=object(),
        memory_repository=None,
        memory_embedding_service=None,
        memory_embedding_backend_error="missing embedding credentials",
        otel_runtime=None,
        trajectory_recorder=None,
    )

    readiness = _build_runtime_readiness(runtime)
    check = next(item for item in readiness.checks if item.name == "memory_embedding_backend")

    assert readiness.ready is False
    assert readiness.status == "degraded"
    assert check.ready is False
    assert check.detail == "missing embedding credentials"
