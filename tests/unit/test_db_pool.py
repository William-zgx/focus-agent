from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

from psycopg.rows import dict_row as dict_row_factory

from focus_agent.api.route_utils.readiness import _build_runtime_readiness
from focus_agent.config import Settings
from focus_agent.config_parts.runtime import load_runtime_config
from focus_agent.engine.runtime import _create_postgres_connection_provider
from focus_agent.repositories.postgres_branch_repository import PostgresBranchRepository
from focus_agent.storage.postgres import PostgresConnectionProvider


def test_focus_agent_db_pool_env_controls_legacy_pool_settings() -> None:
    defaults = Settings()

    values = load_runtime_config(
        {
            "FOCUS_AGENT_DB_POOL_ENABLED": "false",
            "FOCUS_AGENT_DB_POOL_MAX": "13",
        },
        defaults,
        model_catalog=defaults.model_catalog,
        tool_catalog=defaults.tool_catalog,
    )

    assert values["db_pool_enabled"] is False
    assert values["postgres_pool_enabled"] is False
    assert values["db_pool_max"] == 13
    assert values["postgres_pool_max_size"] == 13


def test_runtime_provider_defaults_to_shared_pool_size_contract() -> None:
    settings = Settings(database_uri="postgresql://focus-agent.test/runtime")
    provider = _create_postgres_connection_provider(settings)

    assert provider is not None
    assert provider.pool_enabled is True
    assert provider.min_size == 2
    assert provider.max_size == 20

    settings.db_pool_max = 9
    resized = _create_postgres_connection_provider(settings)
    assert resized is not None
    assert resized.max_size == 9


def test_repository_cursor_uses_shared_provider_dict_row_factory() -> None:
    cursor = object()

    class FakeCursorContext:
        def __enter__(self) -> object:
            return cursor

        def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

    class FakeConnection:
        def cursor(self) -> FakeCursorContext:
            return FakeCursorContext()

    class FakeProvider:
        def __init__(self) -> None:
            self.row_factories: list[object | None] = []

        @contextmanager
        def connect(self, *, row_factory: object | None = None) -> Any:
            self.row_factories.append(row_factory)
            yield FakeConnection()

    provider = FakeProvider()
    repo = PostgresBranchRepository(
        "postgresql://focus-agent.test/runtime",
        connection_provider=provider,  # type: ignore[arg-type]
    )

    with repo._cursor(dict_row=True) as cur:
        assert cur is cursor

    assert provider.row_factories == [dict_row_factory]


def test_disabled_provider_uses_direct_short_connection_fallback(monkeypatch) -> None:
    calls: list[tuple[str, object | None]] = []

    class FakeConnection:
        def __enter__(self) -> FakeConnection:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

    def fake_connect(uri: str, *, row_factory: object | None = None) -> FakeConnection:
        calls.append((uri, row_factory))
        return FakeConnection()

    monkeypatch.setattr("focus_agent.storage.postgres.psycopg.connect", fake_connect)
    provider = PostgresConnectionProvider(
        "postgresql://focus-agent.test/runtime",
        pool_enabled=False,
    )

    with provider.connect(row_factory=dict_row_factory):
        snapshot = provider.snapshot()
        assert snapshot["active_connections"] == 1

    assert calls == [("postgresql://focus-agent.test/runtime", dict_row_factory)]
    snapshot = provider.snapshot()
    assert snapshot["postgres_pool_enabled"] == 0
    assert snapshot["postgres_pool_fallback_direct"] == 1
    assert snapshot["active_connections"] == 0


def test_readyz_exposes_active_connections_from_provider_snapshot() -> None:
    provider = PostgresConnectionProvider(
        "postgresql://focus-agent.test/runtime",
        pool_enabled=False,
    )
    provider._checkout()
    try:
        runtime = SimpleNamespace(
            settings=SimpleNamespace(
                database_uri=None,
                trajectory_enabled=False,
                tracing_enabled=False,
                agent_memory_embedding_enabled=False,
                agent_memory_embedding_backend="disabled",
                agent_memory_vector_search_mode="off",
                background_job_old_pending_seconds=900.0,
                app_version=None,
                app_environment=None,
                deployment_name=None,
            ),
            graph=object(),
            repo=object(),
            branch_service=object(),
            tool_registry=object(),
            skill_registry=object(),
            memory_embedding_service=None,
            memory_embedding_backend_error=None,
            background_work=SimpleNamespace(snapshot=lambda: {}),
            durable_background_worker=None,
            trajectory_recorder=None,
            postgres_connection_provider=provider,
        )

        readiness = _build_runtime_readiness(runtime)

        assert readiness.ready is True
        assert readiness.active_connections == 1
    finally:
        provider._return()
