from __future__ import annotations

import json

from focus_agent import memory_embedding_cli as cli
from focus_agent.config import Settings


class _Provider:
    provider_id = "ollama"
    model_id = "embeddinggemma"
    dimensions = 768

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimensions for _ in texts]


def test_memory_embedding_doctor_reports_provider_and_pgvector_status(monkeypatch, capsys):
    settings = Settings(database_uri="postgresql://focus-agent.test/memory")
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(cli, "create_memory_embedding_provider", lambda settings: _Provider())

    class _Repository:
        def __init__(self, database_uri: str):
            self.database_uri = database_uri

        def inspect_pgvector_support(self, *, dimensions: int, vector_index: bool):
            return {
                "extension_installed": True,
                "extension_version": "0.8.1",
                "embeddings_table_exists": True,
                "embedding_column_type": f"vector({dimensions})",
                "configured_dimensions": dimensions,
                "dimensions_match": True,
                "vector_index_expected": vector_index,
                "vector_index_exists": False,
            }

    monkeypatch.setattr(cli, "PostgresMemoryRepository", _Repository)

    assert cli.main(["doctor"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["ready"] is True
    assert payload["provider"]["provider_id"] == "ollama"
    assert payload["provider"]["model_id"] == "embeddinggemma"
    assert payload["repository"]["dimensions_match"] is True


def test_memory_embedding_doctor_reports_ollama_install_hint(monkeypatch, capsys):
    settings = Settings(database_uri="")
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: settings))

    def raise_unavailable(settings):  # noqa: ARG001
        from focus_agent.memory.embedding import EmbeddingProviderConfigError

        raise EmbeddingProviderConfigError("ollama model embeddinggemma is not installed")

    monkeypatch.setattr(cli, "create_memory_embedding_provider", raise_unavailable)

    assert cli.main(["doctor"]) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload["ready"] is False
    assert payload["provider"]["install_hint"] == "ollama pull embeddinggemma"
    assert payload["repository"]["reason"] == "DATABASE_URI is not set"


def test_memory_embedding_rebuild_requires_confirm(monkeypatch, capsys):
    settings = Settings(database_uri="postgresql://focus-agent.test/memory")
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(cli, "create_memory_embedding_provider", lambda settings: _Provider())

    assert cli.main(["rebuild"]) == 2
    payload = json.loads(capsys.readouterr().err)

    assert payload["status"] == "refused"
    assert payload["reason"] == "--confirm-delete-index is required"


def test_memory_embedding_rebuild_uses_provider_dimensions(monkeypatch, capsys):
    settings = Settings(database_uri="postgresql://focus-agent.test/memory")
    settings.agent_memory_embedding_dimensions = 1536
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: settings))
    monkeypatch.setattr(cli, "create_memory_embedding_provider", lambda settings: _Provider())

    class _Repository:
        instances: list[_Repository] = []

        def __init__(self, database_uri: str):
            self.database_uri = database_uri
            self.rebuild_kwargs: dict[str, object] = {}
            type(self).instances.append(self)

        def rebuild_embedding_index(self, **kwargs):
            self.rebuild_kwargs = dict(kwargs)
            return {
                "extension_installed": True,
                "embeddings_table_exists": True,
                "dimensions_match": True,
            }

        def list_records(self, query):  # noqa: ARG002
            return []

    monkeypatch.setattr(cli, "PostgresMemoryRepository", _Repository)

    assert cli.main(["rebuild", "--confirm-delete-index"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["ready"] is True
    assert _Repository.instances[0].rebuild_kwargs["dimensions"] == 768
    assert payload["backfill"]["status"] == "skipped"
