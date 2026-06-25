from __future__ import annotations

import math
from types import SimpleNamespace

import httpx
import pytest

import focus_agent.memory.embedding_providers as embedding_providers_mod
from focus_agent.api.route_utils.readiness import _build_runtime_readiness
from focus_agent.config import Settings
from focus_agent.config_parts.agent import load_agent_config
from focus_agent.memory.embedding import (
    DeterministicTestEmbeddingProvider,
    EmbeddingProviderConfigError,
    OllamaEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    create_memory_embedding_provider,
)
from focus_agent.memory.embedding_service import MemoryEmbeddingService


class _FakeEmbeddingHttpClient:
    def __init__(self, handler):
        self._handler = handler

    def post(
        self,
        url: str,
        *,
        json: object | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        return self._response(self._handler("POST", url, json, headers or {}, timeout), url=url)

    def get(self, url: str, *, timeout: float | None = None) -> httpx.Response:
        return self._response(self._handler("GET", url, None, {}, timeout), url=url)

    @staticmethod
    def _response(payload: object, *, url: str) -> httpx.Response:
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))


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
    assert (
        create_memory_embedding_provider(
            Settings(
                agent_memory_embedding_enabled=False,
                agent_memory_embedding_backend="disabled",
            )
        )
        is None
    )

    provider = create_memory_embedding_provider(
        Settings(
            agent_memory_embedding_backend="deterministic_test",
            agent_memory_embedding_dimensions=4,
        )
    )

    assert provider is not None
    assert provider.provider_id == "deterministic_test"
    assert len(provider.embed_query("hello")) == 4


def test_memory_embedding_defaults_to_openai_compatible_and_inherits_model_provider_client_config() -> (
    None
):
    provider = create_memory_embedding_provider(
        Settings(
            agent_memory_embedding_backend="openai_compatible",
            resolved_env={
                "OPENAI_BASE_URL": "https://models.example.test/v1",
                "OPENAI_API_KEY": "model-secret",
            },
        )
    )

    assert isinstance(provider, OpenAICompatibleEmbeddingProvider)
    assert provider.provider_id == "openai_compatible"
    assert provider.base_url == "https://models.example.test/v1"
    assert provider.api_key == "model-secret"


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
            "AGENT_RETRIEVAL_BACKEND": "zvec",
            "AGENT_RETRIEVAL_FALLBACK_BACKEND": "postgres",
            "AGENT_ZVEC_ENABLED": "true",
            "AGENT_ZVEC_DATA_DIR": "/tmp/focus-zvec",
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
    assert values["agent_retrieval_backend"] == "zvec"
    assert values["agent_retrieval_fallback_backend"] == "postgres"
    assert values["agent_zvec_enabled"] is True
    assert values["agent_zvec_data_dir"] == "/tmp/focus-zvec"


def test_memory_embedding_config_defaults_to_auto_ollama_route() -> None:
    values = load_agent_config({}, Settings())

    assert values["agent_memory_embedding_backend"] == "auto"
    assert values["agent_memory_embedding_model"] == "embeddinggemma"
    assert values["agent_memory_embedding_dimensions"] == 768


def test_memory_embedding_config_enabled_false_disables_backend_by_default() -> None:
    values = load_agent_config({"AGENT_MEMORY_EMBEDDING_ENABLED": "false"}, Settings())

    assert values["agent_memory_embedding_enabled"] is False
    assert values["agent_memory_embedding_backend"] == "disabled"


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
    del monkeypatch
    captured: dict[str, object] = {}

    def handler(method, url, payload, headers, timeout):
        captured["method"] = method
        captured["url"] = url
        captured["timeout"] = timeout
        captured["authorization"] = headers["Authorization"]
        captured["payload"] = payload
        return {
            "data": [
                {"index": 1, "embedding": [0.3, 0.4]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        }

    provider = OpenAICompatibleEmbeddingProvider(
        model_id="embed-small",
        base_url="https://embeddings.example.test/v1/",
        api_key="secret",
        dimensions=2,
        timeout_seconds=8.0,
        http_client=_FakeEmbeddingHttpClient(handler),
    )

    vectors = provider.embed_texts(["alpha", "beta"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["method"] == "POST"
    assert captured["url"] == "https://embeddings.example.test/v1/embeddings"
    assert captured["timeout"] == 8.0
    assert captured["authorization"] == "Bearer secret"
    assert captured["payload"] == {
        "model": "embed-small",
        "input": ["alpha", "beta"],
        "dimensions": 2,
    }


def test_auto_embedding_provider_prefers_available_ollama_embeddinggemma(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def handler(method, url, payload, headers, timeout):
        del headers
        captured.setdefault("urls", []).append(url)
        captured.setdefault("methods", []).append(method)
        captured["timeout"] = timeout
        if url == "http://ollama.example.test/api/tags":
            return {"models": [{"name": "embeddinggemma:latest"}]}
        captured["embed_payload"] = payload
        return {
            "embeddings": [
                [1.0, *([0.0] * 767)],
                [0.0, 1.0, *([0.0] * 766)],
            ]
        }

    monkeypatch.setattr(
        embedding_providers_mod,
        "shared_sync_http_client",
        lambda: _FakeEmbeddingHttpClient(handler),
    )

    provider = create_memory_embedding_provider(
        Settings(
            agent_memory_embedding_backend="auto",
            agent_memory_embedding_base_url="http://ollama.example.test/v1",
        )
    )

    assert isinstance(provider, OllamaEmbeddingProvider)
    assert provider.provider_id == "ollama"
    assert provider.model_id == "embeddinggemma"
    assert provider.dimensions == 768
    assert provider.base_url == "http://ollama.example.test"

    vectors = provider.embed_texts(["alpha", "beta"])

    assert [len(vector) for vector in vectors] == [768, 768]
    assert captured["urls"] == [
        "http://ollama.example.test/api/tags",
        "http://ollama.example.test/api/embed",
    ]
    assert captured["methods"] == ["GET", "POST"]
    assert captured["timeout"] == 30.0
    assert captured["embed_payload"] == {
        "model": "embeddinggemma",
        "input": ["alpha", "beta"],
    }


def test_auto_embedding_provider_reports_ollama_install_hint_when_no_backend_available(
    monkeypatch,
) -> None:
    def handler(method, url, payload, headers, timeout):
        del payload, headers, timeout
        assert method == "GET"
        assert url == "http://ollama.example.test/api/tags"
        return {"models": [{"name": "llama3.2:latest"}]}

    monkeypatch.setattr(
        embedding_providers_mod,
        "shared_sync_http_client",
        lambda: _FakeEmbeddingHttpClient(handler),
    )

    settings = Settings(
        model="unknown-provider:missing",
        agent_memory_embedding_backend="auto",
        agent_memory_embedding_base_url="http://ollama.example.test",
        agent_memory_embedding_api_key_env="",
        agent_memory_embedding_api_key="",
    )
    with pytest.raises(EmbeddingProviderConfigError, match="ollama pull embeddinggemma"):
        create_memory_embedding_provider(settings)


def test_auto_embedding_provider_does_not_inherit_chat_credentials_as_cloud_fallback(
    monkeypatch,
) -> None:
    def handler(method, url, payload, headers, timeout):
        del payload, headers, timeout
        assert method == "GET"
        assert url == "http://ollama.example.test/api/tags"
        return {"models": []}

    monkeypatch.setattr(
        embedding_providers_mod,
        "shared_sync_http_client",
        lambda: _FakeEmbeddingHttpClient(handler),
    )

    settings = Settings(
        agent_memory_embedding_backend="auto",
        agent_memory_embedding_base_url="http://ollama.example.test",
        resolved_env={
            "OPENAI_BASE_URL": "https://chat-models.example.test/v1",
            "OPENAI_API_KEY": "chat-model-secret",
        },
    )

    with pytest.raises(EmbeddingProviderConfigError, match="ollama pull embeddinggemma"):
        create_memory_embedding_provider(settings)


def test_auto_embedding_provider_uses_explicit_openai_compatible_fallback(
    monkeypatch,
) -> None:
    def handler(method, url, payload, headers, timeout):
        del payload, headers, timeout
        assert method == "GET"
        assert url == "http://127.0.0.1:11434/api/tags"
        return {"models": []}

    monkeypatch.setattr(
        embedding_providers_mod,
        "shared_sync_http_client",
        lambda: _FakeEmbeddingHttpClient(handler),
    )

    provider = create_memory_embedding_provider(
        Settings(
            agent_memory_embedding_backend="auto",
            agent_memory_embedding_api_key="direct-secret",
            agent_memory_embedding_api_key_env="",
        )
    )

    assert isinstance(provider, OpenAICompatibleEmbeddingProvider)
    assert provider.model_id == "text-embedding-3-small"
    assert provider.dimensions == 1536


def test_explicit_openai_compatible_backend_does_not_probe_ollama(monkeypatch) -> None:
    def fail_http_client():
        raise AssertionError("explicit openai_compatible backend should not probe Ollama")

    monkeypatch.setattr(embedding_providers_mod, "shared_sync_http_client", fail_http_client)

    provider = create_memory_embedding_provider(
        Settings(
            agent_memory_embedding_backend="openai_compatible",
            agent_memory_embedding_api_key="direct-secret",
            agent_memory_embedding_api_key_env="",
        )
    )

    assert isinstance(provider, OpenAICompatibleEmbeddingProvider)


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
        def inspect_pgvector_support(
            self, *, dimensions: int, vector_index: bool
        ) -> dict[str, object]:
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


def test_readiness_reports_auto_selected_embedding_provider_metadata() -> None:
    class _Provider:
        provider_id = "ollama"
        model_id = "embeddinggemma"
        dimensions = 768

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] * self.dimensions for _ in texts]

    class _Repository:
        def inspect_pgvector_support(
            self, *, dimensions: int, vector_index: bool
        ) -> dict[str, object]:
            return {
                "extension_installed": True,
                "extension_version": "0.8.0",
                "embeddings_table_exists": True,
                "embedding_column_type": f"vector({dimensions})",
                "dimensions_match": True,
                "vector_index_exists": vector_index,
            }

    settings = Settings(
        database_uri="postgresql://focus-agent.test/readiness",
        agent_memory_embedding_backend="auto",
    )
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
            provider=_Provider(),
        ),
        memory_embedding_backend_error=None,
        otel_runtime=None,
        trajectory_recorder=None,
    )

    readiness = _build_runtime_readiness(runtime)
    check = next(item for item in readiness.checks if item.name == "memory_embedding_backend")

    assert check.ready is True
    assert "auto_selected=ollama" in check.detail
    assert "model=embeddinggemma" in check.detail
    assert "dimensions=768" in check.detail


def test_readiness_reports_zvec_fallback_without_failing_readyz() -> None:
    runtime = SimpleNamespace(
        settings=Settings(agent_retrieval_backend="zvec", agent_retrieval_fallback_backend="postgres"),
        graph=object(),
        repo=object(),
        branch_service=object(),
        tool_registry=object(),
        skill_registry=object(),
        memory_repository=None,
        memory_embedding_service=None,
        memory_embedding_backend_error=None,
        retrieval_index=None,
        retrieval_index_error="zvec_unavailable: RuntimeError",
        otel_runtime=None,
        trajectory_recorder=None,
    )

    readiness = _build_runtime_readiness(runtime)
    check = next(item for item in readiness.checks if item.name == "retrieval_zvec")

    assert readiness.ready is True
    assert check.ready is True
    assert "fallback=postgres" in check.detail


def test_readiness_degrades_when_configured_pgvector_storage_is_missing() -> None:
    class _Repository:
        def inspect_pgvector_support(
            self, *, dimensions: int, vector_index: bool
        ) -> dict[str, object]:
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
        settings=Settings(
            database_uri="postgresql://focus-agent.test/readiness",
            agent_memory_embedding_backend="openai_compatible",
        ),
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


def test_readiness_reports_ollama_install_hint_when_auto_backend_is_unavailable() -> None:
    runtime = SimpleNamespace(
        settings=Settings(
            database_uri="postgresql://focus-agent.test/readiness",
            agent_memory_embedding_backend="auto",
        ),
        graph=object(),
        repo=object(),
        branch_service=object(),
        tool_registry=object(),
        skill_registry=object(),
        memory_repository=None,
        memory_embedding_service=None,
        memory_embedding_backend_error="ollama model embeddinggemma is not installed",
        otel_runtime=None,
        trajectory_recorder=None,
    )

    readiness = _build_runtime_readiness(runtime)
    check = next(item for item in readiness.checks if item.name == "memory_embedding_backend")

    assert readiness.ready is False
    assert check.ready is False
    assert "install_hint=ollama pull embeddinggemma" in check.detail


def test_readiness_keeps_local_fallback_ready_when_default_embedding_credentials_are_absent() -> (
    None
):
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

    assert readiness.ready is True
    assert check.ready is True
    assert check.detail == "local_fallback: missing embedding credentials"
