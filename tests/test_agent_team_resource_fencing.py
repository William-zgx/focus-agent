from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from focus_agent.multi_agent.contracts import LockMode
from focus_agent.multi_agent.resource_lock import (
    InMemoryResourceLockManager,
    PostgresResourceLockManager,
)


def _acquire(
    manager: InMemoryResourceLockManager,
    *,
    agent_id: str,
    session_id: str,
    tenant_id: str | None = None,
    resource_namespace: str | None = None,
    fence_token: int | None = None,
):
    return manager.try_acquire(
        resource_id="file:src/shared.py",
        agent_id=agent_id,
        session_id=session_id,
        mode=LockMode.EXCLUSIVE,
        ttl_seconds=30,
        tenant_id=tenant_id,
        resource_namespace=resource_namespace,
        fence_token=fence_token,
    )


def test_default_resource_locks_remain_session_scoped_without_fence_token() -> None:
    manager = InMemoryResourceLockManager()

    first = _acquire(manager, agent_id="agent:a", session_id="session:a")
    second = _acquire(manager, agent_id="agent:b", session_id="session:b")

    assert first is not None
    assert second is not None
    assert first.is_cross_session is False
    assert first.fence_token is None
    assert second.fence_token is None


def test_cross_session_fencing_lock_conflicts_on_same_canonical_key() -> None:
    manager = InMemoryResourceLockManager()

    first = _acquire(
        manager,
        agent_id="agent:a",
        session_id="session:a",
        tenant_id="tenant:a",
        resource_namespace="repo:focus-agent",
    )
    blocked = _acquire(
        manager,
        agent_id="agent:a",
        session_id="session:b",
        tenant_id="tenant:a",
        resource_namespace="repo:focus-agent",
    )
    independent = _acquire(
        manager,
        agent_id="agent:c",
        session_id="session:b",
        tenant_id="tenant:b",
        resource_namespace="repo:focus-agent",
    )

    assert first is not None
    assert first.is_cross_session is True
    assert first.canonical_resource_key is not None
    assert first.fence_token == 1
    assert blocked is None
    assert independent is not None
    assert independent.fence_token == 1


def test_fence_token_request_alone_enables_global_lock_and_tokens_are_monotonic() -> None:
    manager = InMemoryResourceLockManager()

    first = _acquire(
        manager,
        agent_id="agent:a",
        session_id="session:a",
        fence_token=7,
    )
    assert first is not None
    assert first.fence_token == 7
    manager.release(first)

    second = _acquire(
        manager,
        agent_id="agent:b",
        session_id="session:b",
        fence_token=3,
    )

    assert second is not None
    assert second.fence_token == 8


class _Cursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[object, ...] | None]] = []

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[dict[str, object]]:
        return []

    def fetchone(self) -> dict[str, object]:
        return {"fence_token": 42}

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self.cursor_instance = cursor

    @contextmanager
    def cursor(self) -> Iterator[_Cursor]:
        yield self.cursor_instance

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_postgres_cross_session_fencing_uses_existing_schema_columns(monkeypatch) -> None:
    cursor = _Cursor()
    manager = PostgresResourceLockManager("postgresql://unit-test")
    monkeypatch.setattr(manager, "_connect", lambda: _Connection(cursor))

    claim = manager.try_acquire(
        resource_id="file:src/shared.py",
        agent_id="agent:a",
        session_id="session:a",
        mode=LockMode.EXCLUSIVE,
        ttl_seconds=30,
        tenant_id="tenant:a",
        resource_namespace="repo:focus-agent",
    )

    assert claim is not None
    assert claim.fence_token == 42
    assert claim.canonical_resource_key is not None
    select_sql, select_params = cursor.executed[2]
    assert "WHERE resource_id = %s" in select_sql
    assert "session_id = %s" not in select_sql
    assert select_params == (claim.canonical_resource_key,)
    assert cursor.executed[3][0] == "SELECT txid_current() AS fence_token"
    insert_sql, insert_params = cursor.executed[4]
    assert "INSERT INTO agent_resource_claims" in insert_sql
    assert insert_params is not None
    assert insert_params[1] == "session:a"
    assert insert_params[2] == claim.canonical_resource_key
