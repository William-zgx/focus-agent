from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row

try:  # pragma: no cover - optional production dependency
    from psycopg_pool import ConnectionPool
except Exception:  # pragma: no cover - exercised when psycopg_pool is absent
    ConnectionPool = None  # type: ignore[assignment]


logger = logging.getLogger("focus_agent.postgres")


@dataclass(slots=True)
class PostgresConnectionProvider:
    database_uri: str
    pool_enabled: bool = True
    min_size: int = 1
    max_size: int = 4
    slow_query_threshold_ms: float = 500.0
    row_factory: Any = dict_row
    _pool: Any | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _opened_total: int = field(default=0, init=False)
    _returned_total: int = field(default=0, init=False)
    _in_use: int = field(default=0, init=False)
    _query_total: int = field(default=0, init=False)
    _query_error_total: int = field(default=0, init=False)
    _slow_query_total: int = field(default=0, init=False)
    _pool_unavailable: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.min_size = max(0, int(self.min_size))
        self.max_size = max(1, int(self.max_size))
        if self.min_size > self.max_size:
            self.min_size = self.max_size
        self.slow_query_threshold_ms = max(0.0, float(self.slow_query_threshold_ms))
        self._pool_unavailable = ConnectionPool is None

    @contextmanager
    def connect(self, *, row_factory: Any | None = None) -> Iterator[object]:
        requested_row_factory = self.row_factory if row_factory is None else row_factory
        pool = self._pool_for(row_factory=requested_row_factory)
        self._checkout()
        try:
            if pool is None:
                with psycopg.connect(self.database_uri, row_factory=requested_row_factory) as conn:
                    yield _InstrumentedConnection(conn, self)
            else:
                with pool.connection() as conn:
                    yield _InstrumentedConnection(conn, self)
        finally:
            self._return()

    def close(self) -> None:
        pool = self._pool
        if pool is not None:
            pool.close()
            self._pool = None

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            return {
                "postgres_pool_enabled": int(self.pool_enabled),
                "postgres_pool_available": int(self.pool_enabled and self._pool is not None),
                "postgres_pool_fallback_direct": int(
                    (not self.pool_enabled) or self._pool_unavailable
                ),
                "postgres_connection_opened_total": self._opened_total,
                "postgres_connection_returned_total": self._returned_total,
                "postgres_connection_in_use": self._in_use,
                "postgres_active_connections": self._in_use,
                "active_connections": self._in_use,
                "postgres_query_total": self._query_total,
                "postgres_query_error_total": self._query_error_total,
                "postgres_slow_query_total": self._slow_query_total,
                "postgres_slow_query_threshold_ms": self.slow_query_threshold_ms,
            }

    def _pool_for(self, *, row_factory: Any) -> Any | None:
        if not self.pool_enabled or ConnectionPool is None:
            return None
        if row_factory is not self.row_factory:
            return None
        if self._pool is None:
            with self._lock:
                if self._pool is None:
                    self._pool = ConnectionPool(
                        self.database_uri,
                        min_size=self.min_size,
                        max_size=self.max_size,
                        kwargs={"row_factory": self.row_factory},
                        open=True,
                    )
        return self._pool

    def _checkout(self) -> None:
        with self._lock:
            self._opened_total += 1
            self._in_use += 1

    def _return(self) -> None:
        with self._lock:
            self._returned_total += 1
            self._in_use = max(0, self._in_use - 1)

    def _record_query(
        self, *, duration_ms: float, statement: Any, error: BaseException | None
    ) -> None:
        with self._lock:
            self._query_total += 1
            if error is not None:
                self._query_error_total += 1
            if duration_ms >= self.slow_query_threshold_ms:
                self._slow_query_total += 1
                should_warn = True
            else:
                should_warn = False
        if should_warn:
            logger.warning(
                "slow Postgres query observed",
                extra={
                    "duration_ms": duration_ms,
                    "threshold_ms": self.slow_query_threshold_ms,
                    "statement": _statement_label(statement),
                    "error": type(error).__name__ if error is not None else None,
                },
            )


class _InstrumentedConnection:
    def __init__(self, conn: object, provider: PostgresConnectionProvider) -> None:
        self._conn = conn
        self._provider = provider

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def cursor(self, *args: Any, **kwargs: Any) -> object:
        return _InstrumentedCursorContext(self._conn.cursor(*args, **kwargs), self._provider)


class _InstrumentedCursorContext:
    def __init__(self, cursor: object, provider: PostgresConnectionProvider) -> None:
        self._cursor = cursor
        self._provider = provider

    def __enter__(self) -> object:
        entered = self._cursor.__enter__()
        return _InstrumentedCursor(entered, self._provider)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> object:
        return self._cursor.__exit__(exc_type, exc, tb)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


class _InstrumentedCursor:
    def __init__(self, cursor: object, provider: PostgresConnectionProvider) -> None:
        self._cursor = cursor
        self._provider = provider

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)

    def execute(self, statement: Any, params: Any = None, *args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        error: BaseException | None = None
        try:
            if params is None:
                return self._cursor.execute(statement, *args, **kwargs)
            return self._cursor.execute(statement, params, *args, **kwargs)
        except BaseException as exc:
            error = exc
            raise
        finally:
            duration_ms = (time.monotonic() - started) * 1000.0
            self._provider._record_query(duration_ms=duration_ms, statement=statement, error=error)


def _statement_label(statement: Any) -> str:
    text = " ".join(str(statement).split())
    if len(text) <= 160:
        return text
    return text[:157] + "..."
